#!/usr/bin/env python3
"""Résout CHAQUE tuile de conversion découverte (sans rien modifier) et produit :
- migration/conv-preflight.csv : worklist par tuile (client, dashboard, carte, statut, cible…)
- un résumé des statuts (la file de revue = tout ce qui n'est pas 'ok').
Cartes lues depuis l'audit-cache (rapide), fallback live pour les manquantes.
Usage: python3 scripts/conv_preflight.py [migration/conv-targets.json]"""
import csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib

CACHE = REPO / "migration" / "audit-cache"
_MB = [None]

def get_card(cid):
    p = CACHE / f"card-{cid}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    if _MB[0] is None:
        from spark_metabase_api import Metabase_API
        from reorg_phase1 import _load_env
        e = _load_env()
        _MB[0] = Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])
    return _MB[0].get(f"/api/card/{cid}") or {}

def main():
    targets = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "migration" / "conv-targets.json").read_text())
    mapping_all = json.loads((REPO / "migration" / "conv-client-mapping.json").read_text())
    raw = json.loads((REPO / "migration" / "conv-new-index.json").read_text())
    index = {}
    for k, v in raw.items():
        col, bd = json.loads(k)
        index[(col, tuple(bd))] = v

    rows, counts, per_client = [], Counter(), defaultdict(Counter)
    rescache = {}
    for d in targets:
        client = d["client"]
        cmap = {int(k): v for k, v in mapping_all.get(client, {}).items()}
        for t in d["tiles"]:
            cid = t["card_id"]
            key = (client, cid)
            if key not in rescache:
                rescache[key] = conv_lib.resolve_new_card(get_card(cid), cmap, index) if cmap \
                    else {"status": "no_client_mapping", "reason": f"client {client!r} absent du mapping"}
            res = rescache[key]
            st = res["status"]
            counts[st] += 1
            per_client[client][st] += 1
            rows.append({"client": client, "dashboard_id": d["dashboard_id"], "dashboard_name": d["dashboard_name"],
                         "is_template_like": d["is_template_like"], "dashcard_id": t["dashcard_id"],
                         "card_id": cid, "card_name": t["card_name"], "status": st,
                         "new_card_id": res.get("new_card_id"), "candidates": res.get("candidates"),
                         "new_type": res.get("new_type"), "source": res.get("source"),
                         "old_cols": ";".join(t.get("old_cols", [])), "reason": res.get("reason")})
    base = REPO / "migration"
    (base / "conv-preflight.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    with open(base / "conv-preflight.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v) for k, v in r.items()})
    print(f"{len(rows)} tiles | {len(targets)} dashboards | {len(per_client)} clients")
    print("status counts:", dict(counts.most_common()))
    auto = counts.get("ok", 0)
    print(f"AUTO-applicable (ok): {auto}/{len(rows)} = {100*auto//max(len(rows),1)}%")
    print("-> migration/conv-preflight.csv / .json")

if __name__ == "__main__":
    main()
