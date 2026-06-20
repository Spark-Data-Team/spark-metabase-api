#!/usr/bin/env python3
"""Cartographie des routes de persistance réelles (Metabase v62).
Lectures + candidates d'activation pour la carte 48633 (persist = action voulue ; unpersist = no-op car déjà off)."""
from __future__ import annotations
import sys, time, json
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
    mb=connect(); print("connected | domain=",repr(mb.domain),"\n",flush=True)
    pj=mb.get("/api/persist"); items=pj.get("data") if isinstance(pj,dict) else pj
    pinfo=next((it for it in items if it.get("card_id")==48633), None)
    pid=pinfo.get("id") if pinfo else None
    print("PersistedInfo #48633: id=",pid," | champs=",sorted(pinfo.keys()) if pinfo else None,flush=True)
    if pinfo: print("  contenu:", json.dumps({k:pinfo.get(k) for k in pinfo}, default=str)[:500],flush=True)

    def T(verb,path,**kw):
        fn=mb.post if verb=="POST" else (mb.put if verb=="PUT" else mb.get)
        try:
            r=fn(path,"raw",timeout=60,**kw)
            print(f"  {verb:4s} {path} -> {getattr(r,'status_code','?')} | {getattr(r,'text','')[:120]}",flush=True)
        except Exception as ex:
            print(f"  {verb:4s} {path} -> EXC {repr(ex)[:90]}",flush=True)

    print("\n-- lectures (cartographie namespace) --",flush=True)
    if pid is not None: T("GET", f"/api/persist/{pid}")
    T("GET", "/api/persist/card/48633")

    print("\n-- candidates d'activation (persist=voulu / unpersist=no-op) --",flush=True)
    T("POST", "/api/card/48633/unpersist", json={})
    T("POST", "/api/persist/card/48633", json={})
    if pid is not None:
        T("POST", f"/api/persist/{pid}/refresh", json={})
    print("\nDONE",flush=True)

if __name__=="__main__":
    main()
