#!/usr/bin/env python3
"""Phase 1 — tuile 'suivi inversé' Manucurist : MOIS en lignes × MOT-CLÉ en colonnes × [Rank, Impr, Clics].
Pivot MBQL (MLv2) sur le modèle #48633. Heatmap sur le Rank (1 vert -> 100 rouge).
Crée/maj la carte dans la collection Manucurist #13752. Imprime les noms de colonnes du résultat
(pour vérifier le mapping des agrégations avant de figer le formatage)."""
from __future__ import annotations
import json, sys, time, uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; COLL=13752; MODEL=48633; HTTP_TIMEOUT=480
CARD_NAME="SEO — Suivi inversé : Rank · Impr · Clics × mois (mots-clés en colonnes) | Manucurist"
u=lambda: str(uuid.uuid4())

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex:
            print("retry connect:",repr(ex)[:100],flush=True); time.sleep(8)
    sys.exit("conn failed")

def fl(name,bt,extra=None):
    o={"base-type":bt,"lib/uuid":u()}
    if extra:o.update(extra)
    return ["field",o,name]
def fr(name,bt,extra=None):
    o={"base-type":bt}
    if extra:o.update(extra)
    return ["field",name,o]

def bands(col,kind):
    """Plages discrètes (single-color). Ordre serré->large (1ère règle qui matche gagne)."""
    if kind=="rank":  # vert, foncé = bonne position (basse)
        steps=[(3,"#0B5226"),(10,"#2E7D32"),(20,"#66BB6A"),(50,"#A5D6A7"),(100,"#E8F5E9")]; op="<="
    else:             # clics, bleu, foncé = beaucoup
        steps=[(100,"#2E6CA8"),(50,"#5B8DC0"),(25,"#9CC0E0"),(10,"#DCE9F5")]; op=">="
    return [{"columns":[col],"type":"single","operator":op,"value":v,"color":c} for v,c in steps]

def upsert(mb,name,payload):
    for it in mb.get(f"/api/collection/{COLL}/items?limit=2000").get("data",[]):
        if it.get("model")=="card" and it.get("name")==name:
            mb.put(f"/api/card/{it['id']}","raw",json=payload,timeout=HTTP_TIMEOUT); return it["id"],"maj"
    b=mb.post("/api/card","raw",json=payload,timeout=HTTP_TIMEOUT).json(); return b.get("id"),"créé"

def main():
    mb=connect(); print("connected",flush=True)
    dq={"database":DB,"lib/type":"mbql/query","stages":[{
        "lib/type":"mbql.stage/mbql","source-card":MODEL,
        "aggregation":[
            ["sum",{"lib/uuid":u()}, fl("SEARCH_VOLUME","type/Number")],
            ["avg",{"lib/uuid":u()}, fl("POSITION","type/Number")],
            ["sum",{"lib/uuid":u()}, fl("IMPRESSIONS","type/Number")],
            ["sum",{"lib/uuid":u()}, fl("CLICKS","type/Number")]],
        "breakout":[ fl("MONTH_DATE","type/Date",{"temporal-unit":"month"}), fl("KEYWORD","type/Text") ]}]}
    viz={"pivot_table.column_split":{
            "rows":[fr("MONTH_DATE","type/Date",{"temporal-unit":"month"})],
            "columns":[fr("KEYWORD","type/Text")],
            "values":[["aggregation",0],["aggregation",1],["aggregation",2],["aggregation",3]]},
        "pivot.show_row_totals":False,"pivot.show_column_totals":False,
        "column_settings":{
            json.dumps(["name","MONTH_DATE"]):{"column_title":"Mois"},
            json.dumps(["name","KEYWORD"]):{"column_title":"Mot-clé"},
            json.dumps(["name","sum"]):{"column_title":"Volume","number_style":"decimal","decimals":0},
            json.dumps(["name","avg"]):{"column_title":"Rank","number_style":"decimal","decimals":0},
            json.dumps(["name","sum_2"]):{"column_title":"Impressions","number_style":"decimal","decimals":0},
            json.dumps(["name","sum_3"]):{"column_title":"Clics","number_style":"decimal","decimals":0}},
        "table.column_formatting": bands("avg","rank") + bands("sum_3","clics")}
    CID,how=upsert(mb,CARD_NAME,{"name":CARD_NAME,"collection_id":COLL,
        "dataset_query":dq,"display":"pivot","visualization_settings":viz,
        "description":"Suivi inversé : mois en lignes, mots-clés en colonnes ; sous chaque kw Volume (kp, ~constant car dernier connu) / Rank (avg POSITION, heatmap 1→100) / Impressions / Clics (GSC, échantillonné). Filtrable Marché/Gamme/Catégorie/Mot-clé/Période. Source modèle #48633."})
    print(f"card {how} #{CID}",flush=True)
    legacy={"database":DB,"type":"query","query":{"source-table":f"card__{MODEL}",
        "aggregation":[["sum",fr("SEARCH_VOLUME","type/Number")],["avg",fr("POSITION","type/Number")],["sum",fr("IMPRESSIONS","type/Number")],["sum",fr("CLICKS","type/Number")]],
        "breakout":[fr("MONTH_DATE","type/Date",{"temporal-unit":"month"}),fr("KEYWORD","type/Text")]}}
    jr=mb.post("/api/dataset","raw",json=legacy,timeout=HTTP_TIMEOUT).json()
    if jr.get("error"):
        print("ERR run:",str(jr["error"])[:400],flush=True)
    else:
        cols=jr["data"]["cols"]; rows=jr["data"]["rows"]
        print("COLS:", [(c.get("name"),c.get("display_name")) for c in cols],flush=True)
        print("nb lignes (mois×kw):",len(rows),flush=True)
        mb.put(f"/api/card/{CID}","raw",json={"result_metadata":cols},timeout=120)
        print("result_metadata posé",flush=True)
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> CARD #{CID} : {dom}/question/{CID}",flush=True)

if __name__=="__main__":
    main()
