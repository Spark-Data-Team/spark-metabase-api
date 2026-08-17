#!/usr/bin/env python3
"""Probe : SEARCH_VOLUME varie-t-il par mois dans le modèle #48633 ? (pour décider l'ajout volume au pivot inversé)"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
DB=144; MODEL=48633

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex: print("retry",repr(ex)[:80],flush=True); time.sleep(8)
    sys.exit("conn failed")

def fr(n,bt): return ["field",n,{"base-type":bt}]

def main():
    mb=connect(); print("connected",flush=True)
    q={"database":DB,"type":"query","query":{"source-table":f"card__{MODEL}",
        "fields":[fr("MARCHE","type/Text"),fr("KEYWORD","type/Text"),fr("MONTH_DATE","type/Date"),fr("SEARCH_VOLUME","type/Float")],
        "filter":["or",["=",fr("KEYWORD","type/Text"),"french manucure"],["=",fr("KEYWORD","type/Text"),"gel polish"]],
        "order-by":[["asc",fr("KEYWORD","type/Text")],["asc",fr("MONTH_DATE","type/Date")]]}}
    j=mb.post("/api/dataset","raw",json=q,timeout=240).json()
    if j.get("error"): print("ERR",str(j["error"])[:300],flush=True); return
    cols=[c["name"] for c in j["data"]["cols"]]
    print("cols:",cols,flush=True)
    for r in j["data"]["rows"]:
        print("  ",r,flush=True)

if __name__=="__main__":
    main()
