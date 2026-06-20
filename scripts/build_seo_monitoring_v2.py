#!/usr/bin/env python3
"""Modèle mots-clés V2 — SEO Keyword Monitoring | Manucurist (gsheet V2).

14 kw US + 18 kw FR × mois (13) × :
- position : SERP DataForSEO par zone (FR→France, US→United States), repli GSC
  (position pondérée impressions, depuis page_keyword) ; affichage convention
  gsheet : 100 = non classé (LEAST/COALESCE)
- volume   : kp par zone, dernier connu
- clics    : GSC page_keyword, attribués au MARCHÉ DU SITE via l'URL
  (www=FR, us.=US, uk.=UK, locales www/{en,es,...}=AUTRES)
- Δ vs M-1 et Δ 6 mois (LAG sur position affichée ; + = positions gagnées)

Met à jour le modèle #48633 EN PLACE. Valide un snapshot avant le PUT.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; MODEL_ID=48633; HTTP_TIMEOUT=480

US=['gel polish kit','gel polish','non toxic gel polish','gel nail polish','nail polish kit',
 'non toxic nail polish','vegan nail polish','natural nail polish','nail polish','nail care',
 'cuticle oil','nail strengthener','base coat','top coat','nail treatment']
FR=['vernis semi permanent','french manucure','kit vernis semi permanent','kit manucure',
 'vernis a ongle','top coat','lampe uv ongles','base coat','soin des ongles',
 'kit manucure semi permanent','dissolvant vernis semi permanent','vernis amer',
 'vernis durcisseur','kit semi permanent','dissolvant semi permanent','couleur vernis',
 'huile cuticule','vernis naturel']
def esc(k): return k.replace("'","''")
VALUES=",\n    ".join([f"('{esc(k)}','US')" for k in US]+[f"('{esc(k)}','FR')" for k in FR])
ALL_IN=",".join(f"'{esc(k)}'" for k in US+FR)

MODEL_SQL=f"""
WITH kw_map AS (
  SELECT t.keyword, t.marche,
         CASE t.marche WHEN 'FR' THEN 'France' WHEN 'US' THEN 'United States' END AS zone
  FROM (VALUES
    {VALUES}
  ) AS t(keyword, marche)
),
months AS (
  SELECT DISTINCT DATE_TRUNC('month', date) AS month_date
  FROM utils.calendar
  WHERE date >= DATEADD('month', -13, CURRENT_DATE) AND date <= CURRENT_DATE
),
gcd AS (
  SELECT serp_requests.zone AS zone,
         LOWER(serp__keyword_metrics.keyword) AS keyword,
         serp__keyword_metrics.url, serp__keyword_metrics.request_date,
         serp_requests.domain AS client_domain,
         CASE WHEN serp__keyword_metrics.type='featured_snippet' AND serp__keyword_metrics.rank_group=1 THEN 0
              ELSE serp__keyword_metrics.rank_absolute END AS rank_absolute
  FROM utils.clients
    JOIN google_serp.serp_requests ON google_serp.serp_requests.client_id = utils.clients.id
    JOIN google_serp.serp_history ON (serp_history.keyword=serp_requests.keyword AND serp_history.language=serp_requests.language AND serp_history.zone=serp_requests.zone)
    JOIN google_serp.serp__keyword_metrics ON (serp__keyword_metrics.keyword=serp_history.keyword AND serp__keyword_metrics.language=serp_history.language AND serp__keyword_metrics.zone=serp_history.zone)
  WHERE utils.clients.name='Manucurist'
    AND serp_requests.zone IN ('France','United States')
    AND LOWER(serp_requests.keyword) IN ({ALL_IN})
    AND serp__keyword_metrics.request_date >= DATEADD('month', -13, CURRENT_DATE)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY serp_requests.client_id, serp_requests.corpus_name, serp_history.keyword, serp_history.language, serp_history.zone, serp__keyword_metrics.url, serp__keyword_metrics.request_date ORDER BY rank_absolute) = 1
),
client_pos AS (
  SELECT zone, keyword, request_date, rank_absolute
  FROM gcd WHERE url ILIKE '%' || client_domain || '%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY zone, keyword, request_date ORDER BY rank_absolute) = 1
),
pos AS (
  SELECT zone, keyword, DATE_TRUNC('month', request_date) AS month_date, AVG(rank_absolute) AS position
  FROM client_pos GROUP BY 1,2,3
),
vol AS (
  SELECT zone, keyword, search_volume FROM (
    SELECT zone, LOWER(keyword) AS keyword,
           COALESCE(adjusted_avg_searches, avg_monthly_searches) AS search_volume,
           ROW_NUMBER() OVER (PARTITION BY zone, LOWER(keyword) ORDER BY month DESC) AS rn
    FROM google_keyword_planner.kp__keyword_monthly_metrics
    WHERE zone IN ('France','United States') AND LOWER(keyword) IN ({ALL_IN})
  ) WHERE rn=1
),
gsc AS (
  SELECT LOWER(keyword) AS keyword,
    CASE WHEN page ILIKE 'https://us.manucurist.com%' THEN 'US'
         WHEN page ILIKE 'https://uk.manucurist.com%' THEN 'UK'
         WHEN REGEXP_LIKE(page, 'https://www[.]manucurist[.]com/(en|es|it|de|nl|el|pt)(/.*)?') THEN 'AUTRES'
         WHEN page ILIKE 'https://www.manucurist.com%' THEN 'FR'
         ELSE 'AUTRES' END AS marche,
    DATE_TRUNC('month', date) AS month_date,
    SUM(clicks) AS clicks, SUM(impressions) AS impressions,
    SUM(position*impressions)/NULLIF(SUM(impressions),0) AS gsc_position
  FROM google_search_console.gsc__page_keyword_daily_metrics
  WHERE client_name='Manucurist' AND LOWER(keyword) IN ({ALL_IN})
    AND date >= DATEADD('month', -13, CURRENT_DATE)
  GROUP BY 1,2,3
),
assembled AS (
  SELECT
    m.month_date, k.marche, k.keyword,
    LEAST(COALESCE(pos.position, g.gsc_position, 100), 100) AS position,
    pos.position      AS position_serp,
    g.gsc_position    AS position_gsc,
    vol.search_volume AS search_volume,
    g.clicks          AS clicks,
    g.impressions     AS impressions
  FROM kw_map k
    CROSS JOIN months m
    LEFT JOIN pos ON pos.zone=k.zone AND pos.keyword=k.keyword AND pos.month_date=m.month_date
    LEFT JOIN gsc g ON g.marche=k.marche AND g.keyword=k.keyword AND g.month_date=m.month_date
    LEFT JOIN vol ON vol.zone=k.zone AND vol.keyword=k.keyword
)
SELECT a.*,
  LAG(position)   OVER (PARTITION BY marche, keyword ORDER BY month_date) - position AS delta_m1,
  LAG(position,6) OVER (PARTITION BY marche, keyword ORDER BY month_date) - position AS delta_6m
FROM assembled a
ORDER BY marche, keyword, month_date DESC
"""

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current",timeout=60); return mb
        except Exception: time.sleep(8)
    sys.exit("conn failed")

def run(mb,sql):
    r=mb.post("/api/dataset","raw",json={"database":DB,"type":"native","native":{"query":sql}},timeout=HTTP_TIMEOUT)
    j=r.json()
    if j.get("error"): return None,str(j["error"])
    d=j["data"]; return {"cols":d["cols"],"rows":d["rows"]},None

def main():
    mb=connect(); print("connected")
    res,err=run(mb, MODEL_SQL)
    if err: print("ÉCHEC SQL:",err[:600]); sys.exit(1)
    cols=[c["name"] for c in res["cols"]]; rows=res["rows"]
    ci={n:i for i,n in enumerate(cols)}
    print(f"modèle: {len(rows)} lignes (attendu 33 kw × 14 mois = 462), cols={cols}")
    months=sorted({r[ci["MONTH_DATE"]] for r in rows})
    # snapshot mois précédent (données complètes)
    prev=months[-2] if len(months)>=2 else months[-1]
    snap=[r for r in rows if r[ci["MONTH_DATE"]]==prev]
    print(f"\nSNAPSHOT {str(prev)[:7]} :")
    print("  M  MOT-CLÉ                          POS  ΔM-1  Δ6M    VOL   CLICS")
    ok_pos=ok_vol=ok_clk=0
    for r in sorted(snap, key=lambda r:(r[ci["MARCHE"]], r[ci["POSITION"]] if r[ci["POSITION"]] is not None else 999)):
        p=r[ci["POSITION"]]; d1=r[ci["DELTA_M1"]]; d6=r[ci["DELTA_6M"]]
        v=r[ci["SEARCH_VOLUME"]]; cl=r[ci["CLICKS"]]
        if p is not None and p<100: ok_pos+=1
        if v: ok_vol+=1
        if cl is not None: ok_clk+=1
        fmt=lambda x,w: (('%+d'%x) if isinstance(x,(int,float)) and x==x else '.').rjust(w) if x is not None else '.'.rjust(w)
        print(f"  {r[ci['MARCHE']]:3} {r[ci['KEYWORD']][:32]:32} {('%.0f'%p if p is not None else '.'):>4} {fmt(d1,5)} {fmt(d6,5)} {('%.0f'%v if v else '.'):>6} {('%.0f'%cl if cl is not None else '.'):>6}")
    print(f"\n  {len(snap)} lignes | positions<100: {ok_pos} | volumes: {ok_vol} | clics non-null: {ok_clk}")
    if len(snap)!=33 or ok_vol<31:
        print("  ⚠️ incomplet — PAS de PUT."); sys.exit(1)

    DESC=("V2 (gsheet Thibaut 2026-06 ; base & top coat US scindé en base coat + top coat sur demande Thibaut). "
          "15 kw US + 18 kw FR × mois × position (SERP zone, repli GSC ; "
          "100 = non classé) / volume (kp zone, dernier connu) / clics GSC par marché du site (URL : www=FR, us.=US, uk.=UK) "
          "+ Δ vs M-1 et Δ 6 mois (+ = positions gagnées). NB: pays du chercheur non ingéré (country='other') → marché = section du site.")
    r=mb.put(f"/api/card/{MODEL_ID}","raw",json={
        "name":"SEO Keyword Monitoring — Manucurist (model)",
        "dataset_query":{"database":DB,"type":"native","native":{"query":MODEL_SQL}},
        "description":DESC},timeout=HTTP_TIMEOUT)
    print("PUT modèle:",getattr(r,"status_code","?"))
    rm,_=run(mb, f"SELECT * FROM ({MODEL_SQL}) LIMIT 40")
    if rm: print("PUT metadata:",getattr(mb.put(f"/api/card/{MODEL_ID}","raw",json={"result_metadata":rm["cols"]},timeout=120),"status_code","?"))
    print(f"\n>>> MODÈLE V2 #{MODEL_ID} mis à jour")

if __name__=="__main__":
    main()
