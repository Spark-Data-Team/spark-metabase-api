#!/usr/bin/env python3
"""Probe + backup pour le fix 'toggle de pliage' (Loom Manucurist) :
- compare les réglages pivot des 3 grilles : POSITIONS #48634 / SAISONNALITE #49426 (sans toggle)
  vs PAGES #49063 (qui A le toggle) -> isole le réglage qui pilote le +/-.
- trouve la text card des liens #13489 sur le dashboard #25137 + détecte les onglets.
- sauvegarde les JSON complets (cartes + dashboard) dans migration/ pour rollback.
Lecture seule côté Metabase (GET uniquement).
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DASH=25137; GRID=48634; SAIS=49426; PAGES=49063
BK = ROOT/"migration"; BK.mkdir(exist_ok=True)
TS = datetime.now().strftime("%Y%m%d-%H%M%S")

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex:
            print("retry connect:", repr(ex)[:120]); time.sleep(8)
    sys.exit("conn failed")

def main():
    mb=connect(); print("connected")
    for cid,label in [(GRID,"POSITIONS #48634"),(SAIS,"SAISONNALITE #49426"),(PAGES,"PAGES #49063 (A le toggle)")]:
        c=mb.get(f"/api/card/{cid}")
        (BK/f"card-{cid}-backup-{TS}.json").write_text(json.dumps(c,ensure_ascii=False,indent=2))
        viz=c.get("visualization_settings") or {}
        piv=[k for k in viz if k.startswith("pivot")]
        print(f"\n=== {label} ===")
        print("  display                 :", c.get("display"))
        print("  pivot.show_row_totals   :", viz.get("pivot.show_row_totals"))
        print("  pivot.show_column_totals:", viz.get("pivot.show_column_totals"))
        print("  pivot_table.collapsed_rows:", viz.get("pivot_table.collapsed_rows"))
        print("  toutes clés pivot*      :", piv)
    d=mb.get(f"/api/dashboard/{DASH}")
    (BK/f"dashboard-{DASH}-backup-{TS}.json").write_text(json.dumps(d,ensure_ascii=False,indent=2))
    tabs=d.get("tabs") or d.get("ordered_tabs")
    print(f"\n=== DASHBOARD #{DASH} ===")
    print("  tabs:", "AUCUN" if not tabs else f"{len(tabs)} -> {[t.get('name') for t in tabs]}")
    dcs=d.get("dashcards") or d.get("ordered_cards") or []
    print("  dashcards:", len(dcs))
    for dc in dcs:
        vs=dc.get("visualization_settings") or {}
        t=vs.get("text") or ""
        if "13489" in t:
            print("  >> SAISO TEXT CARD dashcard_id:", dc.get("id"), "| card_id:", dc.get("card_id"))
            print("  >> TEXTE ACTUEL:\n----\n"+t+"\n----")
    print("\nBackups TS:", TS, "->", BK)

if __name__=="__main__":
    main()
