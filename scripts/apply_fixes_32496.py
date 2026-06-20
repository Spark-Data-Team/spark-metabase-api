#!/usr/bin/env python3
"""Applique les 3 fixes validés à l'ORIGINAL #32496 (table à plat).

Changements (validés par diff test, 0 régression) :
- supprime la CTE + INNER JOIN ctr_scenario (récupère positions > 100),
- supprime le code mort (4 CTE + 2 colonnes),
- dédup déterministe (meilleure position par url/crawl).
Garde TOUTES les colonnes de sortie + display=table + viz (nettoyée des
réglages pivot obsolètes). Backup déjà fait ; re-vérifie le run après PUT.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
import build_serp_pivot as B
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; CLIENT="Manucurist"; CORPUS="Corpus transactionnel FR - Mots clés stratégiques"

def main():
    mb=B.connect(); print("connected")
    d=mb.get("/api/card/32496")
    lq=d.get("legacy_query"); lq=json.loads(lq) if isinstance(lq,str) else lq
    orig_sql=lq["native"]["query"]; tags=dict(lq["native"].get("template-tags") or {})

    new_sql=B.transform(orig_sql, trim_columns=False)  # garde toutes les colonnes
    print(f"SQL: {len(orig_sql)} -> {len(new_sql)} chars")
    # garder les 6 colonnes finales
    assert "AS avg_search_volume" in new_sql and "AS nb_points" in new_sql and "AS avg_rank_group" in new_sql, "colonnes finales perdues!"

    print("validation compile (Manucurist)...")
    res,err=B.run_dataset(mb, B.substitute(new_sql))
    if err: print("  ÉCHEC COMPILE:", err[:400]); sys.exit(1)
    print(f"  OK: {len(res['rows'])} lignes, cols={[c.get('name') for c in res['cols']]}")

    tags.pop("ctr_scenario", None)
    params=[p for p in (d.get("parameters") or []) if p.get("slug")!="ctr_scenario"]
    viz=dict(d.get("visualization_settings") or {})
    viz.pop("table.pivot_column", None); viz.pop("table.cell_column", None)  # réglages pivot obsolètes

    payload={
      "name": d.get("name"),
      "collection_id": d.get("collection_id"),
      "dataset_query": {"database":DB,"type":"native","native":{"query":new_sql,"template-tags":tags}},
      "display": d.get("display"),               # reste 'table'
      "visualization_settings": viz,
      "parameters": params,
      "description": d.get("description"),
    }
    print("PUT #32496 ...")
    r=mb.put("/api/card/32496","raw",json=payload,timeout=180)
    print("  status:", getattr(r,"status_code","?"))

    # vérif run (table)
    P=[{"type":"string/=","value":[CLIENT],"target":["dimension",["template-tag","client"]]},
       {"type":"string/=","value":[CORPUS],"target":["dimension",["template-tag","corpus_name"]]},
       {"type":"string/=","value":["day"],"target":["dimension",["template-tag","time_period"]]},
       {"type":"date/all-options","value":"2026-03-01~2026-05-29","target":["dimension",["template-tag","date"]]}]
    rr=mb.post("/api/card/32496/query/json","raw",data={"parameters":json.dumps(P)},timeout=240)
    b=rr.json() if hasattr(rr,"json") else rr
    if isinstance(b,list): print(f"  RUN OK: {len(b)} lignes")
    else: print("  RUN ERR:", str((b.get('via') or [{}])[0].get('error') if isinstance(b,dict) else b)[:200])
    # confirme tag ctr_scenario retiré
    d2=mb.get("/api/card/32496")
    lq2=d2.get("legacy_query"); lq2=json.loads(lq2) if isinstance(lq2,str) else lq2
    print("  template-tags après:", list((lq2.get("native",{}).get("template-tags") or {}).keys()) if lq2 else "?")
    print("  display:", d2.get("display"))

if __name__=="__main__":
    main()
