#!/usr/bin/env python3
"""Fixe le reliquat de l'anti-pattern A : LEFT JOIN kp__keyword_monthly_metrics
sur keyword SEUL (sans language/zone) dans 4 cartes SERP.

Contexte : l'audit anti-pattern (migration/antipattern-audit-results.json) avait
identifié 8 cartes BUG « A ». Vérification live 2026-07-02 : 4 sont déjà corrigées
(28512, 28206, 16708, 34378) et 4 gardent UN join monthly buggé (le join aggregated
de ces mêmes cartes a déjà été fixé — on reproduit exactement ce style).

Effet du bug : fan-out multi-(language,zone) pour un client multi-zones -> volumes
mensuels gonflés (~1.49x mesuré, cf. migration/antipattern-empirical.json).

Sécurité (pattern batch_brand_fix) :
1. dry-run par défaut : affiche les diffs, n'écrit rien.
2. Remplacement de chaîne EXACT (pas de regex) : si la ligne attendue est absente
   ou présente plusieurs fois, la carte est SAUTÉE et signalée.
3. Snapshot JSON de chaque carte avant PUT -> migration/kp-join-fix-snapshots/.
4. re-GET après PUT : le SQL persisté contient bien les 2 conditions ajoutées.

Usage :
  .venv/bin/python scripts/fix_kp_monthly_join_cards.py          # dry-run
  .venv/bin/python scripts/fix_kp_monthly_join_cards.py --yes    # applique
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from archive_collections import connect_resilient  # noqa: E402

SNAP_DIR = REPO / "migration" / "kp-join-fix-snapshots"

CARD_IDS = [28551, 28549, 28550, 28547]

OLD_JOIN = ("LEFT JOIN google_keyword_planner.kp__keyword_monthly_metrics "
            "ON kp__keyword_monthly_metrics.keyword = serp_requests.keyword,")
NEW_JOIN = ("LEFT JOIN google_keyword_planner.kp__keyword_monthly_metrics "
            "ON kp__keyword_monthly_metrics.keyword = serp_requests.keyword "
            "AND kp__keyword_monthly_metrics.language = serp_requests.language "
            "AND kp__keyword_monthly_metrics.zone = serp_requests.zone,")


def get_sql(card: dict) -> tuple[str, dict]:
    """SQL natif d'une carte, formats stages (récent) et legacy."""
    dq = card["dataset_query"]
    if "stages" in dq:
        return dq["stages"][0].get("native") or "", dq
    return (dq.get("native") or {}).get("query") or "", dq


def set_sql(dq: dict, sql: str) -> dict:
    if "stages" in dq:
        dq["stages"][0]["native"] = sql
    else:
        dq["native"]["query"] = sql
    return dq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="applique réellement (sinon dry-run)")
    args = ap.parse_args()
    mb = connect_resilient()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    ok, skipped = [], []
    for cid in CARD_IDS:
        card = mb.get(f"/api/card/{cid}")
        if not isinstance(card, dict):
            skipped.append((cid, f"GET KO: {card!r}"))
            continue
        sql, dq = get_sql(card)
        n = sql.count(OLD_JOIN)
        if n != 1:
            already = "AND kp__keyword_monthly_metrics.language" in sql
            skipped.append((cid, f"ligne attendue x{n}" + (" (déjà fixée ?)" if already else "")))
            continue

        new_sql = sql.replace(OLD_JOIN, NEW_JOIN)
        # gate : SEULE la ligne du join change
        assert new_sql.replace(NEW_JOIN, OLD_JOIN) == sql, f"gate statique KO carte {cid}"

        print(f"\n### {cid} — {card.get('name')}")
        for line in difflib.unified_diff(sql.splitlines(), new_sql.splitlines(),
                                         lineterm="", n=1):
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                print(f"  {line.strip()[:220]}")

        if not args.yes:
            ok.append(cid)
            continue

        (SNAP_DIR / f"{cid}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1))
        r = mb.put(f"/api/card/{cid}", "raw",
                   json={"dataset_query": set_sql(dq, new_sql)}, timeout=180)
        status = getattr(r, "status_code", r)
        # re-GET : le SQL persisté contient bien le nouveau join
        check, _ = get_sql(mb.get(f"/api/card/{cid}"))
        persisted = NEW_JOIN in check
        print(f"  PUT status={status} persisted={persisted}")
        (ok if persisted else skipped).append(cid if persisted else (cid, f"PUT status={status}, non persisté"))

    mode = "APPLIQUÉ" if args.yes else "DRY-RUN"
    print(f"\n[{mode}] OK: {ok} | SKIP: {skipped}")


if __name__ == "__main__":
    main()
