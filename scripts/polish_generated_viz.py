#!/usr/bin/env python3
"""Repolit la config d'affichage des dashcards pointant vers une carte GÉNÉRÉE (coll 13950) :
leur visualization_settings (table.columns / column_settings / series) référence encore les
ANCIENS noms de colonnes alors que la carte générée sort les nouveaux. On substitue avec le
sub_map COMPLET du client → titres/ordre/visibilité des colonnes reprennent correctement.

Usage : python3 scripts/polish_generated_viz.py --copy 25765 --client "Goodiespub" [--yes]
"""
import argparse, json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib
from migrate_dashboard_full import connect, load_inputs, _dcs

GEN_COLL = 14115  # même collection accessible que generate_fallback (cf. permissions)
ALL_OLD = (["CONVERSIONS", "CONVERSION_VALUE"]
           + [f"CONVERSIONS_{n}" for n in range(1, 20)]
           + [f"CONVERSION_{n}_VALUE" for n in range(1, 20)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()
    cmap = {int(k): v for k, v in load_inputs()[0].get(args.client, {}).items()}
    sub_map, _ = conv_lib.substitution_map(ALL_OLD, cmap)

    dash = mb.get(f"/api/dashboard/{args.copy}")
    new_dcs, polished = [], []
    for dc in _dcs(dash):
        cid = dc.get("card_id")
        nd = json.loads(json.dumps(dc))
        if cid:
            c = mb.get(f"/api/card/{cid}")
            if c.get("collection_id") == GEN_COLL and nd.get("visualization_settings"):
                before = json.dumps(nd["visualization_settings"])
                after = conv_lib.apply_substitution(before, sub_map)
                if after != before:
                    nd["visualization_settings"] = json.loads(after)
                    polished.append((cid, c.get("name")))
        new_dcs.append(nd)

    print(f"Dashboard {args.copy} — repolissage viz ({len(polished)} dashcards générés) :")
    for cid, n in polished:
        print(f"  {cid} {str(n)[:50]}")
    if not args.yes:
        print("(DRY-RUN)"); return
    if polished:
        put = {"dashcards": new_dcs}
        if dash.get("tabs"):
            put["tabs"] = dash["tabs"]
        res = mb.put(f"/api/dashboard/{args.copy}", "raw", json=put)
        print(f"PUT {args.copy}: {res.status_code}")


if __name__ == "__main__":
    main()
