#!/usr/bin/env python3
"""Sujet ACCENTS : comment GSC stocke les requêtes accentuées vs corpus SERP désaccentué,
et est-ce qu'un matching accent-insensible (TRANSLATE unaccent) récupère bien les clics ?"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
DB=144; TMO=420
UNACC="TRANSLATE(LOWER({c}),'àâäéèêëîïôöùûüçœ','aaaeeeeiioouuuce')"  # œ->e approx

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
    if r.get("error"): print("ERR:",str(r["error"])[:400],flush=True); return
    cols=[c["name"] for c in r["data"]["cols"]]
    print(" | ".join(cols),flush=True)
    for row in r["data"]["rows"]: print("  "+" | ".join(str(x) for x in row),flush=True)

def main():
    mb=connect(); print("connected",flush=True)
    ua_g=UNACC.format(c="g.keyword")

    run(mb,"""
SELECT keyword, SUM(clicks) clicks, SUM(impressions) impr
FROM google_search_console.gsc__page_keyword_daily_metrics
WHERE client_name ILIKE '%manucurist%' AND date >= DATEADD('month',-6,CURRENT_DATE)
  AND REGEXP_LIKE(keyword, '.*[éèêàâîïôùûçäöü].*')
GROUP BY keyword ORDER BY clicks DESC LIMIT 25
""","1) GSC stocke-t-il les accents ? (top requêtes accentuées Manucurist)")

    run(mb,f"""
WITH targets AS (
  SELECT * FROM (VALUES
    ('vernis dore'),('vernis argente'),('couleur ongle ete'),('couleur manucure ete'),
    ('manucure francaise'),('ongles printemps'),('vernis rose poudre')
  ) t(kw_corpus_desaccentue)
)
SELECT t.kw_corpus_desaccentue, g.keyword AS gsc_reel,
       SUM(g.clicks) clicks, SUM(g.impressions) impr
FROM targets t
JOIN google_search_console.gsc__page_keyword_daily_metrics g
  ON {ua_g} = t.kw_corpus_desaccentue
 AND g.client_name ILIKE '%manucurist%' AND g.date >= DATEADD('month',-6,CURRENT_DATE)
GROUP BY 1,2 ORDER BY 1, clicks DESC
""","2) FIX : corpus désaccentué -> clics GSC récupérés via unaccent (montre la forme réelle GSC)")

    run(mb,"""
SELECT sr.keyword
FROM google_serp.serp_requests sr JOIN utils.clients c ON sr.client_id=c.id
WHERE c.name ILIKE '%manucurist%' AND REGEXP_LIKE(sr.keyword,'.*[éèêàâîïôùûç].*')
GROUP BY 1 LIMIT 15
""","3) google_serp stocke-t-il les accents ? (kw corpus existants accentués)")

    run(mb,"""
SELECT DISTINCT sr.corpus_name
FROM google_serp.serp_requests sr JOIN utils.clients c ON sr.client_id=c.id
WHERE c.name ILIKE '%manucurist%'
  AND (LOWER(sr.corpus_name) LIKE '%couleur%' OR LOWER(sr.corpus_name) LIKE '%season%'
       OR LOWER(sr.corpus_name) LIKE '%saison%' OR LOWER(sr.corpus_name) LIKE '%color%')
""","4) corpus Couleurs/Saisons déjà présents dans google_serp ?")
    print("\nDONE",flush=True)

if __name__=="__main__":
    main()
