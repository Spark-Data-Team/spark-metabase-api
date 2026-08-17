#!/usr/bin/env python3
"""Modèle mots-clés V3 — SEO Keyword Monitoring | Manucurist (gsheet V3).

Ajoute vs V2 : Gamme, Catégorie, URL positionnée, Potentiel de trafic (vol×CTR position),
Δ vs M-3, clics TOTAUX + split géo (Trafic FR/UK/US/Autres), Δ clics vs M-1.
16 kw US + 18 kw FR. Mapping gamme/catégorie : US = gsheet ; FR = proposition (à valider).
Met à jour #48633 en place. Valide un snapshot avant PUT.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB=144; MODEL_ID=48633; HTTP_TIMEOUT=600

# (keyword, gamme, categorie)
US=[("gel polish kit","Gel Polish","Transactionnel"),
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
    ("base coat","Nailcare","Produit"),
    ("top coat","Nailcare","Produit"),
    ("nail treatment","Nailcare","Informationnel")]
# FR : mapping proposé (à valider avec Thibaut)
FR=[("vernis semi permanent","Gel Polish","Générique"),
    ("french manucure","Nail Polish","Générique"),
    ("kit vernis semi permanent","Gel Polish","Transactionnel"),
    ("kit manucure","Nailcare","Transactionnel"),
    ("vernis a ongle","Nail Polish","Générique"),
    ("top coat","Nailcare","Produit"),
    ("lampe uv ongles","Gel Polish","Produit"),
    ("base coat","Nailcare","Produit"),
    ("soin des ongles","Nailcare","Générique"),
    ("kit manucure semi permanent","Gel Polish","Transactionnel"),
    ("dissolvant vernis semi permanent","Gel Polish","Produit"),
    ("vernis amer","Nailcare","Produit"),
    ("vernis durcisseur","Nailcare","Produit"),
    ("kit semi permanent","Gel Polish","Transactionnel"),
    ("dissolvant semi permanent","Gel Polish","Produit"),
    ("couleur vernis","Nail Polish","Générique"),
    ("huile cuticule","Nailcare","Produit"),
    ("vernis naturel","Nail Polish","Clean / Engagement")]
def esc(s): return s.replace("'","''")
VALUES=",\n    ".join([f"('{esc(k)}','US','{g}','{c}')" for k,g,c in US]
                     +[f"('{esc(k)}','FR','{g}','{c}')" for k,g,c in FR])
ALL_IN=",".join(sorted({f"'{esc(k)}'" for k,_,_ in US+FR}))

# CASE marché (section de site) réutilisé pour les clics géo
def market_case(col="page"):
    return (f"CASE WHEN {col} ILIKE 'https://us.manucurist.com%' THEN 'US' "
            f"WHEN {col} ILIKE 'https://uk.manucurist.com%' THEN 'UK' "
            f"WHEN REGEXP_LIKE({col},'https://www[.]manucurist[.]com/(en|es|it|de|nl|el|pt)(/.*)?') THEN 'AUTRES' "
            f"WHEN {col} ILIKE 'https://www.manucurist.com%' THEN 'FR' ELSE 'AUTRES' END")

MODEL_SQL=f"""
WITH kw_map AS (
  SELECT * FROM (VALUES
    {VALUES}
  ) AS t(keyword, marche, gamme, categorie)
),
zone_map AS (
  SELECT keyword, marche, gamme, categorie,
         CASE marche WHEN 'FR' THEN 'France' WHEN 'US' THEN 'United States' END AS zone
  FROM kw_map
),
months AS (
  SELECT DISTINCT DATE_TRUNC('month', date) AS month_date
  FROM utils.calendar
  WHERE date >= DATEADD('month', -13, CURRENT_DATE) AND date <= CURRENT_DATE
),
gcd AS (
  SELECT serp_requests.zone AS zone,
         LOWER(serp__keyword_metrics.keyword) AS keyword,
         serp__keyword_metrics.url AS url, serp__keyword_metrics.request_date,
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
  SELECT zone, keyword, request_date, rank_absolute, REGEXP_REPLACE(url,'[?].*$','') AS url
  FROM gcd WHERE url ILIKE '%' || client_domain || '%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY zone, keyword, request_date ORDER BY rank_absolute) = 1
),
pos AS (
  SELECT zone, keyword, DATE_TRUNC('month', request_date) AS month_date, AVG(rank_absolute) AS position
  FROM client_pos GROUP BY 1,2,3
),
url_pos AS (
  SELECT zone, keyword, url FROM (
    SELECT zone, keyword, url,
           ROW_NUMBER() OVER (PARTITION BY zone, keyword ORDER BY request_date DESC, rank_absolute) rn
    FROM client_pos
  ) WHERE rn=1
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
  SELECT LOWER(keyword) AS keyword, DATE_TRUNC('month', date) AS month_date,
    SUM(clicks) AS clicks, SUM(impressions) AS impressions,
    SUM(position*impressions)/NULLIF(SUM(impressions),0) AS gsc_position,
    SUM(CASE WHEN {market_case()}='FR' THEN clicks ELSE 0 END) AS clicks_fr,
    SUM(CASE WHEN {market_case()}='UK' THEN clicks ELSE 0 END) AS clicks_uk,
    SUM(CASE WHEN {market_case()}='US' THEN clicks ELSE 0 END) AS clicks_us,
    SUM(CASE WHEN {market_case()}='AUTRES' THEN clicks ELSE 0 END) AS clicks_autres
  FROM google_search_console.gsc__page_keyword_daily_metrics
  WHERE client_name='Manucurist' AND LOWER(keyword) IN ({ALL_IN})
    AND date >= DATEADD('month', -13, CURRENT_DATE)
  GROUP BY 1,2
),
assembled AS (
  SELECT
    m.month_date, z.marche, z.gamme, z.categorie, z.keyword,
    up.url AS url_positionnee,
    LEAST(COALESCE(pos.position, g.gsc_position, 100), 100) AS position,
    pos.position AS position_serp, g.gsc_position AS position_gsc,
    vol.search_volume AS search_volume,
    g.clicks AS clicks, g.impressions AS impressions,
    COALESCE(g.clicks_fr,0) AS clicks_fr, COALESCE(g.clicks_uk,0) AS clicks_uk,
    COALESCE(g.clicks_us,0) AS clicks_us, COALESCE(g.clicks_autres,0) AS clicks_autres
  FROM zone_map z
    CROSS JOIN months m
    LEFT JOIN pos ON pos.zone=z.zone AND pos.keyword=z.keyword AND pos.month_date=m.month_date
    LEFT JOIN gsc g ON g.keyword=z.keyword AND g.month_date=m.month_date
    LEFT JOIN vol ON vol.zone=z.zone AND vol.keyword=z.keyword
    LEFT JOIN url_pos up ON up.zone=z.zone AND up.keyword=z.keyword
),
withctr AS (
  SELECT a.*,
    ROUND(a.search_volume * COALESCE(ctr.ctr_medium,0)) AS potentiel_trafic
  FROM assembled a
    LEFT JOIN metabase_filters.serp_ctr_scenarios ctr
      ON ctr.name='Default' AND ctr.position = LEAST(GREATEST(ROUND(a.position),0),100)
)
SELECT w.*,
  LAG(position)   OVER (PARTITION BY marche, keyword ORDER BY month_date) - position AS delta_m1,
  LAG(position,3) OVER (PARTITION BY marche, keyword ORDER BY month_date) - position AS delta_m3,
  clicks - LAG(clicks) OVER (PARTITION BY marche, keyword ORDER BY month_date)        AS delta_clicks_m1
FROM withctr w
ORDER BY marche, gamme, keyword, month_date DESC
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
    nkw=len(US)+len(FR)
    res,err=run(mb, MODEL_SQL)
    if err: print("ÉCHEC SQL:",err[:700]); sys.exit(1)
    cols=[c["name"] for c in res["cols"]]; rows=res["rows"]; ci={n:i for i,n in enumerate(cols)}
    print(f"modèle: {len(rows)} lignes (attendu {nkw}×14≈{nkw*14}), cols={cols}")
    months=sorted({r[ci["MONTH_DATE"]] for r in rows})
    prev=months[-2] if len(months)>=2 else months[-1]
    snap=[r for r in rows if r[ci["MONTH_DATE"]]==prev]
    print(f"\nSNAPSHOT {str(prev)[:7]} (extrait) :")
    print("  M  GAMME       MOT-CLÉ                    POS POT.TRAF VOL   CLICS  FR/UK/US/AU         URL")
    okurl=okpot=okgeo=0
    for r in sorted(snap, key=lambda r:(r[ci["MARCHE"]], r[ci["POSITION"]] if r[ci["POSITION"]] is not None else 999))[:12]:
        u=r[ci["URL_POSITIONNEE"]]; pot=r[ci["POTENTIEL_TRAFIC"]]
        geo=f"{int(r[ci['CLICKS_FR']] or 0)}/{int(r[ci['CLICKS_UK']] or 0)}/{int(r[ci['CLICKS_US']] or 0)}/{int(r[ci['CLICKS_AUTRES']] or 0)}"
        print(f"  {r[ci['MARCHE']]:2} {str(r[ci['GAMME']]):11} {r[ci['KEYWORD']][:24]:24} "
              f"{('%.0f'%r[ci['POSITION']]):>3} {('%.0f'%pot if pot is not None else '.'):>7} "
              f"{('%.0f'%r[ci['SEARCH_VOLUME']] if r[ci['SEARCH_VOLUME']] else '.'):>6} "
              f"{('%.0f'%r[ci['CLICKS']] if r[ci['CLICKS']] is not None else '.'):>5}  {geo:16} {str(u)[:38] if u else '—'}")
    for r in snap:
        if r[ci["URL_POSITIONNEE"]]: okurl+=1
        if r[ci["POTENTIEL_TRAFIC"]] is not None: okpot+=1
        if (r[ci["CLICKS_FR"]] or r[ci["CLICKS_UK"]] or r[ci["CLICKS_US"]] or r[ci["CLICKS_AUTRES"]]): okgeo+=1
    print(f"\n  {len(snap)} lignes | URL pos.: {okurl} | potentiel calc.: {okpot} | géo non-nul: {okgeo}")
    if len(snap)!=nkw or okpot<nkw-2:
        print("  ⚠️ incomplet — PAS de PUT."); sys.exit(1)

    DESC=("V3 (gsheet Thibaut juin). 16 kw US + 18 kw FR × mois × Gamme/Catégorie (US=gsheet, FR=proposé à valider) / "
          "position (SERP zone, repli GSC ; 100=non classé) / URL positionnée (SERP) / Volume (kp) / "
          "Potentiel de trafic (volume×CTR position, scénario Default) / Clics GSC TOTAUX + split géo FR/UK/US/Autres (section de site) / "
          "Δ M-1, Δ M-3 (positions), Δ clics M-1.")
    r=mb.put(f"/api/card/{MODEL_ID}","raw",json={
        "name":"SEO Keyword Monitoring — Manucurist (model)",
        "dataset_query":{"database":DB,"type":"native","native":{"query":MODEL_SQL}},
        "description":DESC},timeout=HTTP_TIMEOUT)
    print("PUT modèle:",getattr(r,"status_code","?"))
    rm,_=run(mb, f"SELECT * FROM ({MODEL_SQL}) LIMIT 40")
    if rm: print("PUT metadata:",getattr(mb.put(f"/api/card/{MODEL_ID}","raw",json={"result_metadata":rm["cols"]},timeout=120),"status_code","?"))
    print(f"\n>>> MODÈLE V3 #{MODEL_ID} mis à jour ({nkw} kw)")

if __name__=="__main__":
    main()
