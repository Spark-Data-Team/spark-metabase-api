#!/usr/bin/env python3
"""Finitions V1 dashboard SEO Manucurist :
- déplace dashboard #25137 + cartes (#48633/#48634/#48635) dans la collection Manucurist
- filtres en dropdown (listes statiques Gamme/Catégorie)
- positions à 0 décimale (snapshot + grille)
- tri du snapshot (Gamme, Position)
- titres de tuiles propres + layout pleine largeur (vire le blanc)
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
DB=144; MODEL_ID=48633; GRID_ID=48634; SNAP_ID=48635; DASH_ID=25137; HTTP_TIMEOUT=300
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
def main():
    mb=connect(); print("connected")
    # 0) collection Manucurist
    colls=mb.get("/api/collection")
    cands=[c for c in colls if (c.get("name") or"").strip().lower()=="manucurist" and not c.get("archived")]
    if not cands:
        cands=[c for c in colls if "manucurist" in (c.get("name") or"").lower() and not c.get("archived")]
    print("collections Manucurist:", [(c["id"],c["name"]) for c in cands][:8])
    COLL = cands[0]["id"] if cands else None
    print("collection cible:", COLL)

    # 1) snapshot : viz décimales/titres + tri + collection
    snap_q={"database":DB,"type":"query","query":{
        "source-table":f"card__{MODEL_ID}",
        "fields":[fr("GAMME","type/Text"),fr("CATEGORIE","type/Text"),fr("KEYWORD","type/Text"),
                  fr("POSITION","type/Float"),fr("SEARCH_VOLUME","type/Float"),fr("CLICKS","type/Float")],
        "filter":["time-interval",fr("MONTH_DATE","type/Date"),"current","month"],
        "order-by":[["asc",fr("GAMME","type/Text")],["asc",fr("POSITION","type/Float")]]}}
    snap_viz={"column_settings":{
        json.dumps(["name","KEYWORD"]):{"column_title":"Mot-clé"},
        json.dumps(["name","GAMME"]):{"column_title":"Gamme"},
        json.dumps(["name","CATEGORIE"]):{"column_title":"Catégorie"},
        json.dumps(["name","POSITION"]):{"column_title":"Position","number_style":"decimal","decimals":0},
        json.dumps(["name","SEARCH_VOLUME"]):{"column_title":"Volume rech.","number_style":"decimal","decimals":0},
        json.dumps(["name","CLICKS"]):{"column_title":"Clics GSC","number_style":"decimal","decimals":0}},
        "table.column_formatting":[{"columns":["POSITION"],"type":"range","colors":["#84BB4C","#ED6E6E"],"min_type":"custom","min_value":1,"max_type":"custom","max_value":50}]}
    payload={"dataset_query":snap_q,"visualization_settings":snap_viz}
    if COLL: payload["collection_id"]=COLL
    print("snapshot:", getattr(mb.put(f"/api/card/{SNAP_ID}","raw",json=payload,timeout=HTTP_TIMEOUT),"status_code","?"))

    # 2) grille : décimales 0 sur la valeur 'avg' (ne PAS toucher dataset_query MLv2)
    d=mb.get(f"/api/card/{GRID_ID}")
    gviz=dict(d.get("visualization_settings") or {})
    cs=dict(gviz.get("column_settings") or {})
    cs[json.dumps(["name","avg"])]={"number_style":"decimal","decimals":0}
    gviz["column_settings"]=cs
    payload={"visualization_settings":gviz}
    if COLL: payload["collection_id"]=COLL
    print("grille:", getattr(mb.put(f"/api/card/{GRID_ID}","raw",json=payload,timeout=HTTP_TIMEOUT),"status_code","?"))

    # 3) modèle -> collection
    if COLL: print("modèle:", getattr(mb.put(f"/api/card/{MODEL_ID}","raw",json={"collection_id":COLL},timeout=120),"status_code","?"))

    # 4) dashboard : collection + dropdowns + layout pleine largeur + titres propres
    P_GAMME={"id":"gamme01","name":"Gamme","slug":"gamme","type":"string/=","sectionId":"string",
        "values_query_type":"list","values_source_type":"static-list",
        "values_source_config":{"values":["Gel Polish","Nail Polish","Nailcare"]}}
    P_CAT={"id":"categ01","name":"Catégorie","slug":"categorie","type":"string/=","sectionId":"string",
        "values_query_type":"list","values_source_type":"static-list",
        "values_source_config":{"values":["Transactionnel","Générique","Clean / Engagement","Produit","Informationnel"]}}
    def maps(card_id):
        return [{"parameter_id":"gamme01","card_id":card_id,"target":["dimension",fr("GAMME","type/Text")]},
                {"parameter_id":"categ01","card_id":card_id,"target":["dimension",fr("CATEGORIE","type/Text")]}]
    dashcards=[
      {"id":-1,"card_id":SNAP_ID,"row":0,"col":0,"size_x":24,"size_y":8,"series":[],
       "parameter_mappings":maps(SNAP_ID),"visualization_settings":{"card.title":"Snapshot du mois — position · volume · clics"}},
      {"id":-2,"card_id":GRID_ID,"row":8,"col":0,"size_x":24,"size_y":11,"series":[],
       "parameter_mappings":maps(GRID_ID),"visualization_settings":{"card.title":"Positions mois par mois"}},
    ]
    body={"parameters":[P_GAMME,P_CAT],"dashcards":dashcards}
    if COLL: body["collection_id"]=COLL
    r=mb.put(f"/api/dashboard/{DASH_ID}","raw",json=body,timeout=HTTP_TIMEOUT)
    bb=r.json() if hasattr(r,"json") else r
    print("dashboard:", getattr(r,"status_code","?"), "| dashcards:", len(bb.get("dashcards",[])) if isinstance(bb,dict) else "?",
          "| params dropdown:", [p.get("values_query_type") for p in (bb.get("parameters") or [])] if isinstance(bb,dict) else "?")
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> {dom}/dashboard/{DASH_ID}")
if __name__=="__main__":
    main()
