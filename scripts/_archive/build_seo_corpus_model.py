#!/usr/bin/env python3
"""Modèle CORPUS-DRIVEN complet — généralise le V3 #48633.
Piloté par google_serp.serp_requests PAR EXCLUSION (informationnel/blog/brand/transactionnels bruts exclus)
-> tout nouveau corpus Nanga (couleurs, saisons, futurs) remonte automatiquement.
Jointures : SERP (position, dédup) + GSC (clics/impr, DÉSACCENTÉ des 2 côtés) + KP (volume, désaccenté).
Ajouts vs validation : DELTA_M1 / DELTA_CLICKS_M1 (LAG) + RANG_CLICS (rang par clics dans corpus×marché, pour filtre Top N).
Gate : valide le run complet (comptages par corpus) AVANT le PUT du modèle.
Usage : --apply pour créer/mettre à jour le modèle, sinon dry-run.
"""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
DB=144; COLL=13752; TMO=600
MODEL_NAME="SEO Corpus Monitoring — Manucurist (model)"

EXCLUDE=["Corpus informationnel FR","Corpus informationnel US",
         "Roadmap blog FR","Roadmap blog US","Manucurist - Brand keywords",
         "Corpus transactionnel FR","Corpus transactionnel US","Corpus transactionnel UK"]
def esc(s): return s.replace("'","''")
EXCL_IN=",".join("'"+esc(c)+"'" for c in EXCLUDE)
def UA(c): return f"TRANSLATE(LOWER({c}),'àâäéèêëîïôöùûüçœ','aaaeeeeiioouuuce')"

SQL=f"""
WITH corpus_kw AS (
  SELECT DISTINCT sr.corpus_name, LOWER(sr.keyword) AS keyword, {UA('sr.keyword')} AS keyword_ua,
         NULLIF(TRIM(sr.category),'') AS category, sr.zone, sr.language,
         CASE sr.zone WHEN 'France' THEN 'FR' WHEN 'United States' THEN 'US'
              WHEN 'United Kingdom' THEN 'UK' ELSE 'AUTRES' END AS marche
  FROM google_serp.serp_requests sr JOIN utils.clients c ON sr.client_id=c.id
  WHERE c.name='Manucurist' AND sr.corpus_name NOT IN ({EXCL_IN})
),
months AS (
  SELECT DISTINCT DATE_TRUNC('month',date) AS month_date FROM utils.calendar
  WHERE date >= DATEADD('month',-13,CURRENT_DATE) AND date <= CURRENT_DATE
),
gcd AS (
  SELECT sr.zone, LOWER(skm.keyword) AS keyword, skm.url, skm.request_date, sr.domain AS client_domain,
         CASE WHEN skm.type='featured_snippet' AND skm.rank_group=1 THEN 0 ELSE skm.rank_absolute END AS rank_absolute
  FROM utils.clients c
    JOIN google_serp.serp_requests sr ON sr.client_id=c.id
    JOIN google_serp.serp_history sh ON (sh.keyword=sr.keyword AND sh.language=sr.language AND sh.zone=sr.zone)
    JOIN google_serp.serp__keyword_metrics skm ON (skm.keyword=sh.keyword AND skm.language=sh.language AND skm.zone=sh.zone)
  WHERE c.name='Manucurist' AND sr.corpus_name NOT IN ({EXCL_IN})
    AND skm.request_date >= DATEADD('month',-13,CURRENT_DATE)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY sr.client_id, sr.corpus_name, sh.keyword, sh.language, sh.zone, skm.url, skm.request_date ORDER BY rank_absolute)=1
),
client_pos AS (
  SELECT zone, keyword, request_date, rank_absolute
  FROM gcd WHERE url ILIKE '%'||client_domain||'%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY zone, keyword, request_date ORDER BY rank_absolute)=1
),
pos AS (
  SELECT zone, keyword, DATE_TRUNC('month',request_date) AS month_date, AVG(rank_absolute) AS position
  FROM client_pos GROUP BY 1,2,3
),
vol AS (
  SELECT zone, keyword_ua, search_volume FROM (
    SELECT zone, {UA('keyword')} AS keyword_ua,
           COALESCE(adjusted_avg_searches, avg_monthly_searches) AS search_volume,
           ROW_NUMBER() OVER (PARTITION BY zone, {UA('keyword')} ORDER BY month DESC) rn
    FROM google_keyword_planner.kp__keyword_monthly_metrics
    WHERE zone IN (SELECT DISTINCT zone FROM corpus_kw)
      AND {UA('keyword')} IN (SELECT keyword_ua FROM corpus_kw)
  ) WHERE rn=1
),
gsc AS (
  SELECT {UA('keyword')} AS keyword_ua, DATE_TRUNC('month',date) AS month_date,
         SUM(clicks) AS clicks, SUM(impressions) AS impressions,
         SUM(position*impressions)/NULLIF(SUM(impressions),0) AS gsc_position
  FROM google_search_console.gsc__page_keyword_daily_metrics
  WHERE client_name='Manucurist' AND date >= DATEADD('month',-13,CURRENT_DATE)
    AND {UA('keyword')} IN (SELECT keyword_ua FROM corpus_kw)
  GROUP BY 1,2
),
assembled AS (
  SELECT m.month_date, ck.corpus_name, ck.marche, ck.category, ck.keyword,
         LEAST(COALESCE(pos.position, g.gsc_position, 100),100) AS position,
         pos.position AS position_serp, g.gsc_position AS position_gsc,
         v.search_volume, g.clicks, g.impressions
  FROM corpus_kw ck CROSS JOIN months m
    LEFT JOIN pos ON pos.zone=ck.zone AND pos.keyword=ck.keyword AND pos.month_date=m.month_date
    LEFT JOIN gsc g ON g.keyword_ua=ck.keyword_ua AND g.month_date=m.month_date
    LEFT JOIN vol v ON v.zone=ck.zone AND v.keyword_ua=ck.keyword_ua
),
kw_rank AS (
  SELECT corpus_name, marche, keyword,
         ROW_NUMBER() OVER (PARTITION BY corpus_name, marche ORDER BY SUM(COALESCE(clicks,0)) DESC, keyword) AS rang_clics
  FROM assembled GROUP BY 1,2,3
)
SELECT a.month_date, a.corpus_name, a.marche, a.category, a.keyword,
       a.position, a.position_serp, a.position_gsc, a.search_volume, a.clicks, a.impressions,
       LAG(a.position) OVER (PARTITION BY a.corpus_name, a.marche, a.keyword ORDER BY a.month_date) - a.position AS delta_m1,
       a.clicks - LAG(a.clicks) OVER (PARTITION BY a.corpus_name, a.marche, a.keyword ORDER BY a.month_date) AS delta_clicks_m1,
       r.rang_clics
FROM assembled a JOIN kw_rank r
  ON r.corpus_name=a.corpus_name AND r.marche=a.marche AND r.keyword=a.keyword
ORDER BY a.corpus_name, a.marche, r.rang_clics, a.keyword, a.month_date DESC
"""

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception as ex: print("retry",repr(ex)[:80],flush=True); time.sleep(8)
    sys.exit("conn failed")

def upsert_model(mb,payload):
    for it in mb.get(f"/api/collection/{COLL}/items?limit=2000").get("data",[]):
        if it.get("model")=="dataset" and it.get("name")==MODEL_NAME:
            mb.put(f"/api/card/{it['id']}","raw",json=payload,timeout=TMO); return it["id"],"maj"
    b=mb.post("/api/card","raw",json=payload,timeout=TMO).json(); return b.get("id"),"créé"

def main():
    apply="--apply" in sys.argv
    mb=connect(); print("connected | mode:","APPLY" if apply else "dry-run",flush=True)
    t0=time.monotonic()
    # validation par agrégat côté Snowflake (l'API /api/dataset tronque à 2000 lignes)
    VSQL=f"""SELECT corpus_name, marche, COUNT(*) AS n_rows, COUNT(DISTINCT keyword) AS n_kw,
             SUM(COALESCE(clicks,0)) AS clicks_13m, COUNT(DISTINCT category) AS n_cat,
             SUM(CASE WHEN rang_clics<=25 THEN COALESCE(clicks,0) ELSE 0 END) AS clicks_top25
             FROM ({SQL}) GROUP BY 1,2 ORDER BY 1,2"""
    r=mb.post("/api/dataset","raw",json={"database":DB,"type":"native","native":{"query":VSQL}},timeout=TMO).json()
    if r.get("error"): print("ÉCHEC SQL:",str(r["error"])[:800],flush=True); sys.exit(1)
    cols=[c["name"] for c in r["data"]["cols"]]; rows=r["data"]["rows"]; ci={n:i for i,n in enumerate(cols)}
    print(f"run: {time.monotonic()-t0:.0f}s | {len(rows)} groupes corpus×marché",flush=True)
    print("\ncorpus × marché | lignes | kw | clics 13m (top25) | catégories:",flush=True)
    tot_rows=0
    for row in rows:
        tot_rows+=row[ci["N_ROWS"]]
        print(f"  {str(row[ci['CORPUS_NAME']])[:46]:46} | {row[ci['MARCHE']]:6} | {row[ci['N_ROWS']]:5} | "
              f"{row[ci['N_KW']]:4} kw | {int(row[ci['CLICKS_13M']]):7} ({int(row[ci['CLICKS_TOP25']]):6}) | {row[ci['N_CAT']]} cat",flush=True)
    names=" || ".join(str(row[ci["CORPUS_NAME"]]).lower() for row in rows)
    print(f"\ntotal lignes modèle: {tot_rows} | groupes: {len(rows)}",flush=True)
    if tot_rows<5000 or len(rows)<5 or "couleurs" not in names or "saisons" not in names or "stratégiques" not in names:
        print("⚠️ gate ÉCHOUÉE (volumétrie ou corpus manquant), PAS de PUT.",flush=True); sys.exit(1)
    if not apply:
        print("\nDONE dry-run (relancer avec --apply pour créer le modèle)",flush=True); return
    DESC=("Suivi corpus-driven Nanga. Tous les corpus pertinents (stratégique, couleurs, saisons et les prochains créés dans Nanga) "
          "par marché et par mois. Position SERP avec repli GSC (100 = non classé), volume Keyword Planner, clics et impressions GSC "
          "avec rapprochement insensible aux accents. RANG_CLICS classe les mots-clés par clics dans chaque corpus et marché (sert au filtre Top N). "
          "Corpus exclus : informationnel, blog, brand, transactionnels bruts.")
    MID,how=upsert_model(mb,{"name":MODEL_NAME,"type":"model","collection_id":COLL,
        "dataset_query":{"database":DB,"type":"native","native":{"query":SQL}},
        "display":"table","visualization_settings":{},"description":DESC})
    print(f"\nmodèle {how} #{MID}",flush=True)
    rm=mb.post("/api/dataset","raw",json={"database":DB,"type":"native","native":{"query":f"SELECT * FROM ({SQL}) LIMIT 40"}},timeout=TMO).json()
    if not rm.get("error"):
        mb.put(f"/api/card/{MID}","raw",json={"result_metadata":rm["data"]["cols"]},timeout=120)
        print("result_metadata posé",flush=True)
    print(f"\n>>> MODÈLE CORPUS #{MID}",flush=True)

if __name__=="__main__":
    main()
