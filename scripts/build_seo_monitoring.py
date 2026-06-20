#!/usr/bin/env python3
"""Modèle consolidé V1 — SEO Keyword Monitoring | Manucurist.

15 mots-clés curatés (gsheet) × mois × [Position (SERP), Volume (KP), Clics+Impr (GSC)],
+ gamme + catégorie. Zone US (mots-clés EN). 13 mois. Mapping kw→gamme→catégorie en dur (V1).
Valide un snapshot avant de créer le modèle.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; SERP_COLLECTION=4809; HTTP_TIMEOUT=300; ZONE="United States"

# 15 mots-clés curatés (du gsheet) : (keyword_lower, gamme, categorie)
KW=[("gel polish kit","Gel Polish","Transactionnel"),
    ("gel polish","Gel Polish","Générique"),
    ("non toxic gel polish","Gel Polish","Clean / Engagement"),
    ("gel nail polish","Gel Polish","Générique"),
    ("led gel polish","Gel Polish","Produit"),
    ("nail polish kit","Nail Polish","Transactionnel"),
    ("non toxic nail polish","Nail Polish","Clean / Engagement"),
    ("vegan nail polish","Nail Polish","Clean / Engagement"),
    ("natural nail polish","Nail Polish","Clean / Engagement"),
    ("nail polish","Nail Polish","Générique"),
    ("nail care","Nailcare","Générique"),
    ("cuticle oil","Nailcare","Produit"),
    ("nail strengthener","Nailcare","Produit"),
    ("base & top coat","Nailcare","Produit"),
    ("nail treatment","Nailcare","Informationnel")]

def vlist():
    return ",\n    ".join("('%s','%s','%s')"%(k.replace("'","''"),g,c) for k,g,c in KW)
INLIST=",".join("'%s'"%k for k,_,_ in KW)

MODEL_SQL=f"""
WITH kw_map AS (
  SELECT * FROM (VALUES
    {vlist()}
  ) AS t(keyword, gamme, categorie)
),
months AS (
  SELECT DISTINCT DATE_TRUNC('month', date) AS month_date
  FROM utils.calendar
  WHERE date >= DATEADD('month', -13, CURRENT_DATE) AND date <= CURRENT_DATE
),
gcd AS (
  SELECT serp_requests.client_id, serp_requests.corpus_name,
         LOWER(serp__keyword_metrics.keyword) AS keyword,
         serp__keyword_metrics.url, serp__keyword_metrics.request_date,
         serp_requests.domain AS client_domain,
         CASE WHEN serp__keyword_metrics.type='featured_snippet' AND serp__keyword_metrics.rank_group=1 THEN 0
              ELSE serp__keyword_metrics.rank_absolute END AS rank_absolute
  FROM utils.clients
    JOIN google_serp.serp_requests ON google_serp.serp_requests.client_id = utils.clients.id
    JOIN google_serp.serp_history ON (serp_history.keyword=serp_requests.keyword AND serp_history.language=serp_requests.language AND serp_history.zone=serp_requests.zone)
    JOIN google_serp.serp__keyword_metrics ON (serp__keyword_metrics.keyword=serp_history.keyword AND serp__keyword_metrics.language=serp_history.language AND serp__keyword_metrics.zone=serp_history.zone)
  WHERE utils.clients.name='Manucurist' AND serp_requests.zone='{ZONE}'
    AND LOWER(serp_requests.keyword) IN ({INLIST})
    AND serp__keyword_metrics.request_date >= DATEADD('month', -13, CURRENT_DATE)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY serp_requests.client_id, serp_requests.corpus_name, serp_history.keyword, serp_history.language, serp_history.zone, serp__keyword_metrics.url, serp__keyword_metrics.request_date ORDER BY rank_absolute) = 1
),
client_pos AS (
  SELECT keyword, request_date, rank_absolute
  FROM gcd WHERE url ILIKE '%' || client_domain || '%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY keyword, request_date ORDER BY rank_absolute) = 1
),
pos AS (
  SELECT keyword, DATE_TRUNC('month', request_date) AS month_date, AVG(rank_absolute) AS position
  FROM client_pos GROUP BY 1,2
),
gsc_pos AS (
  SELECT LOWER(keyword) AS keyword, DATE_TRUNC('month', date) AS month_date,
         SUM(position * impressions) / NULLIF(SUM(impressions), 0) AS gsc_position
  FROM google_search_console.gsc__site_keyword_daily_metrics
  WHERE client_name='Manucurist' AND LOWER(keyword) IN ({INLIST})
  GROUP BY 1,2
),
vol AS (  -- dernier volume connu par mot-clé (kp lague ~2 mois)
  SELECT keyword, search_volume FROM (
    SELECT LOWER(keyword) AS keyword,
           COALESCE(adjusted_avg_searches, avg_monthly_searches) AS search_volume,
           ROW_NUMBER() OVER (PARTITION BY LOWER(keyword) ORDER BY month DESC) AS rn
    FROM google_keyword_planner.kp__keyword_monthly_metrics
    WHERE zone='{ZONE}' AND LOWER(keyword) IN ({INLIST})
  ) WHERE rn=1
),
clk AS (
  SELECT LOWER(keyword) AS keyword, DATE_TRUNC('month', date) AS month_date,
         SUM(clicks) AS clicks, SUM(impressions) AS impressions
  FROM google_search_console.gsc__site_keyword_daily_metrics
  WHERE client_name='Manucurist' AND LOWER(keyword) IN ({INLIST})
  GROUP BY 1,2
)
SELECT
  m.month_date,
  k.gamme, k.categorie, k.keyword,
  COALESCE(pos.position, gsc_pos.gsc_position) AS position,
  pos.position        AS position_serp,
  gsc_pos.gsc_position AS position_gsc,
  vol.search_volume   AS search_volume,
  clk.clicks          AS clicks,
  clk.impressions     AS impressions
FROM kw_map k
  CROSS JOIN months m
  LEFT JOIN pos ON pos.keyword=k.keyword AND pos.month_date=m.month_date
  LEFT JOIN gsc_pos ON gsc_pos.keyword=k.keyword AND gsc_pos.month_date=m.month_date
  LEFT JOIN vol ON vol.keyword=k.keyword
  LEFT JOIN clk ON clk.keyword=k.keyword AND clk.month_date=m.month_date
ORDER BY k.gamme, k.keyword, m.month_date DESC
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
    if err: print("ÉCHEC SQL modèle:",err[:500]); sys.exit(1)
    cols=[c["name"] for c in res["cols"]]; rows=res["rows"]
    print(f"modèle: {len(rows)} lignes, cols={cols}")
    # snapshot dernier mois
    ci={n:i for i,n in enumerate(cols)}
    months=sorted({r[ci["MONTH_DATE"]] for r in rows}, reverse=True)
    last=months[0] if months else None
    print(f"\nSNAPSHOT {str(last)[:7]} (15 kw) :")
    print("  GAMME        CATÉGORIE          MOT-CLÉ                POS   VOL    CLICS")
    snap=[r for r in rows if r[ci["MONTH_DATE"]]==last]
    for r in sorted(snap, key=lambda r:(r[ci["GAMME"]], r[ci["KEYWORD"]])):
        pos=r[ci["POSITION"]]; vol=r[ci["SEARCH_VOLUME"]]; clk=r[ci["CLICKS"]]
        print(f"  {str(r[ci['GAMME']]):12} {str(r[ci['CATEGORIE']]):18} {r[ci['KEYWORD']][:22]:22} "
              f"{('%.0f'%pos if pos is not None else '.'):>4} {('%.0f'%vol if vol is not None else '.'):>6} {('%.0f'%clk if clk is not None else '.'):>6}")
    nkw=len({r[ci["KEYWORD"]] for r in snap})
    haspos=sum(1 for r in snap if r[ci["POSITION"]] is not None)
    print(f"\n  {nkw}/15 mots-clés, {haspos} avec position ce mois")
    if nkw<15 or haspos<5:
        print("  ⚠️ snapshot incomplet — on NE crée pas, à investiguer."); sys.exit(1)

    NAME="SEO Keyword Monitoring — Manucurist (model)"
    DESC=("V1 livrable suivi mots-clés SEO Manucurist (gsheet). 15 kw curatés × mois × "
          "Position (COALESCE SERP DataForSEO / GSC) / Volume (KP, dernier connu) / Clics+Impr (GSC), "
          "+ gamme/catégorie + position_serp & position_gsc séparées. Zone US. Mapping kw→gamme→catégorie en dur (V1).")
    pl={"name":NAME,"type":"model","collection_id":SERP_COLLECTION,
        "dataset_query":{"database":DB,"type":"native","native":{"query":MODEL_SQL}},
        "display":"table","visualization_settings":{},"description":DESC}
    existing=None
    for it in mb.get(f"/api/collection/{SERP_COLLECTION}/items?limit=2000").get("data",[]):
        if it.get("model")=="dataset" and it.get("name")==NAME: existing=it.get("id"); break
    if existing:
        mb.put(f"/api/card/{existing}","raw",json=pl,timeout=HTTP_TIMEOUT); MID=existing
        print(f"  modèle mis à jour #{MID}")
    else:
        b=mb.post("/api/card","raw",json=pl,timeout=HTTP_TIMEOUT).json()
        if not b.get("id"): print("ÉCHEC create:",str(b)[:400]); sys.exit(1)
        MID=b["id"]; print(f"  modèle créé #{MID}")
    rm,_=run(mb, f"SELECT * FROM ({MODEL_SQL}) LIMIT 50")
    if rm: mb.put(f"/api/card/{MID}","raw",json={"result_metadata":rm["cols"]},timeout=120)
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> MODÈLE V1 #{MID}: {dom}/model/{MID}")

if __name__=="__main__":
    main()
