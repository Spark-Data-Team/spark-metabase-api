#!/usr/bin/env python3
"""Sonde la structure des CORPUS Manucurist dans google_serp.serp_requests :
- liste corpus_name × language × zone × n_keywords
- détecte si un corpus_name s'étale sur PLUSIEURS marchés (zone/language) -> réponse à 'filtre corpus vs marché'.
Lecture seule."""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
DB=144; TMO=400

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex: print("retry",repr(ex)[:80],flush=True); time.sleep(8)
    sys.exit("conn failed")

def run(mb,sql,label):
    print(f"\n=== {label} ===",flush=True)
    r=mb.post("/api/dataset","raw",json={"database":DB,"type":"native","native":{"query":sql}},timeout=TMO).json()
    if r.get("error"): print("ERR:",str(r["error"])[:400],flush=True); return None
    cols=[c["name"] for c in r["data"]["cols"]]; rows=r["data"]["rows"]
    print(" | ".join(cols),flush=True)
    for row in rows: print("  "+" | ".join(str(x) for x in row),flush=True)
    return rows

def main():
    mb=connect(); print("connected",flush=True)
    # 0) résoudre le client
    run(mb,"SELECT id, name FROM utils.clients WHERE name ILIKE '%manucurist%'","client Manucurist (utils.clients)")
    # 1) corpus landscape
    run(mb,"""
SELECT sr.corpus_name, sr.language, sr.zone, COUNT(DISTINCT sr.keyword) AS n_kw
FROM google_serp.serp_requests sr
JOIN utils.clients c ON sr.client_id = c.id
WHERE c.name ILIKE '%manucurist%'
GROUP BY 1,2,3
ORDER BY 1,3
""","corpus_name × language × zone × n_kw")
    # 2) un corpus s'étale-t-il sur plusieurs marchés ?
    run(mb,"""
SELECT sr.corpus_name,
       COUNT(DISTINCT sr.zone) AS n_zones,
       COUNT(DISTINCT sr.language) AS n_langs,
       LISTAGG(DISTINCT sr.zone, ', ') AS zones
FROM google_serp.serp_requests sr
JOIN utils.clients c ON sr.client_id = c.id
WHERE c.name ILIKE '%manucurist%'
GROUP BY 1
ORDER BY n_zones DESC, 1
""","multi-marché par corpus (n_zones>1 = corpus multi-marché)")
    print("\nDONE",flush=True)

if __name__=="__main__":
    main()
