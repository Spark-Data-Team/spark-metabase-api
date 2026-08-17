#!/usr/bin/env python3
"""Pose les descriptions rédigées du top 100 sur les cartes Metabase. Réversible.

Source : docs/superpowers/specs/2026-08-04-descriptions-top100.json (repo nanga-front),
120 cartes avec un champ `proposedDescription`.

Sécurité :
- Relecture LIVE de chaque carte avant écriture. On n'écrase QUE :
  description vide, `manual_verification`, ou description auto-générée
  (« KPIs: … Display: … », éventuellement précédée de « Breakdown by … »).
  Une vraie description humaine n'est JAMAIS écrasée (la carte est listée, pas écrite).
- Backup du JSON complet de chaque carte modifiée avant le PUT.
- Écrit rollback-<ts>.json ({id, name, before, after}) + un CSV de relecture.

Usage :
  python3 scripts/apply_top100_descriptions.py                  # dry-run (classe les 120)
  python3 scripts/apply_top100_descriptions.py --limit 5 --yes  # premier échantillon
  python3 scripts/apply_top100_descriptions.py --yes            # tout le reste
  python3 scripts/apply_top100_descriptions.py --rollback migration/.../rollback-<ts>.json --yes
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env, _check  # noqa: E402

SOURCE_JSON = Path.home() / (
    "Dev/Pro/nanga-front/docs/superpowers/specs/2026-08-04-descriptions-top100.json")
CAMPAIGN_DIR = REPO_ROOT / "migration" / "descriptions-top100-2026-08"
BACKUP_DIR = CAMPAIGN_DIR / "backups"

# Dumps auto posés one-shot vers 2025-04-30 : « KPIs: cost   Display: smartscalar »,
# parfois précédés de « Breakdown by <dimensions> » sur une ligne à part.
# DOTALL indispensable : le séparateur est un saut de ligne, pas un espace.
AUTO_DESC_RE = re.compile(r"^(Breakdown by .*?\s*)?KPIS?\s*:", re.IGNORECASE | re.DOTALL)

WRITABLE = ("vide", "manual_verification", "auto")


def connect_resilient() -> Metabase_API:
    """Connexion email/password (l'objet se ré-authentifie si la session expire)."""
    env = _load_env()
    domain, email, password = (env.get("METABASE_DOMAIN"), env.get("METABASE_EMAIL"),
                               env.get("METABASE_PASSWORD"))
    if not (domain and email and password):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env.")
    return Metabase_API(domain=domain, email=email, password=password)


def classify(live_desc: str, proposed: str) -> str:
    """Décide du sort d'une carte à partir de sa description live."""
    desc = (live_desc or "").strip()
    if not desc:
        return "vide"
    if desc == "manual_verification":
        return "manual_verification"
    if desc == proposed.strip():
        return "identique"          # déjà posée par nous, no-op
    if AUTO_DESC_RE.match(desc):
        return "auto"
    return "humaine"                # jamais touchée


def load_source() -> list[dict]:
    if not SOURCE_JSON.exists():
        sys.exit(f"Source introuvable : {SOURCE_JSON}")
    return json.loads(SOURCE_JSON.read_text())


def run(args):
    mb = connect_resilient()
    questions = load_source()
    if args.limit:
        questions = questions[: args.limit]

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rows, written, skipped = [], [], []

    for q in questions:
        cid, proposed = q["id"], q["proposedDescription"]
        live = mb.get(f"/api/card/{cid}")
        if not isinstance(live, dict):
            skipped.append((cid, "lecture échouée"))
            continue
        if live.get("archived"):
            skipped.append((cid, "archivée"))
            continue

        before = live.get("description") or ""
        state = classify(before, proposed)
        rows.append({"id": cid, "name": live.get("name", ""),
                     "collection": q.get("collection", ""), "etat": state,
                     "avant": before, "apres": proposed if state in WRITABLE else before})

        if state not in WRITABLE:
            skipped.append((cid, state))
            continue
        if not args.yes:
            continue

        (BACKUP_DIR / f"card_{cid}.json").write_text(
            json.dumps(live, ensure_ascii=False, indent=1))
        _check(mb.put(f"/api/card/{cid}", json={"description": proposed}),
               f"description carte {cid}")
        written.append({"id": cid, "name": live.get("name", ""),
                        "before": before, "after": proposed})
        print(f"  écrite #{cid} « {live.get('name', '')[:60]} »")

    from collections import Counter
    print("\n=== Classement des", len(rows), "cartes lues ===")
    for state, n in Counter(r["etat"] for r in rows).most_common():
        print(f"  {state:<20} {n:>4}")

    humaines = [r for r in rows if r["etat"] == "humaine"]
    if humaines:
        print(f"\n=== {len(humaines)} description(s) humaine(s) préservée(s) ===")
        for r in humaines:
            print(f"  #{r['id']}  {r['name'][:50]}  |  {r['avant'][:70]}")

    csv_path = CAMPAIGN_DIR / f"relecture-live-{ts}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "name", "collection", "etat", "avant", "apres"],
                           delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"\nCSV de relecture : {csv_path}")

    if not args.yes:
        print(f"\n(DRY-RUN — rien écrit. {sum(1 for r in rows if r['etat'] in WRITABLE)} "
              f"carte(s) seraient écrites. Relancer avec --yes.)")
        return

    rb = CAMPAIGN_DIR / f"rollback-{ts}.json"
    rb.write_text(json.dumps({"appliedAt": datetime.now().isoformat(),
                              "entries": written}, ensure_ascii=False, indent=1))
    print(f"\n=== {len(written)} écrite(s), {len(skipped)} sautée(s) ===")
    print(f"Rollback : {rb}")


def rollback(args):
    mb = connect_resilient()
    data = json.loads(Path(args.rollback).read_text())
    entries = data["entries"]
    print(f"Restauration de {len(entries)} description(s)...")
    if not args.yes:
        print("(DRY-RUN — relancer avec --yes.)")
        return
    for e in entries:
        _check(mb.put(f"/api/card/{e['id']}", json={"description": e["before"] or None}),
               f"rollback carte {e['id']}")
        print(f"  restaurée #{e['id']}")
    print(f"=== {len(entries)} restaurée(s) ===")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--yes", action="store_true", help="écrit réellement (sinon dry-run)")
    p.add_argument("--limit", type=int, help="ne traiter que les N premières cartes")
    p.add_argument("--rollback", help="chemin d'un rollback-<ts>.json à rejouer")
    args = p.parse_args()
    (rollback if args.rollback else run)(args)


if __name__ == "__main__":
    main()
