#!/usr/bin/env python3
"""Fixe le reliquat de l'anti-pattern A : LEFT JOIN kp__keyword_monthly_metrics
sur keyword SEUL (sans language/zone) dans 4 cartes SERP.

Contexte : l'audit anti-pattern (migration/antipattern-audit-results.json) avait
identifié 8 cartes BUG « A ». Vérification live 2026-07-02 : 4 sont déjà corrigées
(28512, 28206, 16708, 34378) et 4 gardent UN join monthly buggé (le join aggregated
de ces mêmes cartes a déjà été fixé — on reproduit exactement ce style).

Effet du bug : fan-out multi-(language,zone) pour un client multi-zones -> volumes
mensuels gonflés (~1.49x mesuré, cf. migration/antipattern-empirical.json).

Sécurité : c'est le MÊME anti-pattern A que fix_antipatterns.py corrige déjà (même
famille de cartes SERP). On délègue donc à son harnais `process()` plutôt que de
réimplémenter une variante plus faible. On récupère ainsi les garde-fous complets :
  1. dry-run par défaut : preuve seule, n'écrit rien.
  2. find/replace EXACT : si le find est absent (ou déjà corrigé), la carte est
     SAUTÉE et signalée, jamais corrompue.
  3. PREUVE LECTURE SEULE avant tout PUT : OLD et NEW exécutés via /api/dataset
     (mêmes substitutions de tags, scope client Tradis multi-zones) + GATE A —
     lignes(NEW) <= lignes(OLD), car retirer le fan-out ne peut que réduire les
     lignes ; abort sinon. (l'ancienne version ne vérifiait QUE la persistance de
     la chaîne, jamais l'exécution : un join subtilement faux passait pour un succès.)
  4. --yes : backup JSON + PUT, puis re-GET + run live ; REVERT auto si la carte casse.

Usage :
  .venv/bin/python scripts/fix_kp_monthly_join_cards.py          # dry-run (preuve)
  .venv/bin/python scripts/fix_kp_monthly_join_cards.py --yes    # applique + vérifie
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from fix_antipatterns import connect, process  # noqa: E402  (harnais A partagé : gate + revert)

CARD_IDS = [28551, 28549, 28550, 28547]

OLD_JOIN = ("LEFT JOIN google_keyword_planner.kp__keyword_monthly_metrics "
            "ON kp__keyword_monthly_metrics.keyword = serp_requests.keyword,")
NEW_JOIN = ("LEFT JOIN google_keyword_planner.kp__keyword_monthly_metrics "
            "ON kp__keyword_monthly_metrics.keyword = serp_requests.keyword "
            "AND kp__keyword_monthly_metrics.language = serp_requests.language "
            "AND kp__keyword_monthly_metrics.zone = serp_requests.zone,")

FIXES = [(OLD_JOIN, NEW_JOIN)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="applique réellement (sinon preuve/dry-run)")
    args = ap.parse_args()
    mb = connect()

    results = []
    for cid in CARD_IDS:
        card = mb.get(f"/api/card/{cid}")
        name = card.get("name") if isinstance(card, dict) else "?"
        res = process(mb, {"card_id": cid, "name": name}, FIXES, antipattern="A", apply=args.yes)
        results.append(res)

    mode = "APPLIQUÉ" if args.yes else "DRY-RUN (preuve)"
    ok = [r["id"] for r in results if r.get("status") in ("applied_ok", "proven", "already_fixed")]
    ko = [(r["id"], r.get("status")) for r in results if r.get("status") not in ("applied_ok", "proven", "already_fixed")]
    print(f"\n[{mode}] OK: {ok} | À VOIR: {ko}")


if __name__ == "__main__":
    main()
