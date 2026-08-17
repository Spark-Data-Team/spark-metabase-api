#!/usr/bin/env python3
"""Active la persistance des 3 modèles SEO Manucurist + cron de refresh quotidien 9h.
- lit report-timezone + cron actuel (propre, via /api/setting liste)
- POST /api/card/{id}/persist pour 48633 / 49062 / 49425 (matérialise + refresh planifié)
- PUT cron persisted-model-refresh-cron-schedule = quotidien 09:00 (Quartz)
- poll /api/persist jusqu'à state=persisted (ou timeout)
Réversible : POST /api/card/{id}/unpersist.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

MODELS={48633:"Positions",49062:"Pages",49425:"Saisonnalite"}
NEW_CRON="0 0 9 * * ? *"   # tous les jours à 09:00 (fuseau instance)

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex:
            print("retry connect:",repr(ex)[:100],flush=True); time.sleep(8)
    sys.exit("conn failed")

def getset(allset,k):
    for s in allset:
        if s.get("key")==k: return s.get("value")
    return None

def persist_state(mb):
    pj=mb.get("/api/persist"); items=pj.get("data") if isinstance(pj,dict) else pj
    return {it.get("card_id"):it for it in (items or []) if it.get("card_id") in MODELS}

def main():
    mb=connect(); print("connected\n",flush=True)
    allset=mb.get("/api/setting")
    tz=getset(allset,"report-timezone"); cur=getset(allset,"persisted-model-refresh-cron-schedule")
    print(f"  report-timezone (avant) = {tz!r}",flush=True)
    print(f"  cron persistance (avant) = {cur!r}\n",flush=True)

    print("--- activation persistance des 3 modèles ---",flush=True)
    for mid,lbl in MODELS.items():
        try:
            r=mb.post(f"/api/card/{mid}/persist","raw",json={},timeout=120)
            print(f"  persist #{mid} {lbl}: HTTP {getattr(r,'status_code','?')}",flush=True)
        except Exception as ex:
            print(f"  persist #{mid} {lbl}: EXC {repr(ex)[:80]}",flush=True)

    print("\n[cron global NON modifié ici — réglage instance partagé, décision séparée]",flush=True)

    print("\n--- poll matérialisation (max ~4 min) ---",flush=True)
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        st=persist_state(mb)
        line=" | ".join(f"#{mid}:{st.get(mid,{}).get('state')}" for mid in MODELS)
        print(f"  [{int(time.monotonic()%100000):05d}] {line}",flush=True)
        if st and all((st.get(mid,{}).get("state")=="persisted") for mid in MODELS):
            print("  -> tous persistés ✅",flush=True); break
        if any((st.get(mid,{}).get("state")=="error") for mid in MODELS):
            print("  -> ⚠️ au moins un en ERROR",flush=True)
            for mid in MODELS:
                e=st.get(mid,{}).get("error")
                if e: print(f"     #{mid} error: {str(e)[:200]}",flush=True)
            break
        time.sleep(12)

    allset2=mb.get("/api/setting")
    print(f"\n  cron persistance (après) = {getset(allset2,'persisted-model-refresh-cron-schedule')!r}",flush=True)
    st=persist_state(mb)
    for mid,lbl in MODELS.items():
        it=st.get(mid,{})
        print(f"  #{mid} {lbl}: state={it.get('state')} active={it.get('active')} refresh_end={it.get('refresh_end')}",flush=True)
    print("\nDONE",flush=True)

if __name__=="__main__":
    main()
