#!/usr/bin/env python3
"""Modèle pages V2 — clics par gabarit × marché × Marque/Hors Marque | Manucurist.

Source unique : gsc__page_keyword_daily_metrics (27M lignes, hist. 2024-02→).
- marché   : section du site via URL (www=FR, us.=US, uk.=UK, locales www/xx=AUTRES)
- gabarit  : /blogs/=Blog, /collections/=Collections, /products/=Produits, sinon Autres pages
- marque   : requête contenant un radical de gsc__brand_keywords → 'Marque', sinon 'Hors Marque'
- mois × clics/impressions + Δ 6 mois % et tendance (LAG par marché×gabarit×marque)

⚠️ granularité requête GSC = échantillonnée (requêtes anonymisées exclues) →
les totaux sont < clics réels de la page ; cohérent en tendance.
Crée ou met à jour le modèle. Valide avant PUT.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; HTTP_TIMEOUT=480
NAME="SEO Pages Monitoring — Manucurist (model)"

MODEL_SQL="""
WITH brand_pat AS (
  SELECT DISTINCT LOWER(keyword) AS pat
  FROM google_search_console.gsc__brand_keywords
  WHERE client_name='Manucurist'
),
base AS (
  SELECT
    DATE_TRUNC('month', date) AS month_date,
    CASE WHEN page ILIKE 'https://us.manucurist.com%' THEN 'US'
         WHEN page ILIKE 'https://uk.manucurist.com%' THEN 'UK'
         WHEN REGEXP_LIKE(page, 'https://www[.]manucurist[.]com/(en|es|it|de|nl|el|pt)(/.*)?') THEN 'AUTRES'
         WHEN page ILIKE 'https://www.manucurist.com%' THEN 'FR'
         ELSE 'AUTRES' END AS marche,
    CASE WHEN page ILIKE '%/blogs/%' THEN 'Blog'
         WHEN page ILIKE '%/collections/%' THEN 'Collections'
         WHEN page ILIKE '%/products/%' THEN 'Produits'
         ELSE 'Autres pages' END AS gabarit,
    LOWER(keyword) AS keyword,
    clicks, impressions
  FROM google_search_console.gsc__page_keyword_daily_metrics
  WHERE client_name='Manucurist'
    AND date >= DATEADD('month', -14, CURRENT_DATE)
),
kw_flag AS (
  SELECT k.keyword,
         CASE WHEN COUNT(b.pat) > 0 THEN 'Marque' ELSE 'Hors Marque' END AS marque
  FROM (SELECT DISTINCT keyword FROM base) k
  LEFT JOIN brand_pat b ON k.keyword LIKE '%' || b.pat || '%'
  GROUP BY k.keyword
),
agg AS (
  SELECT b.month_date, b.marche, b.gabarit, f.marque,
         SUM(b.clicks) AS clicks, SUM(b.impressions) AS impressions
  FROM base b JOIN kw_flag f ON f.keyword=b.keyword
  GROUP BY 1,2,3,4
)
SELECT a.*,
  ROUND(100.0 * (clicks - LAG(clicks,6) OVER (PARTITION BY marche, gabarit, marque ORDER BY month_date))
        / NULLIF(LAG(clicks,6) OVER (PARTITION BY marche, gabarit, marque ORDER BY month_date), 0), 1) AS delta_6m_pct,
  CASE
    WHEN LAG(clicks,6) OVER (PARTITION BY marche, gabarit, marque ORDER BY month_date) IS NULL THEN NULL
    WHEN clicks >= 1.05 * LAG(clicks,6) OVER (PARTITION BY marche, gabarit, marque ORDER BY month_date) THEN '↗ on gagne'
    WHEN clicks <= 0.95 * LAG(clicks,6) OVER (PARTITION BY marche, gabarit, marque ORDER BY month_date) THEN '↘ on recule'
    ELSE '→ stable'
  END AS tendance
FROM agg a
ORDER BY marche, gabarit, marque, month_date DESC
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
    print(f"modèle pages: {len(rows)} lignes, cols={cols}")
    months=sorted({r[ci["MONTH_DATE"]] for r in rows})
    prev=months[-2] if len(months)>=2 else months[-1]
    snap=[r for r in rows if r[ci["MONTH_DATE"]]==prev and r[ci["MARCHE"]] in ('FR','US','UK')
          and r[ci["GABARIT"]]!='Autres pages']
    print(f"\nSNAPSHOT {str(prev)[:7]} (FR/US/UK, hors 'Autres pages') :")
    print("  MARCHÉ GABARIT      MARQUE       CLICS    Δ6M%   TENDANCE")
    for r in sorted(snap, key=lambda r:(r[ci["MARCHE"]], r[ci["GABARIT"]], r[ci["MARQUE"]])):
        print(f"  {r[ci['MARCHE']]:6} {r[ci['GABARIT']]:12} {r[ci['MARQUE']]:12} "
              f"{('%.0f'%r[ci['CLICKS']] if r[ci['CLICKS']] is not None else '.'):>7} "
              f"{(str(r[ci['DELTA_6M_PCT']]) if r[ci['DELTA_6M_PCT']] is not None else '.'):>7}  {r[ci['TENDANCE']] or '.'}")
    if not snap: print("  ⚠️ vide — PAS de création."); sys.exit(1)

    pl={"name":NAME,"type":"model","collection_id":13752,
        "dataset_query":{"database":DB,"type":"native","native":{"query":MODEL_SQL}},
        "display":"table","visualization_settings":{},
        "description":("V2. Clics GSC par gabarit (Blog/Collections/Produits via URL) × marché du site "
        "(www=FR, us.=US, uk.=UK) × Marque/Hors Marque (radicaux gsc__brand_keywords) × mois, + Δ 6 mois % et tendance. "
        "Source: gsc__page_keyword_daily (granularité requête → totaux échantillonnés GSC).")}
    existing=None
    for it in mb.get("/api/collection/13752/items?limit=2000").get("data",[]):
        if it.get("model")=="dataset" and it.get("name")==NAME: existing=it.get("id"); break
    if existing:
        mb.put(f"/api/card/{existing}","raw",json=pl,timeout=HTTP_TIMEOUT); MID=existing; print("modèle pages maj #",MID)
    else:
        b=mb.post("/api/card","raw",json=pl,timeout=HTTP_TIMEOUT).json()
        if not b.get("id"): print("ÉCHEC create:",str(b)[:400]); sys.exit(1)
        MID=b["id"]; print("modèle pages créé #",MID)
    rm,_=run(mb, f"SELECT * FROM ({MODEL_SQL}) LIMIT 40")
    if rm: mb.put(f"/api/card/{MID}","raw",json={"result_metadata":rm["cols"]},timeout=120)
    dom=_load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> MODÈLE PAGES #{MID}: {dom}/model/{MID}")

if __name__=="__main__":
    main()
