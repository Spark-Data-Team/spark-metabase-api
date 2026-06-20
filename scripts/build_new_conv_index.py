#!/usr/bin/env python3
"""Indexe l'arbre des nouvelles conversions -> {(NEW_COL, shape) -> [card_id]} (JSON-encodé).
Par défaut depuis l'audit-cache (rapide) ; --live parcourt la collection 11673.
Une carte « pure nouvelle » (référence des colonnes nouvelles, aucune ancienne) est indexée
sous CHAQUE colonne nouvelle qu'elle somme, avec sa forme (display, metric_kind, breakdown) —
ce qui fait résoudre aussi les métriques dérivées (CAC/COS/CR/ROAS) par colonne+forme.
Usage:
  python3 scripts/build_new_conv_index.py            # depuis le cache
  python3 scripts/build_new_conv_index.py --live --root 11673
"""
import argparse, glob, json, sys
from collections import defaultdict
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib

def _index_card(card, index):
    if card.get("archived"):
        return
    sql, _ = conv_lib.native_and_tags(card)
    if not sql:
        return
    new = conv_lib.new_conversion_columns(sql)
    if not new or conv_lib.old_conversion_columns(sql):
        return  # pure-new cards only
    bd = conv_lib.card_breakdown(card)
    src = conv_lib.conversion_source(sql)
    entry = {"id": card["id"], "source": src, "display": card.get("display"),
             "kpis": list(conv_lib.kpi_signature(card)), "brand": conv_lib.brand_excluded(card)}
    for col in new:
        index[json.dumps([col, list(bd)])].append(entry)

def from_cache():
    index = defaultdict(list)
    n = 0
    for fp in glob.glob(str(REPO / "migration" / "audit-cache" / "card-*.json")):
        try:
            card = json.load(open(fp))
        except Exception:
            continue
        n += 1
        _index_card(card, index)
    return index, n

def from_live(root):
    from spark_metabase_api import Metabase_API
    from reorg_phase1 import _load_env
    e = _load_env()
    mb = Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])
    ids = []
    def walk(cid):
        r = mb.get(f"/api/collection/{cid}/items")
        for it in (r.get("data") if isinstance(r, dict) else r) or []:
            if it.get("model") == "collection":
                walk(it["id"])
            elif it.get("model") == "card":
                ids.append(it["id"])
    walk(root)
    index = defaultdict(list)
    for cid in ids:
        c = mb.get(f"/api/card/{cid}")
        if isinstance(c, dict):
            _index_card(c, index)
    return index, len(ids)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--root", type=int, default=11673)
    ap.add_argument("--out", default=None, help="chemin de sortie (défaut: migration/conv-new-index.json)")
    args = ap.parse_args()
    index, n = (from_live(args.root) if args.live else from_cache())
    out = Path(args.out) if args.out else REPO / "migration" / "conv-new-index.json"
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    multi = sum(1 for v in index.values() if len(v) > 1)
    print(f"{n} cards scanned -> {len(index)} (col,shape) keys ({multi} ambiguous/multi) -> {out}")

if __name__ == "__main__":
    main()
