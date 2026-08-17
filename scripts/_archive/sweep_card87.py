#!/usr/bin/env python3
"""Balayage READ-ONLY des 141 dashboards utilisant la carte 87 : pour chacun, est-ce que
le helper deploy_special_cards peut le traiter uniformément ? Catégorise :
  CLEAN          : ≥1 filtre Metric, AUCUN consommateur étranger -> helper OK
  BLOCKED_FOREIGN: un filtre Metric pilote aussi une carte non-87 -> manuel/Gaby
  NO_METRIC_PARAM: carte 87 présente mais aucun param dashboard ne pilote son tag metric
Plus : onglets, nb de filtres Metric, mappings vers tags absentes de 49788 (seront droppés).
Écrit migration/sweep-card87.json. Usage: python3 scripts/sweep_card87.py"""
import json, sys
from pathlib import Path
from collections import Counter
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib
import special_cards_lib as scl
from archive_collections import connect_resilient

OLD, NEW = 87, 49788


def main():
    mb = connect_resilient()
    new_tags = set(conv_lib.native_and_tags(mb.get(f"/api/card/{NEW}"))[1].keys())
    dlist = mb.get(f"/api/card/{OLD}/dashboards") or []
    ids = [(x.get("id") if isinstance(x, dict) else x) for x in dlist]
    rows, cat = [], Counter()
    for i, did in enumerate(ids):
        d = mb.get(f"/api/dashboard/{did}")
        if not isinstance(d, dict):
            rows.append({"id": did, "category": "UNREADABLE"}); cat["UNREADABLE"] += 1; continue
        sel = scl.selector_dashcards(d, OLD)
        pids = scl.metric_param_ids(d, OLD)
        foreign = scl.foreign_metric_consumers(d, pids, OLD)
        # mappings vers une tag absente de 49788 (seront droppés silencieusement)
        dropped = set()
        for dc in sel:
            for pm in dc.get("parameter_mappings") or []:
                t = scl._target_tag(pm.get("target"))
                if t is not None and t not in new_tags:
                    dropped.add(t)
        if not pids:
            c = "NO_METRIC_PARAM"
        elif foreign:
            c = "BLOCKED_FOREIGN"
        else:
            c = "CLEAN"
        cat[c] += 1
        rows.append({"id": did, "name": (d.get("name") or "")[:60], "category": c,
                     "n_card87": len(sel), "tabs": len(d.get("tabs") or []),
                     "metric_params": sorted(pids), "foreign": foreign, "dropped_tags": sorted(dropped)})
        if (i + 1) % 25 == 0:
            print(f"  ...{i+1}/{len(ids)}", flush=True)
    out = REPO / "migration" / "sweep-card87.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\n=== {len(ids)} dashboards carte 87 ===")
    for k, v in cat.most_common():
        print(f"  {k:16} {v}")
    n_tabs = sum(1 for r in rows if r.get("tabs"))
    n_drop = sum(1 for r in rows if r.get("dropped_tags"))
    n_multi = sum(1 for r in rows if len(r.get("metric_params") or []) > 1)
    print(f"  avec onglets: {n_tabs} | avec tags droppées: {n_drop} | >1 filtre Metric: {n_multi}")
    print(f"-> {out}")
    # liste des BLOCKED pour Gaby/manuel
    blk = [r for r in rows if r["category"] == "BLOCKED_FOREIGN"]
    if blk:
        print("\nBLOCKED_FOREIGN (filtre Metric partagé avec une carte non-87) :")
        for r in blk[:30]:
            print(f"  {r['id']:6} {r['name'][:42]:42} foreign={r['foreign']}")


if __name__ == "__main__":
    main()
