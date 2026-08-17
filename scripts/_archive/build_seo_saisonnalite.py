#!/usr/bin/env python3
"""Saisonnalité — volume de recherche historique par mot-clé | Manucurist.
Modèle kp (34 kw, 24 mois, par marché/gamme) + carte pivot [marché,kw] × mois × volume.
"""
from __future__ import annotations
import json, sys, time, uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
import build_seo_monitoring_v3 as V3
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; COLL=13752; HTTP_TIMEOUT=480
MODEL_NAME="SEO Saisonnalité — Manucurist (model)"
PIVOT_NAME="SEO — Saisonnalité (volume de recherche / mois) | Manucurist"
u=lambda: str(uuid.uuid4())

MODEL_SQL=f"""
WITH kw_map AS (
  SELECT * FROM (VALUES
    {V3.VALUES}
  ) AS t(keyword, marche, gamme, categorie)
),
zone_map AS (
  SELECT keyword, marche, gamme,
         CASE marche WHEN 'FR' THEN 'France' WHEN 'US' THEN 'United States' END AS zone
  FROM kw_map
),
base AS (
  SELECT z.marche, z.gamme, z.keyword, TO_DATE(km.month||'-01','YYYY-MM-DD') AS month_date,
         COALESCE(km.adjusted_avg_searches, km.avg_monthly_searches, 0) AS search_volume
  FROM zone_map z
    JOIN google_keyword_planner.kp__keyword_monthly_metrics km
      ON LOWER(km.keyword)=z.keyword AND km.zone=z.zone
  WHERE km.month >= TO_CHAR(DATEADD('month', -24, CURRENT_DATE),'YYYY-MM')
)
SELECT marche, gamme, keyword, month_date, search_volume
FROM base
QUALIFY ROW_NUMBER() OVER (PARTITION BY marche, keyword, month_date ORDER BY search_volume DESC) = 1
ORDER BY marche, keyword, month_date DESC
"""

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception: time.sleep(8)
    sys.exit("conn failed")

def run(mb,sql):
    r=mb.post("/api/dataset","raw",json={"database":DB,"type":"native","native":{"query":sql}},timeout=HTTP_TIMEOUT)
    j=r.json()
    if j.get("error"): return None,str(j["error"])
    d=j["data"]; return {"cols":d["cols"],"rows":d["rows"]},None

def upsert(mb,name,model,payload):
    kind="dataset" if model else "card"
    for it in mb.get(f"/api/collection/{COLL}/items?limit=2000").get("data",[]):
        if it.get("model")==kind and it.get("name")==name:
            mb.put(f"/api/card/{it['id']}","raw",json=payload,timeout=HTTP_TIMEOUT); return it["id"],"maj"
    b=mb.post("/api/card","raw",json=payload,timeout=HTTP_TIMEOUT).json(); return b.get("id"),"créé"

def main():
    mb=connect(); print("connected")
    res,err=run(mb, MODEL_SQL)
    if err: print("ÉCHEC SQL:",err[:600]); sys.exit(1)
    cols=[c["name"] for c in res["cols"]]; rows=res["rows"]
    nkw=len({r[cols.index("KEYWORD")] for r in rows}); nmo=len({r[cols.index("MONTH_DATE")] for r in rows})
    print(f"modèle saisonnalité: {len(rows)} lignes, {nkw} kw, {nmo} mois")
    if nkw<25: print("⚠️ trop peu de kw — stop"); sys.exit(1)

    MID,how=upsert(mb,MODEL_NAME,True,{"name":MODEL_NAME,"type":"model","collection_id":COLL,
        "dataset_query":{"database":DB,"type":"native","native":{"query":MODEL_SQL}},
        "display":"table","visualization_settings":{},
        "description":"Saisonnalité : volume de recherche mensuel (kp) par mot-clé, 24 mois, par marché/gamme. Voir aussi le template #13489 (48 mois)."})
    print(f"modèle {how} #{MID}")
    rm,_=run(mb, f"SELECT * FROM ({MODEL_SQL}) LIMIT 30")
    if rm: mb.put(f"/api/card/{MID}","raw",json={"result_metadata":rm["cols"]},timeout=120)

    def fl(name,bt,extra=None):
        o={"base-type":bt,"lib/uuid":u()}
        if extra:o.update(extra)
        return ["field",o,name]
    def fr(name,bt,extra=None):
        o={"base-type":bt}
        if extra:o.update(extra)
        return ["field",name,o]
    dq={"database":DB,"lib/type":"mbql/query","stages":[{
        "lib/type":"mbql.stage/mbql","source-card":MID,
        "aggregation":[["sum",{"lib/uuid":u()}, fl("SEARCH_VOLUME","type/Number")]],
        "breakout":[ fl("MARCHE","type/Text"), fl("KEYWORD","type/Text"),
                     fl("MONTH_DATE","type/Date",{"temporal-unit":"month"}) ]}]}
    viz={"pivot_table.column_split":{
            "rows":[fr("MARCHE","type/Text"),fr("KEYWORD","type/Text")],
            "columns":[fr("MONTH_DATE","type/Date",{"temporal-unit":"month"})],
            "values":[["aggregation",0]]},
        "pivot.show_row_totals":False,"pivot.show_column_totals":False,
        "column_settings":{json.dumps(["name","sum"]):{"number_style":"decimal","decimals":0}},
        "table.column_formatting":[{"columns":["sum"],"type":"range","colors":["#FFFFFF","#88BF4D"]}]}
    PID,how=upsert(mb,PIVOT_NAME,False,{"name":PIVOT_NAME,"collection_id":COLL,
        "dataset_query":dq,"display":"pivot","visualization_settings":viz,
        "description":"Saisonnalité : volume de recherche par mot-clé × mois (24 mois). Source modèle saisonnalité. Filtrable par marché/gamme/mot-clé."})
    print(f"pivot {how} #{PID}")
    legacy={"database":DB,"type":"query","query":{"source-table":f"card__{MID}",
        "aggregation":[["sum",fr("SEARCH_VOLUME","type/Number")]],
        "breakout":[fr("MARCHE","type/Text"),fr("KEYWORD","type/Text"),fr("MONTH_DATE","type/Date",{"temporal-unit":"month"})]}}
    jr=mb.post("/api/dataset","raw",json=legacy,timeout=HTTP_TIMEOUT).json()
    if not jr.get("error"): mb.put(f"/api/card/{PID}","raw",json={"result_metadata":jr["data"]["cols"]},timeout=120)
    print(f"\n>>> SAISONNALITÉ model #{MID} | pivot #{PID}")

if __name__=="__main__":
    main()
