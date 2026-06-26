#!/usr/bin/env python3
"""Aplatit un export CSV de la table Airtable « Conversions » vers le format attendu par
export_conv_mapping.py : [{client, type, new_type, platform}], en gérant les cellules
MULTI-SELECT (type/new_type = valeurs jointes par virgule), avec pairing POSITIONNEL quand
les cardinalités correspondent. Les lignes non pairables (cardinalités ≠) ET les new_type
« … OR … » (placeholder indécis) sont écrites en `migration/airtable-ambiguous.json` pour Gaby.

Usage : python3 scripts/flatten_airtable_csv.py /chemin/Conversions.csv
        -> migration/conv-airtable-rows-csv-<ts>.json  (+ airtable-ambiguous.json)
"""
import csv, json, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib

COLS = {"client": "brand_name", "type": "type", "new_type": "new_type", "platform": "platform_name"}


def main():
    src = Path(sys.argv[1])
    rows_out, ambiguous = [], []
    n = 0
    with open(src, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            n += 1
            client = (row.get(COLS["client"]) or "").strip()
            if not client:
                continue
            type_cell, nt_cell = row.get(COLS["type"]), row.get(COLS["new_type"])
            platform = (row.get(COLS["platform"]) or "").strip()
            pairs, amb = conv_lib.split_multiselect_pairs(type_cell, nt_cell)
            if amb:
                ambiguous.append({"client": client, "type": type_cell, "new_type": nt_cell,
                                  "platform": platform, "reason": "cardinalités multi-select ≠"})
            for t, nt in pairs:
                rows_out.append({"client": client, "type": t, "new_type": nt, "platform": platform})
                if nt and " OR " in nt:
                    ambiguous.append({"client": client, "type": t, "new_type": nt,
                                      "platform": platform, "reason": "new_type indécis (« … OR … »)"})

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPO / "migration" / f"conv-airtable-rows-csv-{ts}.json"
    out.write_text(json.dumps(rows_out, ensure_ascii=False, indent=0))
    (REPO / "migration" / "airtable-ambiguous.json").write_text(json.dumps(ambiguous, ensure_ascii=False, indent=2))
    print(f"{n} lignes CSV -> {len(rows_out)} enregistrements aplatis | {len(ambiguous)} ambiguës (Gaby)")
    print(f"-> {out}")
    print(f"-> migration/airtable-ambiguous.json")


if __name__ == "__main__":
    main()
