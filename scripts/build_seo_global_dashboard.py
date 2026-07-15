#!/usr/bin/env python3
"""Phase 1 — dashboard global de suivi mots-clés stratégiques | Manucurist (#26061).
- bloc synthèse DÉDIÉ (carte triée par CLICS décroissants, couleurs monochromes vert/bleu)
  -> ne touche pas le snapshot #48635 partagé avec le dashboard #25137.
- tableau détaillé inversé = #49557 (mois × kw × Volume/Rank/Impr/Clics), colonnes alphabétiques.
- filtres : Marché (FR/US, défaut FR), Gamme, Catégorie, Mot-clé (contient/exact), Période (6 mois).
Idempotent par nom (carte synthèse + dashboard)."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; COLL=13752; HTTP_TIMEOUT=300
MODEL=48633; INV=49557
SYNTH_NAME="SEO — Synthèse mots-clés (dernier mois, tri par clics) | Manucurist"
DASH_NAME="Suivi mots-clés stratégiques (global) | Manucurist"
GREEN=["#176D3A","#E8F4EA"]   # 1 = vert foncé -> 100 = clair
BLUE =["#EAF1F8","#4A6FA5"]   # faible = clair -> élevé = bleu pastel foncé

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex:
            print("retry connect:",repr(ex)[:100],flush=True); time.sleep(8)
    sys.exit("conn failed")

def fr(name,bt,extra=None):
    o={"base-type":bt}
    if extra:o.update(extra)
    return ["field",name,o]
def bands(col,kind):
    """Plages discrètes (single-color). Ordre serré->large (1ère règle qui matche gagne)."""
    if kind=="rank":
        steps=[(3,"#0B5226"),(10,"#2E7D32"),(20,"#66BB6A"),(50,"#A5D6A7"),(100,"#E8F5E9")]; op="<="
    else:
        steps=[(100,"#2E6CA8"),(50,"#5B8DC0"),(25,"#9CC0E0"),(10,"#DCE9F5")]; op=">="
    return [{"columns":[col],"type":"single","operator":op,"value":v,"color":c} for v,c in steps]
def cs(name,opts): return {json.dumps(["name",name]):opts}
def dec0(t): return {"column_title":t,"number_style":"decimal","decimals":0}

def upsert_card(mb,name,payload):
    for it in mb.get(f"/api/collection/{COLL}/items?limit=2000").get("data",[]):
        if it.get("model")=="card" and it.get("name")==name:
            mb.put(f"/api/card/{it['id']}","raw",json=payload,timeout=HTTP_TIMEOUT); return it["id"],"maj"
    b=mb.post("/api/card","raw",json=payload,timeout=HTTP_TIMEOUT).json(); return b.get("id"),"créé"

def build_synth(mb):
    q={"database":DB,"type":"query","query":{"source-table":f"card__{MODEL}",
        "fields":[fr("MARCHE","type/Text"),fr("GAMME","type/Text"),fr("CATEGORIE","type/Text"),fr("KEYWORD","type/Text"),
                  fr("SEARCH_VOLUME","type/Float"),fr("POSITION","type/Float"),fr("DELTA_M1","type/Float"),fr("CLICKS","type/Float")],
        "filter":["time-interval",fr("MONTH_DATE","type/Date"),-1,"month"],
        "order-by":[["desc",fr("CLICKS","type/Float")]]}}
    viz={"column_settings":{
            **cs("MARCHE",{"column_title":"Marché"}),**cs("GAMME",{"column_title":"Gamme"}),**cs("CATEGORIE",{"column_title":"Catégorie"}),
            **cs("KEYWORD",{"column_title":"Mot-clé"}),**cs("SEARCH_VOLUME",dec0("Volume rech.")),
            **cs("POSITION",dec0("Position")),**cs("DELTA_M1",dec0("Δ M-1")),**cs("CLICKS",dec0("Clics GSC"))},
        "table.column_formatting": bands("POSITION","rank") + bands("CLICKS","clics")}
    cid,how=upsert_card(mb,SYNTH_NAME,{"name":SYNTH_NAME,"collection_id":COLL,"dataset_query":q,"display":"table",
        "visualization_settings":viz,
        "description":"Synthèse mots-clés stratégiques (dernier mois complet), triée par CLICS décroissants. Position vert monochrome (1=foncé), Clics bleu monochrome. Pour repérer les kw à fort trafic. Filtrable Marché/Gamme/Catégorie/Mot-clé."})
    print(f"synthèse {how} #{cid}",flush=True)
    jr=mb.post("/api/dataset","raw",json=q,timeout=HTTP_TIMEOUT).json()
    if not jr.get("error"): mb.put(f"/api/card/{cid}","raw",json={"result_metadata":jr["data"]["cols"]},timeout=120)
    return cid

def find_dash(mb):
    for it in mb.get(f"/api/collection/{COLL}/items?limit=2000").get("data",[]):
        if it.get("model")=="dashboard" and it.get("name")==DASH_NAME:
            return it["id"]
    return None

def main():
    mb=connect(); print("connected",flush=True)
    SYNTH=build_synth(mb)
    did=find_dash(mb)
    if not did:
        b=mb.post("/api/dashboard","raw",json={"name":DASH_NAME,"collection_id":COLL,
            "description":"Suivi mensuel des mots-clés stratégiques. Synthèse triée par clics + tableau inversé (mois × kw × Volume/Rank/Impr/Clics). Couleurs monochromes (vert=Rank, bleu=Clics). Toggle Marché FR/US."}).json()
        did=b.get("id"); print("dashboard créé #",did,flush=True)
    else:
        print("dashboard existant #",did,flush=True)

    def DD(values): return {"values_query_type":"list","values_source_type":"static-list","values_source_config":{"values":values}}
    P=[
      {"id":"marche01","name":"Marché","slug":"marche","type":"string/=","sectionId":"string","default":"FR", **DD(["FR","US"])},
      {"id":"gamme01","name":"Gamme","slug":"gamme","type":"string/=","sectionId":"string", **DD(["Gel Polish","Nail Polish","Nailcare"])},
      {"id":"categ01","name":"Catégorie","slug":"categorie","type":"string/=","sectionId":"string", **DD(["Transactionnel","Générique","Clean / Engagement","Produit","Informationnel"])},
      {"id":"pat01","name":"Mot-clé (contient)","slug":"pattern_keyword","type":"string/contains","sectionId":"string"},
      {"id":"exact01","name":"Mot-clé (exact)","slug":"exact_keyword","type":"string/=","sectionId":"string"},
      {"id":"date01","name":"Période","slug":"date","type":"date/all-options","sectionId":"date","default":"past6months"},
    ]
    KW=fr("KEYWORD","type/Text"); MAR=fr("MARCHE","type/Text"); GAM=fr("GAMME","type/Text"); CAT=fr("CATEGORIE","type/Text"); MO=fr("MONTH_DATE","type/Date")
    def m(pid,cid,field): return {"parameter_id":pid,"card_id":cid,"target":["dimension",field]}
    synth_maps=[m("marche01",SYNTH,MAR),m("gamme01",SYNTH,GAM),m("categ01",SYNTH,CAT),m("pat01",SYNTH,KW),m("exact01",SYNTH,KW)]
    inv_maps=[m("marche01",INV,MAR),m("gamme01",INV,GAM),m("categ01",INV,CAT),m("pat01",INV,KW),m("exact01",INV,KW),m("date01",INV,MO)]
    def txt(t): return {"text":t,"virtual_card":{"name":None,"display":"text","visualization_settings":{},"dataset_query":{},"archived":False},
        "text.align_vertical":"middle","text.align_horizontal":"left","dashcard.background":False}
    dashcards=[
      {"id":-1,"card_id":None,"row":0,"col":0,"size_x":24,"size_y":1,"series":[],"parameter_mappings":[],
       "visualization_settings":txt("## 📈 Vue d'ensemble des mots-clés\nLe mot-clé, son volume de recherche, sa position et ses clics sur le dernier mois complet, classés du plus au moins cliqué. Filtrable par marché.")},
      {"id":-2,"card_id":SYNTH,"row":1,"col":0,"size_x":24,"size_y":9,"series":[],"parameter_mappings":synth_maps,
       "visualization_settings":{"card.title":"Synthèse des mots-clés classés par clics (dernier mois complet)"}},
      {"id":-3,"card_id":None,"row":10,"col":0,"size_x":24,"size_y":1,"series":[],"parameter_mappings":[],
       "visualization_settings":txt("## 📊 Évolution par mot-clé\nLes mois en lignes, les mots-clés en colonnes, et pour chacun son volume, son rank, ses impressions et ses clics. Le rank est en vert (foncé = bonne position), les clics en bleu (foncé = beaucoup de clics). Scrolle vers la droite pour voir tous les mots-clés.")},
      {"id":-4,"card_id":INV,"row":11,"col":0,"size_x":24,"size_y":12,"series":[],"parameter_mappings":inv_maps,
       "visualization_settings":{"card.title":"Évolution de chaque mot-clé mois après mois"}},
    ]
    body={"parameters":P,"dashcards":dashcards}
    r=mb.put(f"/api/dashboard/{did}","raw",json=body,timeout=HTTP_TIMEOUT)
    bb=r.json() if hasattr(r,"json") else r
    print("dashboard PUT:",getattr(r,"status_code","?"),"| dashcards:",len(bb.get("dashcards",[])) if isinstance(bb,dict) else "?",
          "| filtres:",[p.get("slug") for p in (bb.get("parameters") or [])] if isinstance(bb,dict) else "?",flush=True)
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> DASHBOARD #{did} : {dom}/dashboard/{did}",flush=True)

if __name__=="__main__":
    main()
