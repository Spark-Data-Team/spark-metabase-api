#!/usr/bin/env python3
"""Assemblage V2 du dashboard #25137 'Suivi mensuel des mots-clés SEO | Manucurist'.

Usage: python3 scripts/build_seo_dashboard_v2.py <PAGES_MODEL_ID>

- maj snapshot #48635 : table mois M-1 (marché, kw, position, ΔM-1, Δ6M, volume, clics)
- maj grille #48634   : pivot [marché, kw] × mois → position (MLv2)
- crée pivot pages    : [marché, gabarit] × mois → clics (MLv2)
- crée table Δ gabarit: mois M-1, Δ6M% + tendance
- PUT dashboard : filtres Marché + Marque/Hors Marque (dropdowns), 4 tuiles pleine largeur
"""
from __future__ import annotations
import json, sys, time, uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; COLL=13752; KW_MODEL=48633; GRID_ID=48634; SNAP_ID=48635; DASH_ID=25137; HTTP_TIMEOUT=480
PAGES_MODEL=int(sys.argv[1]) if len(sys.argv)>1 else None
u=lambda: str(uuid.uuid4())

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception: time.sleep(8)
    sys.exit("conn failed")

def fr(name,bt,extra=None):
    o={"base-type":bt}
    if extra:o.update(extra)
    return ["field",name,o]
def fl(name,bt,extra=None):
    o={"base-type":bt,"lib/uuid":u()}
    if extra:o.update(extra)
    return ["field",o,name]
def cs(name,opts): return {json.dumps(["name",name]):opts}
def dec0(title): return {"column_title":title,"number_style":"decimal","decimals":0}

def upsert_card(mb,name,payload):
    existing=None
    for it in mb.get(f"/api/collection/{COLL}/items?limit=2000").get("data",[]):
        if it.get("model")=="card" and it.get("name")==name: existing=it.get("id"); break
    if existing:
        mb.put(f"/api/card/{existing}","raw",json=payload,timeout=HTTP_TIMEOUT); return existing,"maj"
    b=mb.post("/api/card","raw",json=payload,timeout=HTTP_TIMEOUT).json()
    return b.get("id"),"créé"

def set_meta(mb,cid,query_legacy):
    jr=mb.post("/api/dataset","raw",json=query_legacy,timeout=HTTP_TIMEOUT).json()
    if jr.get("error"): print(f"  meta #{cid} ERR:",str(jr["error"])[:200]); return None
    mb.put(f"/api/card/{cid}","raw",json={"result_metadata":jr["data"]["cols"]},timeout=120)
    return jr

def main():
    if not PAGES_MODEL: sys.exit("PAGES_MODEL_ID requis en argument")
    mb=connect(); print("connected")

    # ---- 1) SNAPSHOT (#48635) : table M-1 ----
    snap_q={"database":DB,"type":"query","query":{
        "source-table":f"card__{KW_MODEL}",
        "fields":[fr("MARCHE","type/Text"),fr("KEYWORD","type/Text"),fr("POSITION","type/Float"),
                  fr("DELTA_M1","type/Float"),fr("DELTA_6M","type/Float"),
                  fr("SEARCH_VOLUME","type/Float"),fr("CLICKS","type/Float")],
        "filter":["time-interval",fr("MONTH_DATE","type/Date"),-1,"month"],
        "order-by":[["asc",fr("MARCHE","type/Text")],["asc",fr("POSITION","type/Float")]]}}
    snap_viz={"column_settings":{
        **cs("MARCHE",{"column_title":"Marché"}), **cs("KEYWORD",{"column_title":"Mot-clé"}),
        **cs("POSITION",dec0("Position")), **cs("DELTA_M1",dec0("Δ vs M-1")),
        **cs("DELTA_6M",dec0("Δ 6 mois")), **cs("SEARCH_VOLUME",dec0("Volume rech.")),
        **cs("CLICKS",dec0("Clics GSC"))},
        "table.column_formatting":[
          {"columns":["POSITION"],"type":"range","colors":["#84BB4C","#ED6E6E"],"min_type":"custom","min_value":1,"max_type":"custom","max_value":100},
          {"columns":["DELTA_M1","DELTA_6M"],"type":"range","colors":["#ED6E6E","#FFFFFF","#84BB4C"],"min_type":"custom","min_value":-10,"max_type":"custom","max_value":10}]}
    r=mb.put(f"/api/card/{SNAP_ID}","raw",json={"dataset_query":snap_q,"display":"table",
        "visualization_settings":snap_viz,
        "description":"V2 — snapshot dernier mois complet : position (100=non classé), Δ vs M-1, Δ 6 mois (+=gagné), volume, clics, par marché."},timeout=HTTP_TIMEOUT)
    print("snapshot #%s:"%SNAP_ID, getattr(r,"status_code","?"))
    jr=set_meta(mb,SNAP_ID,snap_q)
    if jr: print("  lignes:",len(jr["data"]["rows"]))

    # ---- 2) GRILLE POSITIONS (#48634) : pivot [marché, kw] × mois (MLv2) ----
    grid_dq={"database":DB,"lib/type":"mbql/query","stages":[{
        "lib/type":"mbql.stage/mbql","source-card":KW_MODEL,
        "aggregation":[["avg",{"lib/uuid":u()}, fl("POSITION","type/Float")]],
        "breakout":[ fl("MARCHE","type/Text"), fl("KEYWORD","type/Text"),
                     fl("MONTH_DATE","type/Date",{"temporal-unit":"month"}) ]}]}
    grid_viz={"pivot_table.column_split":{
            "rows":[fr("MARCHE","type/Text"),fr("KEYWORD","type/Text")],
            "columns":[fr("MONTH_DATE","type/Date",{"temporal-unit":"month"})],
            "values":[["aggregation",0]]},
        "column_settings":{**cs("MARCHE",{"column_title":"Marché"}),**cs("KEYWORD",{"column_title":"Mot-clé"}),
                           **cs("avg",{"number_style":"decimal","decimals":0})},
        "table.column_formatting":[{"columns":["avg"],"type":"range","colors":["#84BB4C","#ED6E6E"],
            "min_type":"custom","min_value":1,"max_type":"custom","max_value":100}]}
    r=mb.put(f"/api/card/{GRID_ID}","raw",json={"dataset_query":grid_dq,"display":"pivot",
        "visualization_settings":grid_viz,"name":"SEO — Positions mois par mois (grille) | Manucurist",
        "description":"V2 — pivot [marché, mot-clé] × mois → position (100=non classé). Source modèle #48633."},timeout=HTTP_TIMEOUT)
    print("grille #%s:"%GRID_ID, getattr(r,"status_code","?"))
    grid_legacy={"database":DB,"type":"query","query":{"source-table":f"card__{KW_MODEL}",
        "aggregation":[["avg",fr("POSITION","type/Float")]],
        "breakout":[fr("MARCHE","type/Text"),fr("KEYWORD","type/Text"),
                    fr("MONTH_DATE","type/Date",{"temporal-unit":"month"})]}}
    set_meta(mb,GRID_ID,grid_legacy)

    # ---- 3) PIVOT PAGES : [marché, gabarit] × mois → clics (MLv2) ----
    pages_dq={"database":DB,"lib/type":"mbql/query","stages":[{
        "lib/type":"mbql.stage/mbql","source-card":PAGES_MODEL,
        "aggregation":[["sum",{"lib/uuid":u()}, fl("CLICKS","type/Number")]],
        "breakout":[ fl("MARCHE","type/Text"), fl("GABARIT","type/Text"),
                     fl("MONTH_DATE","type/Date",{"temporal-unit":"month"}) ]}]}
    pages_viz={"pivot_table.column_split":{
            "rows":[fr("MARCHE","type/Text"),fr("GABARIT","type/Text")],
            "columns":[fr("MONTH_DATE","type/Date",{"temporal-unit":"month"})],
            "values":[["aggregation",0]]},
        "column_settings":{**cs("MARCHE",{"column_title":"Marché"}),**cs("GABARIT",{"column_title":"Gabarit"}),
                           **cs("sum",{"number_style":"decimal","decimals":0})},
        "table.column_formatting":[{"columns":["sum"],"type":"range","colors":["#FFFFFF","#509EE3"]}]}
    PAGES_PIVOT,how=upsert_card(mb,"SEO — Clics par gabarit de page, mois par mois | Manucurist",{
        "name":"SEO — Clics par gabarit de page, mois par mois | Manucurist","collection_id":COLL,
        "dataset_query":pages_dq,"display":"pivot","visualization_settings":pages_viz,
        "description":"V2 — pivot [marché, gabarit] × mois → clics GSC (granularité requête, échantillonné). Filtrable Marque/Hors Marque. Source modèle pages."})
    print(f"pivot pages {how} #",PAGES_PIVOT)
    pages_legacy={"database":DB,"type":"query","query":{"source-table":f"card__{PAGES_MODEL}",
        "aggregation":[["sum",fr("CLICKS","type/Number")]],
        "breakout":[fr("MARCHE","type/Text"),fr("GABARIT","type/Text"),
                    fr("MONTH_DATE","type/Date",{"temporal-unit":"month"})]}}
    set_meta(mb,PAGES_PIVOT,pages_legacy)

    # ---- 4) TABLE Δ GABARIT (M-1) ----
    delta_q={"database":DB,"type":"query","query":{
        "source-table":f"card__{PAGES_MODEL}",
        "fields":[fr("MARCHE","type/Text"),fr("GABARIT","type/Text"),fr("MARQUE","type/Text"),
                  fr("CLICKS","type/Number"),fr("DELTA_6M_PCT","type/Number"),fr("TENDANCE","type/Text")],
        "filter":["time-interval",fr("MONTH_DATE","type/Date"),-1,"month"],
        "order-by":[["asc",fr("MARCHE","type/Text")],["asc",fr("GABARIT","type/Text")],["asc",fr("MARQUE","type/Text")]]}}
    delta_viz={"column_settings":{
        **cs("MARCHE",{"column_title":"Marché"}),**cs("GABARIT",{"column_title":"Gabarit"}),
        **cs("MARQUE",{"column_title":"Marque / Hors Marque"}),**cs("CLICKS",dec0("Clics (M-1)")),
        **cs("DELTA_6M_PCT",{"column_title":"Δ 6 mois %","number_style":"decimal","decimals":1,"suffix":" %"}),
        **cs("TENDANCE",{"column_title":"Tendance"})}}
    DELTA_ID,how=upsert_card(mb,"SEO — Δ 6 mois par gabarit | Manucurist",{
        "name":"SEO — Δ 6 mois par gabarit | Manucurist","collection_id":COLL,
        "dataset_query":delta_q,"display":"table","visualization_settings":delta_viz,
        "description":"V2 — dernier mois complet : clics, Δ 6 mois % et tendance par marché × gabarit × marque."})
    print(f"table Δ {how} #",DELTA_ID)
    set_meta(mb,DELTA_ID,delta_q)

    # ---- 5) DASHBOARD ----
    P_MARCHE={"id":"marche01","name":"Marché","slug":"marche","type":"string/=","sectionId":"string",
        "values_query_type":"list","values_source_type":"static-list",
        "values_source_config":{"values":["FR","US","UK","AUTRES"]}}
    P_MARQUE={"id":"marque01","name":"Marque / Hors Marque","slug":"marque","type":"string/=","sectionId":"string",
        "values_query_type":"list","values_source_type":"static-list",
        "values_source_config":{"values":["Marque","Hors Marque"]}}
    def m_marche(cid): return {"parameter_id":"marche01","card_id":cid,"target":["dimension",fr("MARCHE","type/Text")]}
    def m_marque(cid): return {"parameter_id":"marque01","card_id":cid,"target":["dimension",fr("MARQUE","type/Text")]}
    dashcards=[
      {"id":-1,"card_id":SNAP_ID,"row":0,"col":0,"size_x":24,"size_y":9,"series":[],
       "parameter_mappings":[m_marche(SNAP_ID)],
       "visualization_settings":{"card.title":"Snapshot du dernier mois — position · Δ · volume · clics"}},
      {"id":-2,"card_id":GRID_ID,"row":9,"col":0,"size_x":24,"size_y":11,"series":[],
       "parameter_mappings":[m_marche(GRID_ID)],
       "visualization_settings":{"card.title":"Positions mois par mois (100 = non classé)"}},
      {"id":-3,"card_id":PAGES_PIVOT,"row":20,"col":0,"size_x":24,"size_y":9,"series":[],
       "parameter_mappings":[m_marche(PAGES_PIVOT),m_marque(PAGES_PIVOT)],
       "visualization_settings":{"card.title":"Clics par gabarit de page (Blog / Collections / Produits), mois par mois"}},
      {"id":-4,"card_id":DELTA_ID,"row":29,"col":0,"size_x":24,"size_y":8,"series":[],
       "parameter_mappings":[m_marche(DELTA_ID),m_marque(DELTA_ID)],
       "visualization_settings":{"card.title":"Δ 6 mois par gabarit — gagne-t-on du trafic ?"}},
    ]
    r=mb.put(f"/api/dashboard/{DASH_ID}","raw",json={
        "parameters":[P_MARCHE,P_MARQUE],"dashcards":dashcards,
        "description":"V2 (gsheet Thibaut). 32 mots-clés stratégiques par marché (14 US + 18 FR) : position/Δ/volume/clics + clics par gabarit de page, filtres Marché & Marque/Hors Marque."},timeout=HTTP_TIMEOUT)
    bb=r.json() if hasattr(r,"json") else r
    print("dashboard:",getattr(r,"status_code","?"),"| dashcards:",len(bb.get("dashcards",[])) if isinstance(bb,dict) else "?")
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> DASHBOARD V2: {dom}/dashboard/{DASH_ID}")

if __name__=="__main__":
    main()
