#!/usr/bin/env python3
"""Vue 'Positions mois par mois' (pivot MBQL) sur le modèle #48633.
Lignes = mot-clé, colonnes = mois, valeur = position (DataForSEO/GSC). Couleur 1=vert.
Stocké MLv2 (évite la redirection ad-hoc). Démo bakée sur Manucurist (le modèle est déjà Manucurist).
"""
from __future__ import annotations
import json, sys, time, uuid, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
DB=144; SERP_COLLECTION=4809; MODEL_ID=48633; HTTP_TIMEOUT=300
NAME="SEO — Positions mois par mois (grille) | Manucurist"
def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception: time.sleep(8)
    sys.exit("conn failed")
u=lambda: str(uuid.uuid4())
def main():
    mb=connect(); print("connected")
    def fld(name,bt,extra=None):
        o={"base-type":bt,"lib/uuid":u()}
        if extra:o.update(extra)
        return ["field",o,name]
    dq={"database":DB,"lib/type":"mbql/query","stages":[{
        "lib/type":"mbql.stage/mbql","source-card":MODEL_ID,
        "aggregation":[["avg",{"lib/uuid":u()}, fld("POSITION","type/Float")]],
        "breakout":[ fld("KEYWORD","type/Text"), fld("MONTH_DATE","type/Date",{"temporal-unit":"month"}) ]}]}
    def sref(name,bt,extra=None):
        o={"base-type":bt}
        if extra:o.update(extra)
        return ["field",name,o]
    viz={"pivot_table.column_split":{
            "rows":[sref("KEYWORD","type/Text")],
            "columns":[sref("MONTH_DATE","type/Date",{"temporal-unit":"month"})],
            "values":[["aggregation",0]]},
         "column_settings":{json.dumps(["name","KEYWORD"]):{"column_title":"Mot-clé"}},
         "table.column_formatting":[{"columns":["avg"],"type":"range","colors":["#84BB4C","#ED6E6E"],
            "min_type":"custom","min_value":1,"max_type":"custom","max_value":50}]}
    pl={"name":NAME,"collection_id":SERP_COLLECTION,"dataset_query":dq,"display":"pivot",
        "visualization_settings":viz,
        "description":"Grille mensuelle des positions (mots-clés × mois). Source modèle #48633. Vert = bonne position. Vue C du gsheet."}
    # update-or-create
    existing=None
    for it in mb.get(f"/api/collection/{SERP_COLLECTION}/items?limit=2000").get("data",[]):
        if it.get("model")=="card" and it.get("name")==NAME: existing=it.get("id"); break
    if existing:
        mb.put(f"/api/card/{existing}","raw",json=pl,timeout=HTTP_TIMEOUT); PID=existing; print("maj #",PID)
    else:
        b=mb.post("/api/card","raw",json=pl,timeout=HTTP_TIMEOUT).json()
        if not b.get("id"): print("ÉCHEC:",str(b)[:500]); sys.exit(1)
        PID=b["id"]; print("créé #",PID)
    # result_metadata via legacy équivalent + rendu
    legacy={"database":DB,"type":"query","query":{"source-table":f"card__{MODEL_ID}",
        "aggregation":[["avg",["field","POSITION",{"base-type":"type/Float"}]]],
        "breakout":[["field","KEYWORD",{"base-type":"type/Text"}],
                    ["field","MONTH_DATE",{"base-type":"type/Date","temporal-unit":"month"}]]}}
    jr=mb.post("/api/dataset","raw",json=legacy,timeout=HTTP_TIMEOUT).json()
    if not jr.get("error"):
        mb.put(f"/api/card/{PID}","raw",json={"result_metadata":jr["data"]["cols"]},timeout=120)
        cols=[c["name"] for c in jr["data"]["cols"]]; rows=jr["data"]["rows"]
        ki=cols.index("KEYWORD"); mi=[i for i,c in enumerate(cols) if "MONTH" in c.upper()][0]; vi=len(cols)-1
        g=collections.defaultdict(dict); months=set()
        for r in rows:
            m=str(r[mi])[:7]; g[r[ki]][m]=r[vi]; months.add(m)
        months=sorted(months)[-6:]
        print(f"\nGRILLE positions — {len(g)} mots-clés × {len(months)} derniers mois\n")
        print("MOT-CLÉ".ljust(24)+" "+" ".join(x[2:] for x in months))
        for kw in sorted(g):
            print(kw[:23].ljust(24)+" "+" ".join((str(int(round(g[kw][m]))) if g[kw].get(m) is not None else ".").rjust(7) for m in months))
    # vérif moteur pivot
    jp=mb.post("/api/dataset/pivot","raw",json=legacy,timeout=HTTP_TIMEOUT).json()
    print("\n/api/dataset/pivot:", "OK "+str(len(jp["data"]["rows"]))+" lignes" if jp.get("data") else str(jp)[:150])
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> GRILLE #{PID}: {dom}/question/{PID}")
if __name__=="__main__":
    main()
