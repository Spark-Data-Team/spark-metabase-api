#!/usr/bin/env python3
"""Test différentiel #32496 : requête ACTUELLE vs NETTOYÉE, mêmes filtres Manucurist.

But : prouver que le nettoyage (suppression CTE/jointure ctr_scenario + code mort)
- RÉCUPÈRE les cellules (mot-clé × date) où la meilleure position client > 100
  (silencieusement droppées aujourd'hui par le INNER JOIN ctr_scenario),
- ne supprime RIEN d'autre,
- ne change AUCUNE valeur sur les cellules communes.

Lecture seule. Usage: python3 scripts/serp_difftest.py
"""
from __future__ import annotations
import json, sys, time, glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/"scripts")); sys.path.insert(0, str(ROOT))
import spark_metabase_api.main_methods as MM
MM.DEFAULT_TIMEOUT = 180
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

CLIENT = "Manucurist"
DATE_WINDOW_DAYS = 120
HTTP_TIMEOUT = 240

def connect():
    e=_load_env()
    for a in range(6):
        try:
            mb=Metabase_API(domain=e["METABASE_DOMAIN"],email=e["METABASE_EMAIL"],password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current"); return mb
        except Exception as ex:
            print(f"  retry {a+1}: {type(ex).__name__}"); time.sleep(6)
    sys.exit("conn failed")

def run(mb, sql):
    r=mb.post("/api/dataset","raw",json={"database":144,"type":"native","native":{"query":sql}},timeout=HTTP_TIMEOUT)
    j=r.json() if hasattr(r,"json") else r
    if j.get("error"):
        print("  SQL ERROR:", str(j.get("error"))[:500]); return None, None
    dd=j.get("data",{}); return [c.get("name") for c in dd.get("cols",[])], dd.get("rows",[])

# ---- substitutions communes (OLD et NEW reçoivent EXACTEMENT les mêmes) ----
def subst_common(sql, corpus):
    return sql

def build_old(corpus):
    bk=sorted(glob.glob(str(ROOT/"migration"/"card-32496-backup-*.json")))[-1]
    d=json.loads(Path(bk).read_text())
    lq=d.get("legacy_query"); lq=json.loads(lq) if isinstance(lq,str) else lq
    sql=lq["native"]["query"]
    sql=sql.replace("[[AND {{date}}]]", f"AND date >= DATEADD('day',-{DATE_WINDOW_DAYS},CURRENT_DATE)")
    sql=sql.replace("{{client}}", f"(utils.clients.name = '{CLIENT}')")
    sql=sql.replace("{{corpus_name}}", f"(serp_requests.corpus_name = '{corpus}')")
    sql=sql.replace("{{category}}", "1=1")
    sql=sql.replace("[[AND {{time_period}}]]", "AND name = 'day'")
    sql=sql.replace("{{ctr_scenario}}", "name = 'Default'")
    sql=sql.replace("[[AND serp_requests.keyword ILIKE ('%' || {{pattern_keyword}} || '%')]]", "")
    sql=sql.replace("[[AND serp_requests.keyword = {{exact_keyword}}]]", "")
    # qualifier rn/url ambigus + dedup DÉTERMINISTE (meilleure position par url/run)
    sql=sql.replace("url, rn ORDER BY request_date DESC",
                    "serp__keyword_metrics.url, rr.rn ORDER BY rank_absolute")
    return sql, bk

NEW_TMPL = r"""
WITH get_dates AS (
  SELECT MIN(date) AS min_date_filter, MAX(date) AS max_date_filter
  FROM utils.calendar
  WHERE TRUE AND date >= DATEADD('day',-%DW%,CURRENT_DATE) AND date <= CURRENT_DATE
),
recent_runs AS (
  SELECT client_id, corpus_name, run_date, rn FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY corpus_name, client_id ORDER BY run_date DESC) AS rn
    FROM utils.clients
      JOIN google_serp.serp_refresh_runs ON google_serp.serp_refresh_runs.client_id = utils.clients.id,
      LATERAL (SELECT min_date_filter, max_date_filter FROM get_dates)
    WHERE TRUE AND (utils.clients.name = '%CLIENT%')
      AND run_date >= min_date_filter AND run_date <= max_date_filter
  )
),
time_period AS (
  SELECT name FROM metabase_filters.time_periods WHERE TRUE AND name = 'day'
),
get_current_data AS (
  SELECT rr.rn, serp_requests.domain AS client_domain,
    REGEXP_REPLACE(serp__keyword_metrics.domain, '^(www\.|app\.|mail\.|ftp\.|blog\.|shop\.|m\.|secure\.|dev\.|staging\.|api\.|portal\.|web\.|beta\.)', '', 1, 1, 'i') AS domain,
    serp__keyword_metrics.keyword, serp__keyword_metrics.url, request_date, request_month,
    CASE WHEN type = 'featured_snippet' AND rank_group = 1 THEN 0 ELSE rank_absolute END AS rank_absolute,
    rank_group,
    COALESCE(adjusted_avg_searches, avg_monthly_searches, 0) AS search_volume
  FROM utils.clients
    JOIN google_serp.serp_requests ON google_serp.serp_requests.client_id = utils.clients.id
    JOIN google_serp.serp_history ON (serp_history.keyword = serp_requests.keyword AND serp_history.language = serp_requests.language AND serp_history.zone = serp_requests.zone)
    JOIN google_serp.serp__keyword_metrics ON (serp__keyword_metrics.keyword = serp_history.keyword AND serp__keyword_metrics.language = serp_history.language AND serp__keyword_metrics.zone = serp_history.zone)
    LEFT JOIN google_keyword_planner.kp__keyword_monthly_metrics ON (
        kp__keyword_monthly_metrics.keyword = serp__keyword_metrics.keyword
        AND kp__keyword_monthly_metrics.language = serp__keyword_metrics.language
        AND kp__keyword_monthly_metrics.zone = serp__keyword_metrics.zone
        AND kp__keyword_monthly_metrics.month = TO_VARCHAR(DATEADD('MONTH',
              CASE WHEN EXTRACT(DAY FROM CURRENT_DATE()) >= 10 THEN -2 ELSE -3 END,
              TO_DATE(serp__keyword_metrics.request_month || '-01','YYYY-MM-DD')), 'YYYY-MM'))
    JOIN recent_runs AS rr ON (rr.client_id = serp_requests.client_id
        AND rr.corpus_name = serp_requests.corpus_name
        AND rr.run_date = serp__keyword_metrics.request_date)
  WHERE TRUE AND (utils.clients.name = '%CLIENT%')
    AND (serp_requests.corpus_name = '%CORPUS%') AND 1=1
  QUALIFY ROW_NUMBER() OVER (PARTITION BY serp_history.keyword, serp_history.language, serp_history.zone, serp__keyword_metrics.url, rr.rn ORDER BY rank_absolute) = 1
),
current_final AS (
  SELECT keyword, request_date, search_volume, rank_absolute, rank_group, url
  FROM get_current_data AS d
  WHERE url ILIKE '%' || client_domain || '%'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY keyword, request_date ORDER BY rank_absolute) = 1
),
aggregated_positions AS (
  SELECT d.keyword, tp.name AS period_type,
    CASE tp.name WHEN 'aggregated' THEN NULL WHEN 'year' THEN DATE_TRUNC('YEAR',d.request_date)
      WHEN 'month' THEN DATE_TRUNC('MONTH',d.request_date) WHEN 'week' THEN DATE_TRUNC('WEEK',d.request_date)
      WHEN 'day' THEN DATE_TRUNC('DAY',d.request_date) END AS period_start,
    AVG(d.search_volume) AS avg_search_volume,
    AVG(d.rank_absolute) AS avg_rank_absolute,
    AVG(d.rank_group)    AS avg_rank_group,
    COUNT(*)             AS nb_observations
  FROM current_final AS d CROSS JOIN time_period AS tp
  WHERE d.request_date BETWEEN (SELECT min_date_filter FROM get_dates) AND (SELECT max_date_filter FROM get_dates)
  GROUP BY d.keyword, tp.name,
    CASE tp.name WHEN 'aggregated' THEN NULL WHEN 'year' THEN DATE_TRUNC('YEAR',d.request_date)
      WHEN 'month' THEN DATE_TRUNC('MONTH',d.request_date) WHEN 'week' THEN DATE_TRUNC('WEEK',d.request_date)
      WHEN 'day' THEN DATE_TRUNC('DAY',d.request_date) END
)
SELECT keyword,
  CASE period_type WHEN 'aggregated' THEN 'aggregated' WHEN 'year' THEN TO_CHAR(period_start,'YYYY')
    WHEN 'month' THEN TO_CHAR(period_start,'YYYY')||'-'||INITCAP(MONTHNAME(period_start))
    WHEN 'week' THEN YEAROFWEEK(period_start)::VARCHAR||'-W'||LPAD(WEEKOFYEAR(period_start)::VARCHAR,2,'0')
    WHEN 'day' THEN TO_CHAR(period_start,'YYYY-MM-DD') END AS periode_label,
  avg_search_volume, avg_rank_absolute, avg_rank_group, nb_observations AS nb_points
FROM aggregated_positions
ORDER BY keyword, period_start DESC NULLS LAST
"""

def build_new(corpus):
    return (NEW_TMPL.replace("%DW%", str(DATE_WINDOW_DAYS))
                    .replace("%CLIENT%", CLIENT)
                    .replace("%CORPUS%", corpus))

def to_map(cols, rows):
    ki, kl = cols.index("KEYWORD") if "KEYWORD" in cols else 0, cols.index("PERIODE_LABEL") if "PERIODE_LABEL" in cols else 1
    ai = cols.index("AVG_RANK_ABSOLUTE") if "AVG_RANK_ABSOLUTE" in cols else 3
    m={}
    for r in rows:
        m[(r[ki], r[kl])] = r[ai]
    return m

def main():
    mb=connect(); print("connected")
    # corpus exact
    c,r=run(mb, f"""
      SELECT DISTINCT corpus_name FROM google_serp.serp_requests sr
      JOIN utils.clients c ON c.id=sr.client_id
      WHERE c.name='{CLIENT}' AND corpus_name ILIKE '%transactionnel%' ORDER BY 1
    """)
    print("corpus transactionnels Manucurist:", r)
    target="Corpus transactionnel FR - Mots clés stratégiques"
    cands=[x[0] for x in r]
    corpus = target if target in cands else (cands[0] if cands else target)
    print("corpus retenu:", repr(corpus))

    # --- la carte LIVE #32496 compile-t-elle ? (params Manucurist, fenêtre courte) ---
    params=[
      {"type":"string/=","value":["Manucurist"],"target":["dimension",["template-tag","client"]]},
      {"type":"string/=","value":[corpus],"target":["dimension",["template-tag","corpus_name"]]},
      {"type":"string/=","value":["day"],"target":["dimension",["template-tag","time_period"]]},
      {"type":"string/=","value":["Default"],"target":["dimension",["template-tag","ctr_scenario"]]},
      {"type":"date/all-options","value":"2026-03-01~2026-05-28","target":["dimension",["template-tag","date"]]},
    ]
    try:
        rr=mb.post("/api/card/32496/query/json","raw",data={"parameters":json.dumps(params)},timeout=HTTP_TIMEOUT)
        body=rr.json() if hasattr(rr,"json") else rr
        if isinstance(body,dict) and body.get("error"):
            print("  CARTE LIVE #32496 -> ERREUR:", str(body.get("error"))[:200])
        elif isinstance(body,list):
            print(f"  CARTE LIVE #32496 -> OK, {len(body)} lignes")
        else:
            print("  CARTE LIVE #32496 -> réponse:", str(body)[:200])
    except Exception as ex:
        print("  CARTE LIVE #32496 -> exception:", type(ex).__name__, str(ex)[:160])

    print("\n... run OLD (actuel)"); co,ro=run(mb, build_old(corpus)[0])
    if co is None: return
    print("    OLD lignes:", len(ro))
    print("... run NEW (nettoyé)"); cn,rn=run(mb, build_new(corpus))
    if cn is None: return
    print("    NEW lignes:", len(rn))

    mo, mn = to_map(co,ro), to_map(cn,rn)
    ko, kn = set(mo), set(mn)
    new_only = kn-ko; old_only = ko-kn
    common = ko & kn
    diffs = [(k, mo[k], mn[k]) for k in common if mo[k]!=mn[k]]

    print("\n========== RÉSULTAT DU DIFF ==========")
    print(f"cellules (mot-clé × date)  OLD={len(ko)}  NEW={len(kn)}")
    print(f"  RÉCUPÉRÉES par le fix (NEW only) : {len(new_only)}")
    print(f"  perdues (OLD only, attendu 0)    : {len(old_only)}")
    print(f"  communes valeurs différentes (attendu 0): {len(diffs)}")

    if new_only:
        vals=[mn[k] for k in new_only]
        over100=sum(1 for v in vals if v is not None and v>100)
        print(f"\n  parmi les récupérées : {over100}/{len(new_only)} ont position > 100 "
              f"(min={min(vals)}, max={max(vals)})")
        print("  exemples récupérés (mot-clé, date, position):")
        for k in sorted(new_only)[:8]:
            print(f"    {k[0][:45]:45}  {k[1]}  pos={mn[k]}")
    if old_only:
        print("\n  !! OLD only (régression?) exemples:", sorted(old_only)[:5])
    if diffs:
        print("\n  !! valeurs divergentes exemples:", diffs[:5])

if __name__=="__main__":
    main()
