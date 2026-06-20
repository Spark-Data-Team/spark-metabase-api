#!/usr/bin/env python3
"""Debug endpoints persistance : version, droits, structure /api/setting, corps du 404 persist."""
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
    me=mb.get("/api/user/current")
    print("superuser =",me.get("is_superuser"),"| email =",me.get("email"),flush=True)
    try:
        props=mb.get("/api/session/properties")
        v=props.get("version") if isinstance(props,dict) else None
        print("version =", (v.get("tag") if isinstance(v,dict) else v),flush=True)
    except Exception as ex: print("version: ",repr(ex)[:90],flush=True)

    print("\n--- /api/setting structure ---",flush=True)
    allset=mb.get("/api/setting")
    print("type:",type(allset).__name__,"| len:",len(allset) if hasattr(allset,"__len__") else "?",flush=True)
    if isinstance(allset,list):
        for s in allset:
            if s.get("key") in ("report-timezone","persisted-models-enabled","persisted-model-refresh-cron-schedule","persisted-model-refresh-anchor-time"):
                print(f"  {s.get('key')} = {s.get('value')!r} (default={s.get('default')!r})",flush=True)

    print("\n--- test POST /api/card/48633/persist (corps réponse) ---",flush=True)
    r=mb.post("/api/card/48633/persist","raw",json={},timeout=60)
    print(f"  -> {getattr(r,'status_code','?')} | {getattr(r,'text','')[:300]}",flush=True)
    print("\nDONE",flush=True)

if __name__=="__main__":
    main()
