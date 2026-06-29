#!/usr/bin/env python3
"""Round-trip : lit le HANDOFF-consultants.csv une fois la colonne « ✍️ TA RÉPONSE » remplie par les
consultants, et produit les corrections de mapping à appliquer.

Sortie : migration/consultant-decisions.json = [{client, slot, new_type}] -> à fusionner dans
conv-client-mapping.json (puis re-run des dashboards de ces clients pour les débloquer).

Usage : python3 scripts/parse_consultant_answers.py migration/HANDOFF-consultants-REMPLI.csv
"""
import sys, csv, json, re
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "migration" / "HANDOFF-consultants.csv"
    rows = list(csv.DictReader(open(src, encoding="utf-8-sig")))
    decisions, skipped = [], 0
    for r in rows:
        ans = (r.get("✍️ TA RÉPONSE") or "").strip()
        ref = (r.get("ref") or "").strip()
        if not ans or not ref:
            skipped += 1
            continue
        try:
            client, slot, typ = ref.split("§")
        except ValueError:
            skipped += 1
            continue
        low = ans.lower()
        # « mélange » / « les deux » = vrai mélange, on ne tranche pas (reste data)
        if low in ("mélange", "melange", "les deux", "mix"):
            decisions.append({"client": client, "slot": int(slot), "new_type": "__MIXED__", "raw": ans})
            continue
        decisions.append({"client": client, "slot": int(slot), "new_type": ans, "raw": ans})
    out = REPO / "migration" / "consultant-decisions.json"
    out.write_text(json.dumps(decisions, ensure_ascii=False, indent=1))
    nclients = len({d["client"] for d in decisions})
    print(f"écrit {out} : {len(decisions)} décisions tranchées / {nclients} clients "
          f"({skipped} lignes sans réponse ignorées)")
    # aperçu par client
    from collections import Counter
    for c, n in Counter(d["client"] for d in decisions).most_common():
        print(f"   {c}: {n}")


if __name__ == "__main__":
    main()
