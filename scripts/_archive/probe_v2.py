#!/usr/bin/env python3
"""Sondage V2 : marché GSC, gabarits de pages, brand keywords, kw FR trackés."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

FR_KW=['vernis semi permanent','french manucure','kit vernis semi permanent','kit manucure',
 'vernis a ongle','top coat','lampe uv ongles','base coat','soin des ongles',
 'kit manucure semi permanent','dissolvant vernis semi permanent','vernis amer',
 'vernis durcisseur','kit semi permanent','dissolvant semi permanent','couleur vernis',
 'huile cuticule','vernis naturel']
US_KW=['gel polish kit','gel polish','non toxic gel polish','gel nail polish','nail polish kit',
 'non toxic nail polish','vegan nail polish','natural nail polish','nail polish','nail care',
 'cuticle oil','nail strengthener','base & top coat','nail treatment']
FR_IN=",".join("'%s'"%k for k in FR_KW)
US_IN=",".join("'%s'"%k for k in US_KW)

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
        j=r.json()
        print(f"\n##### {label}")
        if j.get("error"): print("  ERR:",str(j["error"])[:250]); return [],[]
        d=j["data"]; cols=[c["name"] for c in d["cols"]]
        print("  ",cols)
        for x in d["rows"]: print("   ",x)
        return cols, d["rows"]

    run("A. Comptes GSC Manucurist","""
SELECT account_id, account_name FROM google_search_console.gsc__accounts
WHERE client_name='Manucurist'""")

    run("B. Pays dispo (country_device_keyword), Manucurist, 90j","""
SELECT country, SUM(clicks) clicks, COUNT(DISTINCT keyword) kws
FROM google_search_console.gsc__country_device_keyword_daily_metrics
WHERE client_name='Manucurist' AND date>=DATEADD('day',-90,CURRENT_DATE)
GROUP BY 1 ORDER BY 2 DESC LIMIT 12""")

    run("C. Colonnes des tables pages + brand","""
SELECT table_name, LISTAGG(column_name,', ') WITHIN GROUP (ORDER BY ordinal_position) cols
FROM information_schema.columns
WHERE table_schema='GOOGLE_SEARCH_CONSOLE'
  AND table_name IN ('GSC__PAGE_DAILY_METRICS','GSC__PAGE_KEYWORD_DAILY_METRICS','GSC__BRAND_KEYWORDS','GSC__URL_GROUPS')
GROUP BY 1""")

    run("D. Top URLs pages Manucurist (patterns gabarit/locale), 30j","""
SELECT page, SUM(clicks) clicks
FROM google_search_console.gsc__page_daily_metrics
WHERE client_name='Manucurist' AND date>=DATEADD('day',-30,CURRENT_DATE)
GROUP BY 1 ORDER BY 2 DESC LIMIT 30""")

    run("E. Brand keywords Manucurist (sample)","""
SELECT * FROM google_search_console.gsc__brand_keywords
WHERE client_name ILIKE '%manucurist%' LIMIT 15""")

    run("F. KW FR du gsheet trackés en SERP zone France ?",f"""
SELECT LOWER(sr.keyword) kw, COUNT(DISTINCT sr.corpus_name) corpus
FROM google_serp.serp_requests sr JOIN utils.clients c ON c.id=sr.client_id
WHERE c.name='Manucurist' AND sr.zone='France' AND LOWER(sr.keyword) IN ({FR_IN})
GROUP BY 1 ORDER BY 1""")

    run("G. Volumes kp zone France pour ces kw",f"""
SELECT LOWER(keyword) kw, MAX(month) last_month,
       MAX(COALESCE(adjusted_avg_searches,avg_monthly_searches)) vol
FROM google_keyword_planner.kp__keyword_monthly_metrics
WHERE zone='France' AND LOWER(keyword) IN ({FR_IN}) GROUP BY 1 ORDER BY 1""")

    run("H. Clics par pays pour kw stratégiques (country_device), mai",f"""
SELECT country, COUNT(DISTINCT LOWER(keyword)) kws, SUM(clicks) clicks
FROM google_search_console.gsc__country_device_keyword_daily_metrics
WHERE client_name='Manucurist' AND date>=DATEADD('day',-30,CURRENT_DATE)
  AND (LOWER(keyword) IN ({US_IN}) OR LOWER(keyword) IN ({FR_IN}))
GROUP BY 1 ORDER BY 3 DESC LIMIT 10""")

if __name__=="__main__":
    main()
