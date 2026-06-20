#!/usr/bin/env python3
"""Vue Snapshot + Dashboard dédié 'Suivi mensuel des mots-clés SEO | Manucurist'.
Assemble : Snapshot (table, mois courant) + Grille positions (#48634) + filtres Gamme/Catégorie.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
DB=144; SERP_COLLECTION=4809; MODEL_ID=48633; GRID_ID=48634; HTTP_TIMEOUT=300
SNAP_NAME="SEO — Snapshot mots-clés (mois courant) | Manucurist"
DASH_NAME="Suivi mensuel des mots-clés SEO | Manucurist"
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
    # 1) Snapshot card (MBQL table sur le modèle, mois courant)
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
        json.dumps(["name","POSITION"]):{"column_title":"Position"},
        json.dumps(["name","SEARCH_VOLUME"]):{"column_title":"Volume rech."},
        json.dumps(["name","CLICKS"]):{"column_title":"Clics GSC"}},
        "table.column_formatting":[{"columns":["POSITION"],"type":"range","colors":["#84BB4C","#ED6E6E"],
            "min_type":"custom","min_value":1,"max_type":"custom","max_value":50}]}
    snap_pl={"name":SNAP_NAME,"collection_id":SERP_COLLECTION,"dataset_query":snap_q,"display":"table",
             "visualization_settings":snap_viz,"description":"Snapshot mois courant : position/volume/clics par mot-clé (gamme/catégorie). Source modèle #48633. Vue A du gsheet."}
    existing=None
    for it in mb.get(f"/api/collection/{SERP_COLLECTION}/items?limit=2000").get("data",[]):
        if it.get("model")=="card" and it.get("name")==SNAP_NAME: existing=it.get("id"); break
    if existing:
        mb.put(f"/api/card/{existing}","raw",json=snap_pl,timeout=HTTP_TIMEOUT); SNAP=existing; print("snapshot maj #",SNAP)
    else:
        b=mb.post("/api/card","raw",json=snap_pl,timeout=HTTP_TIMEOUT).json()
        SNAP=b.get("id"); print("snapshot créé #",SNAP)
    jr=mb.post("/api/dataset","raw",json=snap_q,timeout=HTTP_TIMEOUT).json()
    if not jr.get("error"):
        mb.put(f"/api/card/{SNAP}","raw",json={"result_metadata":jr["data"]["cols"]},timeout=120)
        print("  snapshot lignes:", len(jr["data"]["rows"]))

    # 2) Dashboard
    existing_d=None
    for it in mb.get(f"/api/collection/{SERP_COLLECTION}/items?limit=2000").get("data",[]):
        if it.get("model")=="dashboard" and it.get("name")==DASH_NAME: existing_d=it.get("id"); break
    if existing_d:
        DID=existing_d; print("dashboard existant #",DID)
    else:
        bd=mb.post("/api/dashboard","raw",json={"name":DASH_NAME,"collection_id":SERP_COLLECTION,
            "description":"Suivi mensuel SEO des 15 mots-clés stratégiques Manucurist (gsheet). Position (DataForSEO/GSC) + Volume + Clics GSC, par gamme. V1."},timeout=HTTP_TIMEOUT).json()
        DID=bd.get("id"); print("dashboard créé #",DID)

    P_GAMME={"id":"gamme01","name":"Gamme","slug":"gamme","type":"string/=","sectionId":"string"}
    P_CAT={"id":"categ01","name":"Catégorie","slug":"categorie","type":"string/=","sectionId":"string"}
    def maps(card_id):
        return [{"parameter_id":"gamme01","card_id":card_id,"target":["dimension",fr("GAMME","type/Text")]},
                {"parameter_id":"categ01","card_id":card_id,"target":["dimension",fr("CATEGORIE","type/Text")]}]
    dashcards=[
      {"id":-1,"card_id":SNAP,"row":0,"col":0,"size_x":12,"size_y":8,"series":[],"parameter_mappings":maps(SNAP),"visualization_settings":{}},
      {"id":-2,"card_id":GRID_ID,"row":8,"col":0,"size_x":24,"size_y":10,"series":[],"parameter_mappings":maps(GRID_ID),"visualization_settings":{}},
    ]
    r=mb.put(f"/api/dashboard/{DID}","raw",json={"parameters":[P_GAMME,P_CAT],"dashcards":dashcards},timeout=HTTP_TIMEOUT)
    body=r.json() if hasattr(r,"json") else r
    ndc=len(body.get("dashcards",[])) if isinstance(body,dict) else "?"
    print("  PUT dashboard status:",getattr(r,"status_code","?"),"| dashcards:",ndc)
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> SNAPSHOT #{SNAP} | DASHBOARD #{DID}: {dom}/dashboard/{DID}")
if __name__=="__main__":
    main()
