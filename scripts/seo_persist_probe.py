#!/usr/bin/env python3
"""Probe config persistance Metabase avant d'activer (lecture seule).
- réglage global + cron de refresh actuel + fuseau
- liste des modèles déjà persistés instance-wide (pour savoir si un cron global impacte d'autres projets)
- état persistance DB 144
"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex:
            print("retry connect:",repr(ex)[:100],flush=True); time.sleep(8)
    sys.exit("conn failed")

def main():
    mb=connect(); print("connected\n",flush=True)
    for s in ["persisted-models-enabled","persisted-model-refresh-cron-schedule","report-timezone","instance-creation"]:
        try: print(f"  {s} = {mb.get(f'/api/setting/{s}')!r}",flush=True)
        except Exception as ex: print(f"  {s}: {repr(ex)[:80]}",flush=True)
    print("\n--- modèles persistés instance-wide (/api/persist) ---",flush=True)
    try:
        pj=mb.get("/api/persist")
        items=pj.get("data") if isinstance(pj,dict) else pj
        if isinstance(items,list):
            print(f"  total = {len(items)}",flush=True)
            for it in items:
                print(f"  card_id={it.get('card_id')} db={it.get('database_id')} state={it.get('state')} "
                      f"active={it.get('active')} name={it.get('card_name')!r} schema={it.get('table_name')}",flush=True)
        else:
            print("  réponse:",str(pj)[:300],flush=True)
    except Exception as ex:
        print("  /api/persist:",repr(ex)[:120],flush=True)
    print("\n--- DB 144 ---",flush=True)
    try:
        db=mb.get("/api/database/144")
        print("  name:",db.get("name"),"| settings:",db.get("settings"),flush=True)
    except Exception as ex:
        print("  /api/database/144:",repr(ex)[:120],flush=True)
    print("\nDONE",flush=True)

if __name__=="__main__":
    main()
