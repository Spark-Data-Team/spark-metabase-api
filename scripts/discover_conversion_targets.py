#!/usr/bin/env python3
"""Crawl tous les dashboards sous la collection 317 et liste les tuiles de conversion
(ancien système). Sortie: migration/conv-targets-<ts>.json (+ un lien stable conv-targets.json).
Le client est déduit du param 'client' du dashboard (fallback: nom de la collection cliente).
Usage: python3 scripts/discover_conversion_targets.py [--root 317]"""
import argparse, json, re, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
import conv_lib

TEMPLATE_RX = re.compile(r"template|\bspec\b|master|exemple|\bdemo\b", re.I)

def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])

def items(mb, cid):
    r = mb.get(f"/api/collection/{cid}/items")
    return (r.get("data") if isinstance(r, dict) else r) or []

def dashboards_under(mb, cid, acc):
    for it in items(mb, cid):
        if it.get("model") == "collection":
            dashboards_under(mb, it["id"], acc)
        elif it.get("model") == "dashboard":
            acc.append(it["id"])

def client_of(dash, fallback):
    for p in dash.get("parameters") or []:
        if p.get("slug") == "client" and p.get("default"):
            d = p["default"]
            return d[0] if isinstance(d, list) and d else d
    return fallback

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--root", type=int, default=317)
    args = ap.parse_args()
    mb = connect()
    clients = [(c["id"], c["name"]) for c in items(mb, args.root) if c.get("model") == "collection"]
    card_cache, out = {}, []
    n_dash = 0
    for coll_id, coll_name in clients:
        dl = []
        dashboards_under(mb, coll_id, dl)
        for did in dl:
            n_dash += 1
            full = mb.get(f"/api/dashboard/{did}")
            if not isinstance(full, dict):
                continue
            tiles = []
            for dc in (full.get("dashcards") or full.get("ordered_cards") or []):
                cid = dc.get("card_id")
                if not cid:
                    continue
                if cid not in card_cache:
                    card_cache[cid] = mb.get(f"/api/card/{cid}") or {}
                c = card_cache[cid]
                sql, _ = conv_lib.native_and_tags(c)
                oc = conv_lib.old_conversion_columns(sql)
                if oc:
                    tiles.append({"dashcard_id": dc["id"], "card_id": cid,
                                  "card_name": c.get("name"), "display": c.get("display"), "old_cols": sorted(oc)})
            if tiles:
                out.append({"client": client_of(full, coll_name), "collection_id": coll_id,
                            "dashboard_id": did, "dashboard_name": full.get("name"),
                            "is_template_like": bool(TEMPLATE_RX.search(full.get("name") or "")),
                            "n_tiles": len(tiles), "tiles": tiles})
        print(f"[{coll_name[:28]:28}] dashboards so far={n_dash} targets={len(out)}", flush=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    p = REPO / "migration" / f"conv-targets-{ts}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    (REPO / "migration" / "conv-targets.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nDONE: {len(clients)} clients | {n_dash} dashboards | {len(out)} with conversion tiles | "
          f"{sum(d['n_tiles'] for d in out)} tiles | template-like: {sum(d['is_template_like'] for d in out)}")
    print(f"-> {p}  (+ migration/conv-targets.json)")

if __name__ == "__main__":
    main()
