#!/usr/bin/env python3
"""Audit LECTURE SEULE des clauses d'exclusion brand sur le sous-arbre 11673
(+ nos cartes 13884/13885). Règle métier (user, 2026-06-11) : l'exclusion brand
doit tester campaign_TYPE uniquement ; toute clause testant channel / category /
network / product / name est FAUSSE.

Sortie : migration/brand-clause-audit.json + résumé console.
Usage : .venv/bin/python scripts/audit_brand_clause.py
"""
import json, re, sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from archive_collections import connect_resilient
import conv_lib

# toute condition « ... campaign_<col> ... NOT LIKE '%brand%' »
RX = re.compile(r"campaign_(\w+)\s*,\s*''\s*\)\s*\)\s*NOT\s+LIKE\s*'%brand%'", re.I)

def main():
    mb = connect_resilient()
    inv = json.loads((REPO / "migration" / "temporal-unit-inventory.json").read_text())
    ids = sorted({c["id"] for c in inv["cards"]})
    ids += [49095, 49096, 49097, 49098, 49100, 49101, 49102, 49103, 49104, 49105, 49106, 49107]
    print("cartes à scanner:", len(ids))

    def scan(cid):
        try:
            c = mb.get(f"/api/card/{cid}")
            sql, _ = conv_lib.native_and_tags(c)
            cols = sorted({m.group(1).lower() for m in RX.finditer(sql)})
            return {"id": cid, "name": c.get("name"), "collection": c.get("collection_id"),
                    "cols": cols, "archived": c.get("archived", False)}
        except Exception as e:
            return {"id": cid, "error": str(e)[:120]}

    with ThreadPoolExecutor(8) as ex:
        out = list(ex.map(scan, ids))

    errors = [o for o in out if "error" in o]
    with_brand = [o for o in out if o.get("cols")]
    wrong = [o for o in with_brand if o["cols"] != ["type"]]
    print(f"erreurs: {len(errors)} | avec clause brand: {len(with_brand)} | "
          f"correctes (type seul): {len(with_brand) - len(wrong)} | FAUSSES: {len(wrong)}")
    for combo, n in Counter(tuple(o["cols"]) for o in wrong).most_common():
        print(f"  {n:5d} cartes testent {list(combo)}")
    (REPO / "migration" / "brand-clause-audit.json").write_text(json.dumps(out, ensure_ascii=False))
    print("audit sauvé: migration/brand-clause-audit.json")
    print("nos cartes (>=49095) à corriger:", sorted(o["id"] for o in wrong if o["id"] >= 49095))

if __name__ == "__main__":
    main()
