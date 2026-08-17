#!/usr/bin/env python3
"""Applique le retour Loom Manucurist (dashboard #25137) :
1) TOGGLE DE PLIAGE par Marché sur POSITIONS #48634 + SAISONNALITE #49426
   -> pivot.show_column_totals=True  (sous-total de groupe = porte le +/-),
      pivot.show_row_totals=False     (pas de colonne 'Row totals' across-mois superflue).
   PUT visualization_settings SEULEMENT -> ne touche pas dataset_query (préserve MLv2 + result_metadata).
2) RETRAIT des liens Metabase #13489 (cassés hors embed -> mur de login) de la text card Saisonnalité.
Backups préalables: scripts/seo_collapse_probe.py (migration/*-backup-*.json).
"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DASH=25137; GRID=48634; SAIS=49426; HTTP_TIMEOUT=300
SAIS_DASHCARD=131700
NEW_TEXT=("### 🗓️ Saisonnalité\n"
          "Volume de recherche mensuel par mot-clé sur les **24 derniers mois** "
          "(source : Google Keyword Planner).")
DC_FIELDS=("id","card_id","dashboard_tab_id","row","col","size_x","size_y",
           "series","parameter_mappings","visualization_settings")

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex:
            print("retry connect:", repr(ex)[:120]); time.sleep(8)
    sys.exit("conn failed")

def enable_toggle(mb,cid,label):
    c=mb.get(f"/api/card/{cid}")
    viz=dict(c.get("visualization_settings") or {})
    before=(viz.get("pivot.show_row_totals"),viz.get("pivot.show_column_totals"))
    viz["pivot.show_column_totals"]=True
    viz["pivot.show_row_totals"]=False
    r=mb.put(f"/api/card/{cid}","raw",json={"visualization_settings":viz},timeout=HTTP_TIMEOUT)
    print(f"  PUT {label} #{cid}: {getattr(r,'status_code','?')} | (row,col) {before} -> (False, True)")

def main():
    mb=connect(); print("connected")
    print("--- 1) toggle de pliage ---")
    enable_toggle(mb,GRID,"POSITIONS")
    enable_toggle(mb,SAIS,"SAISONNALITE")

    print("--- 2) retrait liens #13489 ---")
    d=mb.get(f"/api/dashboard/{DASH}")
    dcs=d.get("dashcards") or []
    out=[]; edited=False
    for dc in dcs:
        nd={k:dc.get(k) for k in DC_FIELDS if k in dc}
        if dc.get("id")==SAIS_DASHCARD:
            vs=dict(dc.get("visualization_settings") or {})
            assert "13489" in (vs.get("text") or ""), "text card saiso inattendue (pas de 13489)"
            vs["text"]=NEW_TEXT; nd["visualization_settings"]=vs; edited=True
        out.append(nd)
    assert edited, "dashcard saiso introuvable"
    body={"parameters":d.get("parameters") or [], "dashcards":out}
    if d.get("tabs"): body["tabs"]=d["tabs"]
    r=mb.put(f"/api/dashboard/{DASH}","raw",json=body,timeout=HTTP_TIMEOUT)
    bb=r.json() if hasattr(r,"json") else r
    n=len(bb.get("dashcards") or []) if isinstance(bb,dict) else "?"
    print(f"  PUT dashboard #{DASH}: {getattr(r,'status_code','?')} | dashcards {n}/{len(dcs)}")

    print("--- 3) vérification post-PUT (re-GET) ---")
    okc=True
    for cid,label in [(GRID,"POSITIONS"),(SAIS,"SAISONNALITE")]:
        v=mb.get(f"/api/card/{cid}").get("visualization_settings") or {}
        cok = v.get("pivot.show_column_totals") is True and v.get("pivot.show_row_totals") is False
        okc &= cok
        print(f"  {label} #{cid}: show_column_totals={v.get('pivot.show_column_totals')} show_row_totals={v.get('pivot.show_row_totals')} {'OK' if cok else 'KO'}")
    dd=mb.get(f"/api/dashboard/{DASH}")
    txt=next((dc.get("visualization_settings",{}).get("text","") for dc in (dd.get("dashcards") or []) if dc.get("id")==SAIS_DASHCARD),"")
    link_gone = "13489" not in txt and "metabaseapp.com" not in txt
    print(f"  text card saiso: liens #13489 retirés={link_gone}")
    print(f"  TEXTE FINAL:\n----\n{txt}\n----")
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> {'TOUT OK' if (okc and link_gone) else '⚠️ VERIF INCOMPLETE'}  {dom}/dashboard/{DASH}")

if __name__=="__main__":
    main()
