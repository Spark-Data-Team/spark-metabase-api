#!/usr/bin/env python3
"""NOUVEAU dashboard corpus-driven | Manucurist.
- carte synthèse à plat (dernier mois, tri par clics) : Marché/Catégorie/Mot-clé/Volume/Position/Δ M-1/Clics/Impressions
- carte inversée (mois × mot-clé × Volume/Rank/Impr/Clics)
- filtres : Corpus (valeurs DYNAMIQUES depuis le modèle -> autonomie), Marché, Catégorie (dynamique),
  Top N par clics (nombre, défaut 25, mappé sur RANG_CLICS), Mot-clé contient/exact, Période.
Plages de couleurs discrètes validées (vert = rank, bleu = clics). #26061 et #25137 non touchés.
"""
from __future__ import annotations
import json, sys, time, uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; COLL=13752; TMO=600
MODEL_NAME="SEO Corpus Monitoring — Manucurist (model)"
SYNTH_NAME="SEO Corpus — synthèse du dernier mois (tri par clics) | Manucurist"
INV_NAME="SEO Corpus — évolution par mot-clé (mois en lignes) | Manucurist"
DASH_NAME="Suivi mots-clés par corpus | Manucurist"
DEFAULT_CORPUS="Mots-clés suivis FR"  # défaut = 1 seul corpus ; tous restent sélectionnables
u=lambda: str(uuid.uuid4())

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex: print("retry",repr(ex)[:80],flush=True); time.sleep(8)
    sys.exit("conn failed")

def fl(name,bt,extra=None):
    o={"base-type":bt,"lib/uuid":u()}
    if extra:o.update(extra)
    return ["field",o,name]
def fr(name,bt,extra=None):
    o={"base-type":bt}
    if extra:o.update(extra)
    return ["field",name,o]
def cs(name,opts): return {json.dumps(["name",name]):opts}
def dec0(t): return {"column_title":t,"number_style":"decimal","decimals":0}
def bands(col,kind):
    if kind=="rank":
        steps=[(3,"#0B5226"),(10,"#2E7D32"),(20,"#66BB6A"),(50,"#A5D6A7"),(100,"#E8F5E9")]; op="<="
    else:
        steps=[(100,"#2E6CA8"),(50,"#5B8DC0"),(25,"#9CC0E0"),(10,"#DCE9F5")]; op=">="
    return [{"columns":[col],"type":"single","operator":op,"value":v,"color":c} for v,c in steps]

def find(mb,kind,name):
    for it in mb.get(f"/api/collection/{COLL}/items?limit=2000").get("data",[]):
        if it.get("model")==kind and it.get("name")==name: return it["id"]
    return None
def upsert_card(mb,name,payload):
    cid=find(mb,"card",name)
    if cid: mb.put(f"/api/card/{cid}","raw",json=payload,timeout=TMO); return cid,"maj"
    b=mb.post("/api/card","raw",json=payload,timeout=TMO).json(); return b.get("id"),"créé"

def main():
    mb=connect(); print("connected",flush=True)
    MID=find(mb,"dataset",MODEL_NAME)
    if not MID: sys.exit("modèle corpus introuvable, lancer build_seo_corpus_model.py --apply d'abord")
    print("modèle #",MID,flush=True)

    # ---- carte synthèse (table plate, dernier mois complet, tri clics desc) ----
    synth_q={"database":DB,"type":"query","query":{"source-table":f"card__{MID}",
        "fields":[fr("MARCHE","type/Text"),fr("CATEGORY","type/Text"),fr("KEYWORD","type/Text"),
                  fr("SEARCH_VOLUME","type/Float"),fr("POSITION","type/Float"),fr("DELTA_M1","type/Float"),
                  fr("CLICKS","type/Float"),fr("IMPRESSIONS","type/Float")],
        "filter":["time-interval",fr("MONTH_DATE","type/Date"),-1,"month"],
        "order-by":[["desc",fr("CLICKS","type/Float")]]}}
    synth_viz={"column_settings":{
            **cs("MARCHE",{"column_title":"Marché"}),**cs("CATEGORY",{"column_title":"Catégorie"}),
            **cs("KEYWORD",{"column_title":"Mot-clé"}),**cs("SEARCH_VOLUME",dec0("Volume rech.")),
            **cs("POSITION",dec0("Position")),**cs("DELTA_M1",dec0("Évolution M-1")),
            **cs("CLICKS",dec0("Clics GSC")),**cs("IMPRESSIONS",dec0("Impressions"))},
        "table.column_formatting": bands("POSITION","rank")+bands("CLICKS","clics")}
    SYNTH,how=upsert_card(mb,SYNTH_NAME,{"name":SYNTH_NAME,"collection_id":COLL,"dataset_query":synth_q,
        "display":"table","visualization_settings":synth_viz,
        "description":"Synthèse du dernier mois complet pour le corpus et le marché choisis, classée du mot-clé le plus cliqué au moins cliqué. Position en vert (foncé = bonne position), clics en bleu."})
    print(f"synthèse {how} #{SYNTH}",flush=True)
    jr=mb.post("/api/dataset","raw",json=synth_q,timeout=TMO).json()
    if not jr.get("error"): mb.put(f"/api/card/{SYNTH}","raw",json={"result_metadata":jr["data"]["cols"]},timeout=120)

    # ---- carte inversée (pivot MLv2) ----
    inv_dq={"database":DB,"lib/type":"mbql/query","stages":[{
        "lib/type":"mbql.stage/mbql","source-card":MID,
        "aggregation":[
            ["sum",{"lib/uuid":u()}, fl("SEARCH_VOLUME","type/Number")],
            ["avg",{"lib/uuid":u()}, fl("POSITION","type/Number")],
            ["sum",{"lib/uuid":u()}, fl("IMPRESSIONS","type/Number")],
            ["sum",{"lib/uuid":u()}, fl("CLICKS","type/Number")]],
        "breakout":[ fl("MONTH_DATE","type/Date",{"temporal-unit":"month"}), fl("KEYWORD","type/Text") ]}]}
    inv_viz={"pivot_table.column_split":{
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
        "table.column_formatting": bands("avg","rank")+bands("sum_3","clics")}
    INV,how=upsert_card(mb,INV_NAME,{"name":INV_NAME,"collection_id":COLL,"dataset_query":inv_dq,
        "display":"pivot","visualization_settings":inv_viz,
        "description":"Les mois en lignes, les mots-clés en colonnes, et pour chacun son volume, son rank, ses impressions et ses clics. Filtré par corpus, marché et Top N par clics."})
    print(f"inversée {how} #{INV}",flush=True)
    legacy={"database":DB,"type":"query","query":{"source-table":f"card__{MID}",
        "aggregation":[["sum",fr("SEARCH_VOLUME","type/Number")],["avg",fr("POSITION","type/Number")],
                       ["sum",fr("IMPRESSIONS","type/Number")],["sum",fr("CLICKS","type/Number")]],
        "breakout":[fr("MONTH_DATE","type/Date",{"temporal-unit":"month"}),fr("KEYWORD","type/Text")]}}
    jr=mb.post("/api/dataset","raw",json=legacy,timeout=TMO).json()
    if not jr.get("error"): mb.put(f"/api/card/{INV}","raw",json={"result_metadata":jr["data"]["cols"]},timeout=120)

    # ---- dashboard ----
    did=find(mb,"dashboard",DASH_NAME)
    if not did:
        b=mb.post("/api/dashboard","raw",json={"name":DASH_NAME,"collection_id":COLL,
            "description":"Suivi mensuel des mots-clés par corpus Nanga. Choisis un corpus et un marché, le tableau montre les mots-clés les plus cliqués (Top N réglable) et leur évolution mois par mois. Les nouveaux corpus créés dans Nanga apparaissent automatiquement."}).json()
        did=b.get("id"); print("dashboard créé #",did,flush=True)
    else: print("dashboard existant #",did,flush=True)

    def dyn(field):
        return {"values_query_type":"list","values_source_type":"card",
                "values_source_config":{"card_id":MID,"value_field":["field",field,{"base-type":"type/Text"}]}}
    # filtre Marché retiré (2026-07-02, décision Thibaut) : 1 corpus = 1 langue = 1 marché,
    # le nom du corpus porte déjà le marché.
    P=[
      {"id":"corpus01","name":"Corpus","slug":"corpus","type":"string/=","sectionId":"string",
       "default":[DEFAULT_CORPUS], **dyn("CORPUS_NAME")},
      {"id":"categ01","name":"Catégorie","slug":"categorie","type":"string/=","sectionId":"string", **dyn("CATEGORY")},
      {"id":"topn01","name":"Top mots-clés (par clics)","slug":"top_n","type":"number/<=","sectionId":"number","default":[25]},
      {"id":"pat01","name":"Mot-clé (contient)","slug":"pattern_keyword","type":"string/contains","sectionId":"string"},
      {"id":"exact01","name":"Mot-clé (exact)","slug":"exact_keyword","type":"string/=","sectionId":"string"},
      {"id":"date01","name":"Période","slug":"date","type":"date/all-options","sectionId":"date","default":"past6months"},
    ]
    CO=fr("CORPUS_NAME","type/Text"); MA=fr("MARCHE","type/Text"); CA=fr("CATEGORY","type/Text")
    KW=fr("KEYWORD","type/Text"); RN=fr("RANG_CLICS","type/Number"); MO=fr("MONTH_DATE","type/Date")
    def m(pid,cid,field): return {"parameter_id":pid,"card_id":cid,"target":["dimension",field]}
    def maps(cid,with_date):
        l=[m("corpus01",cid,CO),m("categ01",cid,CA),
           m("topn01",cid,RN),m("pat01",cid,KW),m("exact01",cid,KW)]
        if with_date: l.append(m("date01",cid,MO))
        return l
    def txt(t): return {"text":t,"virtual_card":{"name":None,"display":"text","visualization_settings":{},"dataset_query":{},"archived":False},
        "text.align_vertical":"middle","text.align_horizontal":"left","dashcard.background":False}
    dashcards=[
      {"id":-1,"card_id":None,"row":0,"col":0,"size_x":24,"size_y":2,"series":[],"parameter_mappings":[],
       "visualization_settings":txt("## 📈 Vue d'ensemble du corpus\nLes mots-clés du corpus choisi sur le dernier mois complet, classés du plus au moins cliqué. Le filtre Top limite aux mots-clés les plus cliqués.")},
      {"id":-2,"card_id":SYNTH,"row":2,"col":0,"size_x":24,"size_y":9,"series":[],"parameter_mappings":maps(SYNTH,False),
       "visualization_settings":{"card.title":"Synthèse du dernier mois complet, triée par clics"}},
      {"id":-3,"card_id":None,"row":11,"col":0,"size_x":24,"size_y":2,"series":[],"parameter_mappings":[],
       "visualization_settings":txt("## 📊 Évolution par mot-clé\nLes mois en lignes, les mots-clés en colonnes, et pour chacun son volume, son rank, ses impressions et ses clics. Le rank est en vert (foncé = bonne position), les clics en bleu. Scrolle vers la droite pour voir tous les mots-clés.")},
      {"id":-4,"card_id":INV,"row":13,"col":0,"size_x":24,"size_y":12,"series":[],"parameter_mappings":maps(INV,True),
       "visualization_settings":{"card.title":"Évolution de chaque mot-clé mois après mois"}},
    ]
    r=mb.put(f"/api/dashboard/{did}","raw",json={"parameters":P,"dashcards":dashcards},timeout=TMO)
    bb=r.json() if hasattr(r,"json") else r
    print("dashboard PUT:",getattr(r,"status_code","?"),"| dashcards:",len(bb.get("dashcards",[])) if isinstance(bb,dict) else "?",
          "| filtres:",[p.get("slug") for p in (bb.get("parameters") or [])] if isinstance(bb,dict) else "?",flush=True)
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> DASHBOARD CORPUS #{did} : {dom}/dashboard/{did}",flush=True)

if __name__=="__main__":
    main()
