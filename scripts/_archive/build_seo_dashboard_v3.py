#!/usr/bin/env python3
"""Dashboard V3 — #25137 'Suivi mensuel des mots-clés SEO | Manucurist'.
Snapshot enrichi (15 col), 7 filtres, tuile saisonnalité + lien template #13489, sections.
"""
from __future__ import annotations
import json, sys, time, urllib.parse as ulib
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; COLL=13752; DASH=25137; HTTP_TIMEOUT=480
KW_MODEL=48633; GRID=48634; SNAP=48635; PAGES_PIVOT=49063; DELTA=49064; SAIS_PIVOT=49426
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
def cs(name,opts): return {json.dumps(["name",name]):opts}
def dec0(t): return {"column_title":t,"number_style":"decimal","decimals":0}

def main():
    mb=connect(); print("connected")
    # ---- Snapshot V3 (#48635) ----
    snap_q={"database":DB,"type":"query","query":{
        "source-table":f"card__{KW_MODEL}",
        "fields":[fr("MARCHE","type/Text"),fr("GAMME","type/Text"),fr("CATEGORIE","type/Text"),fr("KEYWORD","type/Text"),
                  fr("POSITION","type/Float"),fr("DELTA_M1","type/Float"),fr("DELTA_M3","type/Float"),
                  fr("SEARCH_VOLUME","type/Float"),fr("POTENTIEL_TRAFIC","type/Float"),
                  fr("CLICKS","type/Float"),fr("CLICKS_FR","type/Float"),fr("CLICKS_UK","type/Float"),
                  fr("CLICKS_US","type/Float"),fr("CLICKS_AUTRES","type/Float"),fr("URL_POSITIONNEE","type/Text")],
        "filter":["time-interval",fr("MONTH_DATE","type/Date"),-1,"month"],
        "order-by":[["asc",fr("MARCHE","type/Text")],["asc",fr("GAMME","type/Text")],["asc",fr("POSITION","type/Float")]]}}
    snap_viz={"column_settings":{
        **cs("MARCHE",{"column_title":"Marché"}),**cs("GAMME",{"column_title":"Gamme"}),**cs("CATEGORIE",{"column_title":"Catégorie"}),
        **cs("KEYWORD",{"column_title":"Mot-clé"}),**cs("POSITION",dec0("Position")),
        **cs("DELTA_M1",dec0("Δ M-1")),**cs("DELTA_M3",dec0("Δ M-3")),
        **cs("SEARCH_VOLUME",dec0("Volume rech.")),**cs("POTENTIEL_TRAFIC",dec0("Potentiel trafic")),
        **cs("CLICKS",dec0("Clics GSC")),**cs("CLICKS_FR",dec0("FR")),**cs("CLICKS_UK",dec0("UK")),
        **cs("CLICKS_US",dec0("US")),**cs("CLICKS_AUTRES",dec0("Autres")),
        **cs("URL_POSITIONNEE",{"column_title":"URL positionnée","view_as":"link"})},
        "table.column_formatting":[
          {"columns":["POSITION"],"type":"range","colors":["#84BB4C","#ED6E6E"],"min_type":"custom","min_value":1,"max_type":"custom","max_value":100},
          {"columns":["DELTA_M1","DELTA_M3"],"type":"range","colors":["#ED6E6E","#FFFFFF","#84BB4C"],"min_type":"custom","min_value":-10,"max_type":"custom","max_value":10}]}
    print("snapshot V3:", getattr(mb.put(f"/api/card/{SNAP}","raw",json={"dataset_query":snap_q,"display":"table",
        "visualization_settings":snap_viz,
        "description":"V3 — snapshot dernier mois complet: marché/gamme/catégorie/mot-clé, position+Δ M-1/M-3, volume, potentiel trafic (vol×CTR), clics GSC + split FR/UK/US/Autres, URL positionnée."},timeout=HTTP_TIMEOUT),"status_code","?"))
    jr=mb.post("/api/dataset","raw",json=snap_q,timeout=HTTP_TIMEOUT).json()
    if not jr.get("error"): mb.put(f"/api/card/{SNAP}","raw",json={"result_metadata":jr["data"]["cols"]},timeout=120)

    # ---- Filtres ----
    def DD(values): return {"values_query_type":"list","values_source_type":"static-list","values_source_config":{"values":values}}
    P=[
      {"id":"marche01","name":"Marché","slug":"marche","type":"string/=","sectionId":"string", **DD(["FR","US","UK","AUTRES"])},
      {"id":"gamme01","name":"Gamme","slug":"gamme","type":"string/=","sectionId":"string", **DD(["Gel Polish","Nail Polish","Nailcare"])},
      {"id":"categ01","name":"Catégorie","slug":"categorie","type":"string/=","sectionId":"string", **DD(["Transactionnel","Générique","Clean / Engagement","Produit","Informationnel"])},
      {"id":"marque01","name":"Marque / Hors Marque","slug":"marque","type":"string/=","sectionId":"string", **DD(["Marque","Hors Marque"])},
      {"id":"pat01","name":"Mot-clé (contient)","slug":"pattern_keyword","type":"string/contains","sectionId":"string"},
      {"id":"exact01","name":"Mot-clé (exact)","slug":"exact_keyword","type":"string/=","sectionId":"string"},
      {"id":"date01","name":"Période","slug":"date","type":"date/all-options","sectionId":"date","default":"past6months"},
    ]
    def m(pid,cid,field): return {"parameter_id":pid,"card_id":cid,"target":["dimension",field]}
    KW=fr("KEYWORD","type/Text"); MAR=fr("MARCHE","type/Text"); GAM=fr("GAMME","type/Text")
    CAT=fr("CATEGORIE","type/Text"); MQ=fr("MARQUE","type/Text"); MO=fr("MONTH_DATE","type/Date")
    def kw_maps(cid,with_date=False,with_cat=True):
        l=[m("marche01",cid,MAR),m("gamme01",cid,GAM),m("pat01",cid,KW),m("exact01",cid,KW)]
        if with_cat: l.append(m("categ01",cid,CAT))
        if with_date: l.append(m("date01",cid,MO))
        return l
    def page_maps(cid):
        return [m("marche01",cid,MAR),m("marque01",cid,MQ),m("date01",cid,MO)]

    def txt(t): return {"text":t,"virtual_card":{"name":None,"display":"text","visualization_settings":{},"dataset_query":{},"archived":False}}
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    def tmpl(corpus): return f"{dom}/dashboard/13489?client=Manucurist&corpus_name={ulib.quote(corpus)}&date=past48months"
    sais_link=("### 🗓️ Saisonnalité\nVolumes de recherche par mois. Vue détaillée **48 mois** (template #13489) — choisis le marché : "
               f"**[🇺🇸 US]({tmpl('Corpus transactionnel US')})**  ·  "
               f"**[🇫🇷 FR]({tmpl('Corpus transactionnel FR - Mots clés stratégiques')})**")
    dashcards=[
      {"id":-1,"card_id":None,"row":0,"col":0,"size_x":24,"size_y":1,"series":[],"parameter_mappings":[],"visualization_settings":txt("## 📊 Vision par mots-clés")},
      {"id":-2,"card_id":SNAP,"row":1,"col":0,"size_x":24,"size_y":9,"series":[],"parameter_mappings":kw_maps(SNAP),
       "visualization_settings":{"card.title":"Snapshot du dernier mois — position · Δ · volume · potentiel · clics (+ géo) · URL"}},
      {"id":-3,"card_id":GRID,"row":10,"col":0,"size_x":24,"size_y":11,"series":[],"parameter_mappings":kw_maps(GRID,with_date=True),
       "visualization_settings":{"card.title":"Positions mois par mois (100 = non classé)"}},
      {"id":-4,"card_id":None,"row":21,"col":0,"size_x":24,"size_y":1,"series":[],"parameter_mappings":[],"visualization_settings":txt(sais_link)},
      {"id":-5,"card_id":SAIS_PIVOT,"row":22,"col":0,"size_x":24,"size_y":9,"series":[],
       "parameter_mappings":[m("marche01",SAIS_PIVOT,MAR),m("gamme01",SAIS_PIVOT,GAM),m("pat01",SAIS_PIVOT,KW),m("exact01",SAIS_PIVOT,KW),m("date01",SAIS_PIVOT,MO)],
       "visualization_settings":{"card.title":"Saisonnalité — volume de recherche par mois (24 mois)"}},
      {"id":-6,"card_id":None,"row":31,"col":0,"size_x":24,"size_y":1,"series":[],"parameter_mappings":[],"visualization_settings":txt("## 📄 Vision par pages")},
      {"id":-7,"card_id":PAGES_PIVOT,"row":32,"col":0,"size_x":24,"size_y":9,"series":[],"parameter_mappings":page_maps(PAGES_PIVOT),
       "visualization_settings":{"card.title":"Clics par gabarit de page (Blog / Collections / Produits), mois par mois"}},
      {"id":-8,"card_id":DELTA,"row":41,"col":0,"size_x":24,"size_y":8,"series":[],"parameter_mappings":page_maps(DELTA),
       "visualization_settings":{"card.title":"Δ 6 mois par gabarit — gagne-t-on du trafic ?"}},
    ]
    r=mb.put(f"/api/dashboard/{DASH}","raw",json={"parameters":P,"dashcards":dashcards,
        "description":"V3 (gsheet Thibaut juin). 34 mots-clés stratégiques (16 US + 18 FR) par marché : position/Δ/volume/potentiel trafic/clics + split géo + URL positionnée ; saisonnalité ; clics par gabarit de page. Filtres : Marché, Gamme, Catégorie, Marque/Hors Marque, Mot-clé (contient/exact), Période."},timeout=HTTP_TIMEOUT)
    bb=r.json() if hasattr(r,"json") else r
    print("dashboard:",getattr(r,"status_code","?"),"| dashcards:",len(bb.get("dashcards",[])) if isinstance(bb,dict) else "?",
          "| filtres:",[p.get("slug") for p in (bb.get("parameters") or [])] if isinstance(bb,dict) else "?")
    print(f"\n>>> DASHBOARD V3: {dom}/dashboard/{DASH}")

if __name__=="__main__":
    main()
