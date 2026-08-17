#!/usr/bin/env python3
"""Fixe les 9 cartes BUG « B » (regex Snowflake mal échappées) de l'audit anti-pattern.

Le bug type (varie par carte, cf. `analysis.reasoning` de l'audit) : dans une chaîne
single-quote Snowflake, `\\(` collapse en `\(` puis le backslash isolé est mangé ->
le métacaractère garde son sens regex (ex : '^\\(\\?i\\)' censé stripper un préfixe
littéral "(?i)" matche en fait une chaîne vide et ne strip RIEN -> mots-clés brand
pollués -> splits brand/non-brand faux). Forme sûre : classes de caractères `[(]`.

Source de vérité des fixes : `migration/antipattern-audit-results.json` — chaque
carte BUG « B » porte son `fix_find`/`fix_replace` EXACT prescrit par l'audit.
Ce script les consomme tels quels (aucune transformation maison).

Réutilise le harnais fix_antipatterns : dry-run par défaut (preuve /api/dataset
OLD vs NEW : counts + sommes numériques), gate « NEW compile », --yes = backup
JSON + PUT + re-GET + run live + revert auto. Snapshots dans
migration/regex-dot-fix-snapshots/ (écrits AVANT toute modification).

Usage :
  .venv/bin/python scripts/fix_regex_dot_cards.py          # dry-run (preuve)
  .venv/bin/python scripts/fix_regex_dot_cards.py --yes    # applique + vérifie
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from fix_antipatterns import connect, process, get_card  # noqa: E402

SNAP_DIR = REPO / "migration" / "regex-dot-fix-snapshots"
AUDIT = REPO / "migration" / "antipattern-audit-results.json"


def load_b_fixes():
    """{card_id: (name, fix_find, fix_replace)} pour les BUG « B » de l'audit."""
    data = json.loads(AUDIT.read_text())
    items = data if isinstance(data, list) else data.get("results", data.get("cards", []))
    out = {}
    for x in items:
        if str(x.get("final_verdict")) != "BUG" or str(x.get("antipattern")) != "B":
            continue
        a = x.get("analysis") or {}
        out[x["card_id"]] = (x.get("name", ""), a.get("fix_find"), a.get("fix_replace"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="applique réellement (sinon preuve/dry-run)")
    args = ap.parse_args()
    mb = connect()
    SNAP_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for cid, (name, find, repl) in sorted(load_b_fixes().items()):
        if not find or not repl:
            print(f"\n#{cid} {name[:60]} : pas de fix prescrit par l'audit -> À LA MAIN")
            results.append({"id": cid, "status": "no_prescribed_fix"})
            continue
        _, _, old_sql, _ = get_card(mb, cid)
        (SNAP_DIR / f"{cid}.sql").write_text(old_sql)
        if find not in old_sql:
            status = "already_fixed" if repl in old_sql else "find_absent_a_la_main"
            print(f"\n#{cid} {name[:60]} : find absent -> {status}")
            results.append({"id": cid, "status": status})
            continue
        results.append(process(mb, {"card_id": cid, "name": name}, [(find, repl)],
                               antipattern="B", apply=args.yes))

    print("\n=== bilan:", json.dumps(
        {str(r.get("id")): r.get("status") for r in results}, indent=1))


if __name__ == "__main__":
    main()
