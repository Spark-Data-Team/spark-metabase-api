#!/usr/bin/env python3
"""Corrige la clause d'exclusion brand (-> campaign_type) sur des cartes données.

Par carte : GET -> conv_lib.fix_brand_clause(sql) ; si changement :
  - contrôle statique : il ne reste que des atomes campaign_type ;
  - run AVANT (params épinglés, brand_included au DÉFAUT 'yes' -> clause inerte) ;
  - snapshot JSONL ; PUT ; re-GET ; run APRÈS -> valeurs identiques sinon RESTORE.
Avec --show-no : run brand_included='no' avant/après pour MONTRER le changement
de comportement (attendu : c'est le correctif).

Usage :
  .venv/bin/python scripts/fix_brand_clause_cards.py --ids 49098,49100 --yes
  .venv/bin/python scripts/fix_brand_clause_cards.py --ids 42580 --yes --show-no
"""
import argparse, json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from archive_collections import connect_resilient
import conv_lib
from audit_brand_clause import RX

PIN = [
    {"type": "category", "target": ["dimension", ["template-tag", "clients"]], "value": ["Pro Nutrition"]},
    {"type": "date/all-options", "target": ["dimension", ["template-tag", "date"]], "value": "2026-05-01~2026-05-31"},
]
BRAND_NO = {"type": "category", "target": ["dimension", ["template-tag", "brand_included"]], "value": ["no"]}

def run_cells(mb, cid, tags, extra=()):
    params = [p for p in PIN if p["target"][1][1] in tags] + list(extra)
    r = mb.post(f"/api/card/{cid}/query", json={"parameters": params}, timeout=300)
    if r.get("status") != "completed":
        return None
    cols = [str(x.get("name")) for x in r["data"]["cols"]]
    return conv_lib.displayed_cells(cols, r["data"]["rows"], None)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True, help="ids de cartes, séparés par des virgules")
    ap.add_argument("--show-no", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    mb = connect_resilient()
    snap = open(REPO / "migration" / "snapshots" / "brand-fix-snapshots.jsonl", "a")
    n_fixed = 0
    for cid in ids:
        card = mb.get(f"/api/card/{cid}")
        dq = card["dataset_query"]
        st = dq["stages"][0] if "stages" in dq else dq["native"]
        key = "native" if "stages" in dq else "query"
        sql = st[key]
        fixed = conv_lib.fix_brand_clause(sql)
        if fixed == sql:
            print(f"{cid}: déjà conforme — rien à faire")
            continue
        rest = sorted({m.group(1).lower() for m in RX.finditer(fixed)})
        if rest != ["type"]:
            print(f"{cid}: ⛔ après correction il reste {rest} — carte SAUTÉE")
            continue
        _, tags = conv_lib.native_and_tags(card)
        before = run_cells(mb, cid, tags)
        before_no = run_cells(mb, cid, tags, [BRAND_NO]) if args.show_no and "brand_included" in tags else None
        if not args.yes:
            print(f"{cid}: clause corrigée (dry-run) — {card['name'][:55]!r}")
            continue
        snap.write(json.dumps(card) + "\n")
        st[key] = fixed
        resp = mb.put(f"/api/card/{cid}", "raw", json={"dataset_query": dq})
        if resp.status_code != 200:
            print(f"{cid}: ⛔ PUT {resp.status_code} — {resp.text[:120]}")
            continue
        after = run_cells(mb, cid, tags)
        if before is None or after != before:
            st[key] = sql
            mb.put(f"/api/card/{cid}", "raw", json={"dataset_query": dq})
            print(f"{cid}: ⛔ valeurs au défaut MODIFIÉES ({len(before or [])} vs {len(after or [])}) — RESTAURÉE")
            continue
        n_fixed += 1
        msg = f"{cid}: corrigée ✅ valeurs au défaut identiques ({len(after)} cellules)"
        if before_no is not None:
            after_no = run_cells(mb, cid, tags, [BRAND_NO])
            msg += f" | brand=no: {'CHANGE (attendu)' if after_no != before_no else 'identique'}"
        print(msg, f"— {card['name'][:50]!r}")
    snap.close()
    print(f"\n=> {n_fixed} carte(s) corrigée(s)")

if __name__ == "__main__":
    main()
