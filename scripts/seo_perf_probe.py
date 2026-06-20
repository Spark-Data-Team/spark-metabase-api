#!/usr/bin/env python3
"""Diagnostic perf dashboard SEO Manucurist #25137 :
- état RÉEL de la persistance (réglage global + PersistedInfo par modèle)
- timing à froid des requêtes (POST /api/card/{id}/query) pour localiser la lenteur.
Lecture seule (GET + .../query exécute mais ne modifie aucun objet).
"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

MODELS={48633:"Positions (SERP+GSC)",49062:"Pages (GSC 27M)",49425:"Saisonnalite (kp)"}
HEAVY ={48634:"Grille positions",49063:"Pivot pages"}
TMO=420

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
    # 1) réglage global de persistance
    try: print("setting persisted-models-enabled =", mb.get("/api/setting/persisted-models-enabled"),flush=True)
    except Exception as ex: print("setting persisted-models-enabled:",repr(ex)[:90],flush=True)
    # 2) état persistance par modèle
    print("\n--- persistance par modèle ---",flush=True)
    pmap={}
    try:
        pj=mb.get("/api/persist")
        items=pj.get("data") if isinstance(pj,dict) else pj
        if isinstance(items,list): pmap={it.get("card_id"):it for it in items}
    except Exception as ex:
        print("  /api/persist indispo:",repr(ex)[:90],flush=True)
    for mid,lbl in MODELS.items():
        it=pmap.get(mid)
        if it:
            print(f"  #{mid} {lbl}: state={it.get('state')} active={it.get('active')} "
                  f"refresh_end={it.get('refresh_end')} error={str(it.get('error'))[:60]}",flush=True)
        else:
            c=mb.get(f"/api/card/{mid}")
            print(f"  #{mid} {lbl}: PAS de PersistedInfo | champ card.persisted={c.get('persisted')}",flush=True)
    # 3) timing à froid
    print("\n--- timing (POST /api/card/{id}/query, sans filtre = pire cas) ---",flush=True)
    for cid,lbl in {**MODELS,**HEAVY}.items():
        t0=time.monotonic()
        try:
            r=mb.post(f"/api/card/{cid}/query","raw",json={},timeout=TMO)
            j=r.json() if hasattr(r,"json") else {}
            err=j.get("error") if isinstance(j,dict) else None
            n=len(j.get("data",{}).get("rows",[])) if isinstance(j,dict) and not err else "?"
            print(f"  #{cid:5d} {lbl:20s}: {time.monotonic()-t0:6.1f}s  rows={n}  {('ERR '+str(err)[:50]) if err else ''}",flush=True)
        except Exception as ex:
            print(f"  #{cid:5d} {lbl:20s}: {time.monotonic()-t0:6.1f}s  EXC {repr(ex)[:60]}",flush=True)
    print("\nDONE",flush=True)

if __name__=="__main__":
    main()
