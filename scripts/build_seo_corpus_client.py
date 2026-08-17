#!/usr/bin/env python3
"""Pile 'Suivi mots-clés par corpus' GÉNÉRIQUE — généralise la pile Manucurist (#52065/#52066/#52067/#27183).

Construit pour n'importe quel client : modèle corpus-driven + carte synthèse + carte évolution (pivot)
+ dashboard filtré (Corpus, Catégorie, Top N, Mot-clé contient/exact, Période).
La config vit dans Nanga (google_serp.serp_requests) : tout nouveau corpus du client remonte tout seul.

Différences assumées vs la pile Manucurist :
  - aucun corpus exclu par défaut (la liste EXCLUDE de Manucurist n'a pas de sens ailleurs) ; --exclude si besoin
  - marché : mapping zone -> code générique (DE, IT, ES, NL... et pas seulement FR/US/UK)
  - GSC joint par client_id (pas par nom) et catégories dédoublonnées à la casse
  - une seule ligne par (corpus, mot-clé, zone) garantie -> pas de double comptage des clics
  - gate de validation volumétrique générique (pas de noms de corpus en dur)

Usage :
    python scripts/build_seo_corpus_client.py --client "Arrago"                     # dry-run
    python scripts/build_seo_corpus_client.py --client "Arrago" --apply             # écrit dans Metabase
    python scripts/build_seo_corpus_client.py --client "Arrago" --collection 5700 \
        --default-corpus "Corpus mots clés 2026" --apply
"""
from __future__ import annotations
import argparse, json, sys, time, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB = 144
CLIENTS_ROOT = 317          # "3. Clients | Custom Dashs & Questions"
TMO = 600
u = lambda: str(uuid.uuid4())

# zone SERP -> code marché lisible (ELSE : on garde le nom de la zone)
ZONES = {"France": "FR", "United States": "US", "United Kingdom": "UK", "Germany": "DE", "Italy": "IT",
         "Spain": "ES", "Netherlands": "NL", "Belgium": "BE", "Switzerland": "CH", "Canada": "CA",
         "Portugal": "PT", "Austria": "AT", "Ireland": "IE", "Poland": "PL", "Greece": "GR",
         "Iceland": "IS", "India": "IN", "Mexico": "MX", "Singapore": "SG", "Morocco": "MA",
         "South Africa": "ZA", "Sweden": "SE", "Denmark": "DK", "Norway": "NO", "Finland": "FI",
         "Japan": "JP", "Australia": "AU", "Brazil": "BR"}


def esc(s: str) -> str:
    return s.replace("'", "''")


def UA(col: str) -> str:
    """Désaccentue pour rapprocher SERP / GSC / Keyword Planner."""
    return f"TRANSLATE(LOWER({col}),'àâäéèêëîïôöùûüçœ','aaaeeeeiioouuuce')"


def marche_case(col: str = "sr.zone") -> str:
    whens = " ".join(f"WHEN '{esc(z)}' THEN '{c}'" for z, c in ZONES.items())
    return f"CASE {col} {whens} ELSE {col} END"


def build_sql(client: str, exclude: list[str]) -> str:
    cl = esc(client)
    excl = ""
    if exclude:
        excl = "\n    AND sr.corpus_name NOT IN (" + ",".join("'" + esc(x) + "'" for x in exclude) + ")"
    return f"""
WITH cat_canon AS (
  -- une seule orthographe par catégorie (fusionne 'All Keywords' / 'All keywords')
  SELECT LOWER(TRIM(sr.category)) AS cat_lc, MIN(TRIM(sr.category)) AS category
  FROM google_serp.serp_requests sr JOIN utils.clients c ON sr.client_id=c.id
  WHERE c.name='{cl}' AND NULLIF(TRIM(sr.category),'') IS NOT NULL
  GROUP BY 1
),
corpus_kw AS (
  -- 1 ligne par (corpus, mot-clé, zone) : évite le double comptage si un kw porte 2 catégories
  SELECT sr.corpus_name, LOWER(sr.keyword) AS keyword, {UA('sr.keyword')} AS keyword_ua,
         MIN(cc.category) AS category, sr.zone, sr.language, {marche_case()} AS marche
  FROM google_serp.serp_requests sr
    JOIN utils.clients c ON sr.client_id=c.id
    LEFT JOIN cat_canon cc ON cc.cat_lc = LOWER(TRIM(sr.category))
  WHERE c.name='{cl}'{excl}
  GROUP BY sr.corpus_name, LOWER(sr.keyword), {UA('sr.keyword')}, sr.zone, sr.language
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
  WHERE c.name='{cl}'{excl}
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
  WHERE client_id IN (SELECT id FROM utils.clients WHERE name='{cl}')
    AND date >= DATEADD('month',-13,CURRENT_DATE)
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


# ---------------------------------------------------------------- Metabase
def connect() -> Metabase_API:
    e = _load_env()
    for _ in range(6):
        try:
            mb = Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current", timeout=60); return mb
        except Exception as ex:
            print("retry", repr(ex)[:80], flush=True); time.sleep(8)
    sys.exit("connexion Metabase impossible")


def resolve_collection(mb: Metabase_API, client: str) -> int:
    for it in mb.get(f"/api/collection/{CLIENTS_ROOT}/items?models=collection&limit=1000").get("data", []):
        if it.get("name", "").strip().lower() == client.strip().lower():
            return it["id"]
    sys.exit(f"collection '{client}' introuvable sous {CLIENTS_ROOT} — passer --collection <id>")


def find(mb: Metabase_API, coll: int, kind: str, name: str):
    for it in mb.get(f"/api/collection/{coll}/items?limit=2000").get("data", []):
        if it.get("model") == kind and it.get("name") == name:
            return it["id"]
    return None


def upsert(mb: Metabase_API, coll: int, kind: str, name: str, payload: dict):
    cid = find(mb, coll, kind, name)
    if cid:
        mb.put(f"/api/card/{cid}", "raw", json=payload, timeout=TMO); return cid, "maj"
    return mb.post("/api/card", "raw", json=payload, timeout=TMO).json().get("id"), "créé"


# ---------------------------------------------------------------- viz helpers
def fl(name, bt, extra=None):
    o = {"base-type": bt, "lib/uuid": u()}
    if extra: o.update(extra)
    return ["field", o, name]


def fr(name, bt, extra=None):
    o = {"base-type": bt}
    if extra: o.update(extra)
    return ["field", name, o]


def cs(name, opts): return {json.dumps(["name", name]): opts}
def dec0(t): return {"column_title": t, "number_style": "decimal", "decimals": 0}


def bands(col, kind):
    if kind == "rank":
        steps = [(3, "#0B5226"), (10, "#2E7D32"), (20, "#66BB6A"), (50, "#A5D6A7"), (100, "#E8F5E9")]; op = "<="
    else:
        steps = [(100, "#2E6CA8"), (50, "#5B8DC0"), (25, "#9CC0E0"), (10, "#DCE9F5")]; op = ">="
    return [{"columns": [col], "type": "single", "operator": op, "value": v, "color": c} for v, c in steps]


# ---------------------------------------------------------------- gate
def validate(mb: Metabase_API, sql: str, client: str) -> dict:
    """Agrégats côté Snowflake (l'API /api/dataset tronque à 2000 lignes)."""
    vsql = f"""SELECT corpus_name, marche, COUNT(*) AS n_rows, COUNT(DISTINCT keyword) AS n_kw,
             COUNT(DISTINCT CASE WHEN position_serp IS NOT NULL THEN keyword END) AS kw_avec_position,
             SUM(COALESCE(clicks,0)) AS clicks_13m, COUNT(DISTINCT category) AS n_cat,
             SUM(CASE WHEN rang_clics<=25 THEN COALESCE(clicks,0) ELSE 0 END) AS clicks_top25,
             COUNT(DISTINCT CASE WHEN search_volume IS NOT NULL THEN keyword END) AS kw_avec_volume
             FROM ({sql}) GROUP BY 1,2 ORDER BY clicks_13m DESC, n_kw DESC"""
    t0 = time.monotonic()
    r = mb.post("/api/dataset", "raw", json={"database": DB, "type": "native", "native": {"query": vsql}}, timeout=TMO).json()
    if r.get("error"):
        print("ÉCHEC SQL:", str(r["error"])[:900], flush=True); sys.exit(1)
    cols = [c["name"] for c in r["data"]["cols"]]; rows = r["data"]["rows"]; ci = {n: i for i, n in enumerate(cols)}
    print(f"run modèle : {time.monotonic()-t0:.0f}s | {len(rows)} groupes corpus × marché", flush=True)
    print(f"\n{'corpus':46} | marché | lignes |   kw | pos. | vol. | clics 13m (top25) | cat", flush=True)
    tot_rows = tot_kw = tot_pos = tot_clicks = 0
    for row in rows:
        tot_rows += row[ci["N_ROWS"]]; tot_kw += row[ci["N_KW"]]
        tot_pos += row[ci["KW_AVEC_POSITION"]]; tot_clicks += int(row[ci["CLICKS_13M"]] or 0)
        print(f"{str(row[ci['CORPUS_NAME']])[:46]:46} | {str(row[ci['MARCHE']]):6} | {row[ci['N_ROWS']]:6} | "
              f"{row[ci['N_KW']]:4} | {row[ci['KW_AVEC_POSITION']]:4} | {row[ci['KW_AVEC_VOLUME']]:4} | "
              f"{int(row[ci['CLICKS_13M']] or 0):8} ({int(row[ci['CLICKS_TOP25']] or 0):6}) | {row[ci['N_CAT']]}", flush=True)
    print(f"\ntotal : {tot_rows} lignes | {tot_kw} mots-clés | {tot_pos} avec position SERP | {tot_clicks} clics 13 mois", flush=True)

    # gate générique
    problems = []
    if not rows: problems.append("aucun corpus renvoyé")
    if tot_rows == 0: problems.append("modèle vide")
    if tot_pos == 0: problems.append("aucune position SERP (jointure domaine/serp_history cassée ?)")
    if problems:
        print("\n⚠️  GATE ÉCHOUÉE :", " ; ".join(problems), "— aucune écriture.", flush=True); sys.exit(1)
    if tot_clicks == 0:
        print("\n⚠️  aucun clic GSC : le client n'a pas de GSC connectée, les colonnes Clics/Impressions resteront vides.", flush=True)
    print("✅ gate OK", flush=True)
    return {"rows": rows, "ci": ci, "tot_kw": tot_kw}


# ---------------------------------------------------------------- build
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--collection", type=int, default=None)
    ap.add_argument("--default-corpus", default=None, help="corpus pré-sélectionné dans le filtre du dashboard")
    ap.add_argument("--exclude", default="", help="corpus à exclure du modèle, séparés par des virgules")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    client = a.client.strip()
    exclude = [x.strip() for x in a.exclude.split(",") if x.strip()]
    mb = connect()
    coll = a.collection or resolve_collection(mb, client)
    print(f"client: {client} | collection: {coll} | mode: {'APPLY' if a.apply else 'dry-run'}", flush=True)
    if exclude: print("corpus exclus:", exclude, flush=True)

    sql = build_sql(client, exclude)
    validate(mb, sql, client)

    MODEL_NAME = f"SEO Corpus Monitoring — {client} (model)"
    SYNTH_NAME = f"SEO Corpus — synthèse du dernier mois (tri par clics) | {client}"
    INV_NAME   = f"SEO Corpus — évolution par mot-clé (mois en lignes) | {client}"
    DASH_NAME  = f"Suivi mots-clés par corpus | {client}"

    if not a.apply:
        print(f"\nDONE dry-run — à créer dans la collection {coll} :", flush=True)
        for n in (MODEL_NAME, SYNTH_NAME, INV_NAME, DASH_NAME): print("   •", n, flush=True)
        print("   (relancer avec --apply pour écrire)", flush=True)
        return

    # ---- modèle
    DESC = (f"Suivi corpus-driven Nanga pour {client}. Tous les corpus du client, par marché et par mois. "
            "Position SERP avec repli GSC (100 = non classé), volume Keyword Planner, clics et impressions GSC "
            "avec rapprochement insensible aux accents. RANG_CLICS classe les mots-clés par clics dans chaque "
            "corpus et marché (sert au filtre Top N). Les nouveaux corpus créés dans Nanga remontent automatiquement.")
    MID, how = upsert(mb, coll, "dataset", MODEL_NAME, {
        "name": MODEL_NAME, "type": "model", "collection_id": coll,
        "dataset_query": {"database": DB, "type": "native", "native": {"query": sql}},
        "display": "table", "visualization_settings": {}, "description": DESC})
    print(f"modèle {how} #{MID}", flush=True)
    rm = mb.post("/api/dataset", "raw", json={"database": DB, "type": "native",
                                              "native": {"query": f"SELECT * FROM ({sql}) LIMIT 40"}}, timeout=TMO).json()
    if not rm.get("error"):
        mb.put(f"/api/card/{MID}", "raw", json={"result_metadata": rm["data"]["cols"]}, timeout=120)
        print("result_metadata posé", flush=True)

    # ---- carte synthèse
    synth_q = {"database": DB, "type": "query", "query": {
        "source-table": f"card__{MID}",
        "fields": [fr("MARCHE", "type/Text"), fr("CATEGORY", "type/Text"), fr("KEYWORD", "type/Text"),
                   fr("SEARCH_VOLUME", "type/Float"), fr("POSITION", "type/Float"), fr("DELTA_M1", "type/Float"),
                   fr("CLICKS", "type/Float"), fr("IMPRESSIONS", "type/Float")],
        "filter": ["time-interval", fr("MONTH_DATE", "type/Date"), -1, "month"],
        "order-by": [["desc", fr("CLICKS", "type/Float")]]}}
    synth_viz = {"column_settings": {
        **cs("MARCHE", {"column_title": "Marché"}), **cs("CATEGORY", {"column_title": "Catégorie"}),
        **cs("KEYWORD", {"column_title": "Mot-clé"}), **cs("SEARCH_VOLUME", dec0("Volume rech.")),
        **cs("POSITION", dec0("Position")), **cs("DELTA_M1", dec0("Évolution M-1")),
        **cs("CLICKS", dec0("Clics GSC")), **cs("IMPRESSIONS", dec0("Impressions"))},
        "table.column_formatting": bands("POSITION", "rank") + bands("CLICKS", "clics")}
    SYNTH, how = upsert(mb, coll, "card", SYNTH_NAME, {
        "name": SYNTH_NAME, "collection_id": coll, "dataset_query": synth_q, "display": "table",
        "visualization_settings": synth_viz,
        "description": "Synthèse du dernier mois complet pour le corpus choisi, classée du mot-clé le plus cliqué au moins cliqué. Position en vert (foncé = bonne position), clics en bleu."})
    print(f"synthèse {how} #{SYNTH}", flush=True)
    jr = mb.post("/api/dataset", "raw", json=synth_q, timeout=TMO).json()
    if not jr.get("error"):
        mb.put(f"/api/card/{SYNTH}", "raw", json={"result_metadata": jr["data"]["cols"]}, timeout=120)

    # ---- carte évolution (pivot MLv2)
    inv_dq = {"database": DB, "lib/type": "mbql/query", "stages": [{
        "lib/type": "mbql.stage/mbql", "source-card": MID,
        "aggregation": [["sum", {"lib/uuid": u()}, fl("SEARCH_VOLUME", "type/Number")],
                        ["avg", {"lib/uuid": u()}, fl("POSITION", "type/Number")],
                        ["sum", {"lib/uuid": u()}, fl("IMPRESSIONS", "type/Number")],
                        ["sum", {"lib/uuid": u()}, fl("CLICKS", "type/Number")]],
        "breakout": [fl("MONTH_DATE", "type/Date", {"temporal-unit": "month"}), fl("KEYWORD", "type/Text")]}]}
    inv_viz = {"pivot_table.column_split": {
        "rows": [fr("MONTH_DATE", "type/Date", {"temporal-unit": "month"})],
        "columns": [fr("KEYWORD", "type/Text")],
        "values": [["aggregation", 0], ["aggregation", 1], ["aggregation", 2], ["aggregation", 3]]},
        "pivot.show_row_totals": False, "pivot.show_column_totals": False,
        "column_settings": {
            json.dumps(["name", "MONTH_DATE"]): {"column_title": "Mois"},
            json.dumps(["name", "KEYWORD"]): {"column_title": "Mot-clé"},
            json.dumps(["name", "sum"]): dec0("Volume"),
            json.dumps(["name", "avg"]): dec0("Rank"),
            json.dumps(["name", "sum_2"]): dec0("Impressions"),
            json.dumps(["name", "sum_3"]): dec0("Clics")},
        "table.column_formatting": bands("avg", "rank") + bands("sum_3", "clics")}
    INV, how = upsert(mb, coll, "card", INV_NAME, {
        "name": INV_NAME, "collection_id": coll, "dataset_query": inv_dq, "display": "pivot",
        "visualization_settings": inv_viz,
        "description": "Les mois en lignes, les mots-clés en colonnes, et pour chacun son volume, son rank, ses impressions et ses clics. Filtré par corpus et Top N par clics."})
    print(f"évolution {how} #{INV}", flush=True)
    legacy = {"database": DB, "type": "query", "query": {
        "source-table": f"card__{MID}",
        "aggregation": [["sum", fr("SEARCH_VOLUME", "type/Number")], ["avg", fr("POSITION", "type/Number")],
                        ["sum", fr("IMPRESSIONS", "type/Number")], ["sum", fr("CLICKS", "type/Number")]],
        "breakout": [fr("MONTH_DATE", "type/Date", {"temporal-unit": "month"}), fr("KEYWORD", "type/Text")]}}
    jr = mb.post("/api/dataset", "raw", json=legacy, timeout=TMO).json()
    if not jr.get("error"):
        mb.put(f"/api/card/{INV}", "raw", json={"result_metadata": jr["data"]["cols"]}, timeout=120)

    # ---- dashboard
    did = find(mb, coll, "dashboard", DASH_NAME)
    if not did:
        did = mb.post("/api/dashboard", "raw", json={
            "name": DASH_NAME, "collection_id": coll,
            "description": "Suivi mensuel des mots-clés par corpus Nanga. Choisis un corpus, le tableau montre les mots-clés les plus cliqués (Top N réglable) et leur évolution mois par mois. Les nouveaux corpus créés dans Nanga apparaissent automatiquement."}).json().get("id")
        print("dashboard créé #", did, flush=True)
    else:
        print("dashboard existant #", did, flush=True)

    def dyn(field):
        return {"values_query_type": "list", "values_source_type": "card",
                "values_source_config": {"card_id": MID, "value_field": ["field", field, {"base-type": "type/Text"}]}}
    P = [{"id": "corpus01", "name": "Corpus", "slug": "corpus", "type": "string/=", "sectionId": "string", **dyn("CORPUS_NAME")},
         {"id": "categ01", "name": "Catégorie", "slug": "categorie", "type": "string/=", "sectionId": "string", **dyn("CATEGORY")},
         {"id": "topn01", "name": "Top mots-clés (par clics)", "slug": "top_n", "type": "number/<=", "sectionId": "number", "default": [25]},
         {"id": "pat01", "name": "Mot-clé (contient)", "slug": "pattern_keyword", "type": "string/contains", "sectionId": "string"},
         {"id": "exact01", "name": "Mot-clé (exact)", "slug": "exact_keyword", "type": "string/=", "sectionId": "string"},
         {"id": "date01", "name": "Période", "slug": "date", "type": "date/all-options", "sectionId": "date", "default": "past6months"}]
    if a.default_corpus:
        P[0]["default"] = [a.default_corpus]

    CO = fr("CORPUS_NAME", "type/Text"); CA = fr("CATEGORY", "type/Text")
    KW = fr("KEYWORD", "type/Text"); RN = fr("RANG_CLICS", "type/Number"); MO = fr("MONTH_DATE", "type/Date")

    def m(pid, cid, field): return {"parameter_id": pid, "card_id": cid, "target": ["dimension", field]}

    def maps(cid, with_date):
        l = [m("corpus01", cid, CO), m("categ01", cid, CA), m("topn01", cid, RN),
             m("pat01", cid, KW), m("exact01", cid, KW)]
        if with_date: l.append(m("date01", cid, MO))
        return l

    def txt(t):
        return {"text": t, "virtual_card": {"name": None, "display": "text", "visualization_settings": {},
                                            "dataset_query": {}, "archived": False},
                "text.align_vertical": "middle", "text.align_horizontal": "left", "dashcard.background": False}

    dashcards = [
        {"id": -1, "card_id": None, "row": 0, "col": 0, "size_x": 24, "size_y": 2, "series": [], "parameter_mappings": [],
         "visualization_settings": txt("## 📈 Vue d'ensemble du corpus\nLes mots-clés du corpus choisi sur le dernier mois complet, classés du plus au moins cliqué. Le filtre Top limite aux mots-clés les plus cliqués.")},
        {"id": -2, "card_id": SYNTH, "row": 2, "col": 0, "size_x": 24, "size_y": 9, "series": [],
         "parameter_mappings": maps(SYNTH, False),
         "visualization_settings": {"card.title": "Synthèse du dernier mois complet, triée par clics"}},
        {"id": -3, "card_id": None, "row": 11, "col": 0, "size_x": 24, "size_y": 2, "series": [], "parameter_mappings": [],
         "visualization_settings": txt("## 📊 Évolution par mot-clé\nLes mois en lignes, les mots-clés en colonnes, et pour chacun son volume, son rank, ses impressions et ses clics. Le rank est en vert (foncé = bonne position), les clics en bleu. Scrolle vers la droite pour voir tous les mots-clés.")},
        {"id": -4, "card_id": INV, "row": 13, "col": 0, "size_x": 24, "size_y": 12, "series": [],
         "parameter_mappings": maps(INV, True),
         "visualization_settings": {"card.title": "Évolution de chaque mot-clé mois après mois"}},
    ]
    r = mb.put(f"/api/dashboard/{did}", "raw", json={"parameters": P, "dashcards": dashcards}, timeout=TMO)
    bb = r.json() if hasattr(r, "json") else r
    print("dashboard PUT:", getattr(r, "status_code", "?"),
          "| dashcards:", len(bb.get("dashcards", [])) if isinstance(bb, dict) else "?",
          "| filtres:", [p.get("slug") for p in (bb.get("parameters") or [])] if isinstance(bb, dict) else "?", flush=True)
    dom = _load_env()["METABASE_DOMAIN"].rstrip("/")
    print(f"\n>>> DASHBOARD #{did} : {dom}/dashboard/{did}", flush=True)


if __name__ == "__main__":
    main()
