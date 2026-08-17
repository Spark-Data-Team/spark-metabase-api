#!/usr/bin/env python3
"""Découverte V3 : template saisonnalité #13489, CTR/potentiel, URL positionnée, géo-clics."""
from __future__ import annotations
import json, sys, time
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
        except Exception: time.sleep(8)
    sys.exit("conn failed")

def main():
    mb=connect(); print("connected")
    def run(label,sql):
        r=mb.post("/api/dataset","raw",json={"database":144,"type":"native","native":{"query":sql}},timeout=240)
        j=r.json(); print(f"\n##### {label}")
        if j.get("error"): print("  ERR:",str(j["error"])[:250]); return
        d=j["data"]; print("  ",[c["name"] for c in d["cols"]])
        for x in d["rows"]: print("   ",x)

    # A. template saisonnalité #13489
    print("##### A. Carte/dashboard #13489 (saisonnalité)")
    try:
        c=mb.get("/api/card/13489")
        if isinstance(c,dict) and c.get("id"):
            print("  CARTE:", c.get("name"),"| type:",c.get("type"),"| display:",c.get("display"),"| coll:",(c.get("collection") or {}).get("name"))
            lq=c.get("legacy_query"); lq=json.loads(lq) if isinstance(lq,str) else lq
            q=(lq or {}).get("native",{}).get("query","")
            print("  SQL len:",len(q)); print("  SQL head:\n",("\n".join(q.splitlines()[:25]) if q else "(vide via legacy)"))
            tt=(lq or {}).get("native",{}).get("template-tags") or {}
            print("  tags:", list(tt.keys()))
        else:
            print("  pas une carte, essai dashboard…")
    except Exception as ex: print("  card err:",ex)
    try:
        d=mb.get("/api/dashboard/13489")
        if isinstance(d,dict) and d.get("id"):
            print("  DASHBOARD #13489:", d.get("name"),"| tuiles:",len(d.get("dashcards",[])))
    except Exception as ex: pass

    # B. CTR scenarios pour potentiel de trafic
    run("B. serp_ctr_scenarios (Default) — position→ctr","""
SELECT position, ctr_low, ctr_medium, ctr_high
FROM metabase_filters.serp_ctr_scenarios WHERE name='Default' AND position IN (1,2,3,5,8,12,24,100)
ORDER BY position""")

    # C. URL positionnée (client) pour 3 kw US
    run("C. URL positionnée client (SERP) — sample US","""
WITH gcd AS (
  SELECT LOWER(km.keyword) keyword, km.url, km.request_date, sr.domain client_domain,
    CASE WHEN km.type='featured_snippet' AND km.rank_group=1 THEN 0 ELSE km.rank_absolute END ra
  FROM utils.clients c JOIN google_serp.serp_requests sr ON sr.client_id=c.id
   JOIN google_serp.serp_history sh ON (sh.keyword=sr.keyword AND sh.language=sr.language AND sh.zone=sr.zone)
   JOIN google_serp.serp__keyword_metrics km ON (km.keyword=sh.keyword AND km.language=sh.language AND km.zone=sh.zone)
  WHERE c.name='Manucurist' AND sr.zone='United States'
    AND LOWER(sr.keyword) IN ('gel polish kit','cuticle oil','nail polish')
    AND km.request_date>=DATEADD('month',-2,CURRENT_DATE)
)
SELECT keyword, url, ra FROM gcd WHERE url ILIKE '%'||client_domain||'%'
QUALIFY ROW_NUMBER() OVER (PARTITION BY keyword ORDER BY request_date DESC, ra) = 1""")

    # D. géo-split des clics par mot-clé (section de site)
    run("D. clics par mot-clé × marché (page_keyword, 30j)","""
SELECT LOWER(keyword) kw,
  CASE WHEN page ILIKE 'https://us.manucurist.com%' THEN 'US'
       WHEN page ILIKE 'https://uk.manucurist.com%' THEN 'UK'
       WHEN REGEXP_LIKE(page,'https://www[.]manucurist[.]com/(en|es|it|de|nl|el|pt)(/.*)?') THEN 'AUTRES'
       WHEN page ILIKE 'https://www.manucurist.com%' THEN 'FR' ELSE 'AUTRES' END marche,
  SUM(clicks) clics
FROM google_search_console.gsc__page_keyword_daily_metrics
WHERE client_name='Manucurist' AND LOWER(keyword) IN ('nail polish','non toxic nail polish','french manucure')
  AND date>=DATEADD('day',-30,CURRENT_DATE)
GROUP BY 1,2 ORDER BY 1,3 DESC""")

if __name__=="__main__":
    main()
