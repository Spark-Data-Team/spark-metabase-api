#!/usr/bin/env python3
"""Phase 1 — NOUVEAU dashboard global de suivi mots-clés stratégiques | Manucurist.
- bloc synthèse = snapshot #48635 (kw + volume + position + Δ + clics, dernier mois complet)
- tableau détaillé inversé = #49557 (mois × kw × Rank/Impr/Clics)
- filtres : Marché (FR/US, défaut FR), Gamme, Catégorie, Mot-clé (contient/exact), Période (6 mois)
- le toggle Marché filtre synthèse + détail.
Crée/maj le dashboard dans la collection Manucurist #13752 (idempotent par nom)."""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; COLL=13752; HTTP_TIMEOUT=300
SNAP=48635; INV=49557
DASH_NAME="Suivi mots-clés stratégiques (global) | Manucurist"

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

def find_dash(mb):
    for it in mb.get(f"/api/collection/{COLL}/items?limit=2000").get("data",[]):
        if it.get("model")=="dashboard" and it.get("name")==DASH_NAME:
            return it["id"]
    return None

def main():
    mb=connect(); print("connected",flush=True)
    did=find_dash(mb)
    if not did:
        b=mb.post("/api/dashboard","raw",json={"name":DASH_NAME,"collection_id":COLL,
            "description":"Suivi mensuel des mots-clés stratégiques. Synthèse (kw+volume+position) + tableau inversé (mois × kw × Rank/Impr/Clics) pour lire l'évolution et corréler ranking/impressions/clics. Toggle Marché FR/US."}).json()
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
    snap_maps=[m("marche01",SNAP,MAR),m("gamme01",SNAP,GAM),m("categ01",SNAP,CAT),m("pat01",SNAP,KW),m("exact01",SNAP,KW)]
    inv_maps=[m("marche01",INV,MAR),m("gamme01",INV,GAM),m("categ01",INV,CAT),m("pat01",INV,KW),m("exact01",INV,KW),m("date01",INV,MO)]
    def txt(t): return {"text":t,"virtual_card":{"name":None,"display":"text","visualization_settings":{},"dataset_query":{},"archived":False},
        "text.align_vertical":"middle","text.align_horizontal":"left","dashcard.background":False}
    dashcards=[
      {"id":-1,"card_id":None,"row":0,"col":0,"size_x":24,"size_y":1,"series":[],"parameter_mappings":[],
       "visualization_settings":txt("## 📈 Synthèse — sur quel mot-clé monter ?\nMot-clé · volume de recherche · position (dernier mois complet). Filtrable par marché.")},
      {"id":-2,"card_id":SNAP,"row":1,"col":0,"size_x":24,"size_y":9,"series":[],"parameter_mappings":snap_maps,
       "visualization_settings":{"card.title":"Synthèse — mot-clé · volume · position · clics (dernier mois complet)"}},
      {"id":-3,"card_id":None,"row":10,"col":0,"size_x":24,"size_y":1,"series":[],"parameter_mappings":[],
       "visualization_settings":txt("## 📊 Détail inversé — évolution par mot-clé\nMois en lignes, mot-clé en colonnes ; sous chaque kw **Rank · Impressions · Clics**. Rank en heatmap (vert = bon) — lu de haut en bas = trajectoire. Scroll horizontal pour parcourir les mots-clés.")},
      {"id":-4,"card_id":INV,"row":11,"col":0,"size_x":24,"size_y":12,"series":[],"parameter_mappings":inv_maps,
       "visualization_settings":{"card.title":"Évolution Rank · Impressions · Clics par mot-clé (mois en lignes)"}},
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
