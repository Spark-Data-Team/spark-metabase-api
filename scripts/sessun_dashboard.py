# -*- coding: utf-8 -*-
"""Campagne : dashboard « Media & Sales | Sessùn », sur le modèle de « Shopify | Polène » (16427).

Rejouable : une carte ou un dashboard déjà présent dans la collection Sessùn est mis à jour, jamais dupliqué.

    .venv/bin/python scripts/sessun_dashboard.py          # crée ou met à jour, puis contrôle
    .venv/bin/python scripts/sessun_dashboard.py controle # contrôle seulement

Même forme de requêtes que Polène : les dates passent par utils.calendar, donc un seul {{date}} filtre ventes et dépenses
dans la même carte ; {{time_period}} règle la granularité, {{comparison_date}} la période de comparaison (vide : les N jours
d'avant). Sources : GLOBAL.CAMPAIGN_DAILY_METRICS pour le média, ANALYTICS.GOOGLE__ANALYTICS_METRICS pour le trafic,
CLIENT_DATA.SESSUN__* pour le reste. Les tables restent sans alias : Metabase écrit "SCHEMA"."TABLE"."COLONNE".

Décisions de Louis du 06/11/2026 : nouveaux clients Splio arrêtés au dernier chargement, sur deux périodes de même durée ;
ROAS sur le CA HT net de retours ; filtre Marché hors de la Vue d'ensemble (les dépenses ne se répartissent pas par marché).
Retours rattachés à la date de commande (spark-pipelines #1507) : ils mettent environ 35 jours à arriver, donc CA net, ROAS et
taux de retour ne montrent aucune évolution sur une période plus récente.
"""
import json
import re
import sys
import textwrap
import uuid

from spark_metabase_api import cards, connect, dashboards, http

DB = 144
COLLECTION = 15237
DASHBOARD = 30879
NOM = "Media & Sales | Sessùn"
CLIENT = "rec7aHUXyxAvMBEiw"
MARCHES = ["FR", "DE", "EN", "ES", "GB", "NL", "IT", "US", "CH"]
CALENDRIER = 419201

SALES = "client_data.sessun__sales_daily_metrics"
PRODUCTS = "client_data.sessun__product_daily_metrics"
RETAIL = "client_data.sessun__retail_daily_metrics"
COHORTS = "client_data.sessun__crm_cohort_metrics"
RFM = "client_data.sessun__rfm_metrics"
MEDIA = "global.campaign_daily_metrics"
TRAFFIC = "analytics.google__analytics_metrics"

EUR = {"number_style": "currency", "currency": "EUR", "currency_style": "symbol", "decimals": 0}
PCT = {"number_style": "percent", "decimals": 1}
DEC = {"number_style": "decimal", "decimals": 2}
ENT = {"number_style": "decimal", "decimals": 0}

# Une couleur par mesure, partout ; version pâle pour la période précédente.
COULEURS = {"net": ("#FC926D", "#FDC1AB"), "orders": ("#6896E9", "#A0BDF1"), "spend": ("#F7C41F", "#FBE39A"), "roas": ("#51B8A6", "#A8DCD2"),
            "cost_order": ("#A989C5", "#D4C4E2"), "ncac": ("#E66775", "#F2B3BA"), "new": ("#88BF4D", "#C3DFA6"), "first": ("#8C9BAE", "#C5CDD6"),
            "refund": ("#E66775", "#F2B3BA"), "rate": ("#A989C5", "#D4C4E2")}
PLATEFORMES = {"Meta": "#6896E9", "Google": "#F8E26F", "TikTok": "#EAB1E1", "Pinterest": "#E66775"}
MARCHES_C = {"FR": "#6896E9", "DE": "#FC926D", "EN": "#88BF4D", "ES": "#F7C41F", "GB": "#A989C5", "NL": "#51B8A6", "US": "#E66775", "IT": "#EAB1E1", "CH": "#8C9BAE"}
SEGMENTS_C = {"Champions": "#6896E9", "Loyal": "#88BF4D", "New": "#51B8A6", "At risk": "#F7C41F", "To reactivate": "#FC926D", "Lost": "#8C9BAE"}
TYPES_C = {"Pantalon": "#6896E9", "Chemise": "#FC926D", "Robe": "#88BF4D", "Manteau": "#A989C5", "Pull": "#F7C41F", "Sac": "#E66775", "Veste": "#51B8A6", "Jean": "#EAB1E1", "Other": "#C5CDD6"}
CANAUX_C = {"Paid social": "#E66775", "Paid search": "#FC926D", "Other": "#6896E9", "Organic": "#F7C41F", "Referral": "#A989C5", "AI assistants": "#EAB1E1", "Other paid": "#51B8A6"}


def source(table, *portee):
    return {"table": table, "portee": list(portee)}


S_SALES = source(SALES)
S_MEDIA = source(MEDIA, f"{MEDIA}.client_id = '{CLIENT}' -- Sessùn")
S_TRAFFIC = source(TRAFFIC, f"{TRAFFIC}.client_id = '{CLIENT}' -- Sessùn")
S_PRODUCTS = source(PRODUCTS)
S_RETAIL = source(RETAIL)

# Splio et les tickets boutique sont chargés à la main, jusqu'à un mois de retard. Le dernier jour chargé est partiel
# (mesuré : 33 commandes sur 117 le 13/10/2026), comme le dernier jour de GA4 : on s'arrête au dernier jour complet.
CHARGEMENTS = {
    "splio": f"SELECT DATEADD(day, -1, MAX(date)) AS last_date\nFROM {SALES}\nWHERE new_customers_splio IS NOT NULL",
    "boutique": f"SELECT DATEADD(day, -1, MAX(date)) AS last_date\nFROM {RETAIL}",
    "trafic": f"SELECT DATEADD(day, -1, MAX(date)) AS last_date\nFROM {TRAFFIC}\nWHERE client_id = '{CLIENT}'",
}
# Les retours mettent environ 35 jours à arriver : plus récent, un CA net ne se compare pas.
RECENT = "(SELECT current_end FROM periods) > DATEADD(day, -35, CURRENT_DATE)"


# ---- Fabrique de SQL ------------------------------------------------------------------------------------------------
def tag(nom):
    return "[[AND {{" + nom + "}}]]"


def cte(nom, corps):
    return f"{nom} AS (\n{textwrap.indent(corps, '    ')}\n)"


def clause_where(conditions, filtres=()):
    conditions = list(conditions) or ["TRUE"]
    lignes = ["WHERE " + conditions[0]] + ["    AND " + c for c in conditions[1:]] + ["    " + tag(f) for f in filtres]
    return "\n".join(lignes)


def clause_select(dims, colonnes):
    lignes = list(dims) + [f"{expr} AS {alias}" for alias, expr in colonnes.items()]
    return "SELECT\n" + ",\n".join("    " + l for l in lignes)


def periodes(arret=None, fin_splio=False):
    """Bornes des deux périodes. arret : elles s'arrêtent au dernier chargement. fin_splio : colonne en plus pour Splio."""
    debut_cmp = "COALESCE(cmp.start_date, DATEADD(day, -(DATEDIFF(day, cur.start_date, cur.end_date) + 1), cur.start_date))"
    fin_cur = "LEAST(MAX(date), CURRENT_DATE, (SELECT last_date FROM last_load))" if arret else "LEAST(MAX(date), CURRENT_DATE)"
    fin_cmp = (f"DATEADD(day, DATEDIFF(day, cur.start_date, cur.end_date), {debut_cmp})" if arret
               else "COALESCE(cmp.end_date, DATEADD(day, -1, cur.start_date))")
    colonnes = ["cur.start_date AS current_start", "cur.end_date AS current_end",
                f"{debut_cmp} AS comparison_start", f"{fin_cmp} AS comparison_end"]
    if fin_splio:
        # Une seule fenêtre de comparaison pour Splio, la même que sur les tuiles.
        fin_splio_sql = "LEAST(cur.end_date, (SELECT last_date FROM last_load))"
        debut_splio = f"COALESCE(cmp.start_date, DATEADD(day, -(DATEDIFF(day, cur.start_date, {fin_splio_sql}) + 1), cur.start_date))"
        colonnes += [f"{debut_splio} AS comparison_start_splio", f"DATEADD(day, DATEDIFF(day, cur.start_date, {fin_splio_sql}), {debut_splio}) AS comparison_end_splio"]
    commentaire = ("-- Le dernier chargement borne les deux périodes, qui gardent la même durée.\n" if arret else
                   "-- Bornes des deux périodes, lues dans les filtres et non dans les données.\n"
                   "-- comparison_date vide : les N jours juste avant la période date.\n")
    return (commentaire + "SELECT\n" + ",\n".join("    " + c for c in colonnes) + f"""
FROM (
    SELECT MIN(date) AS start_date, {fin_cur} AS end_date
    FROM utils.calendar
    WHERE FALSE [[OR {{{{date}}}}]]
) AS cur,
(
    SELECT MIN(date) AS start_date, MAX(date) AS end_date
    FROM utils.calendar
    WHERE FALSE [[OR {{{{comparison_date}}}}]]
) AS cmp""")


def debut_periodes(arret=None, fin_splio=False):
    chargement = "splio" if fin_splio else arret
    ctes = [cte("last_load", CHARGEMENTS[chargement])] if chargement else []
    return ctes + [cte("periods", periodes(arret, fin_splio))]


def lecture_courante(s, colonnes, filtres=(), dims=(), arret=None):
    t = s["table"]
    if arret:
        lignes = [clause_select(dims, colonnes), f"FROM {t}",
                  clause_where(s["portee"] + [f"{t}.date BETWEEN (SELECT current_start FROM periods) AND (SELECT current_end FROM periods)"], filtres)]
    else:
        lignes = [clause_select(dims, colonnes), f"FROM {t}", f"    JOIN utils.calendar ON utils.calendar.date = {t}.date",
                  clause_where(s["portee"], ("date",) + tuple(filtres))]
    return "\n".join(lignes + (["GROUP BY 1"] if dims else []))


def lecture_precedente(s, colonnes, filtres=(), dims=()):
    t = s["table"]
    lignes = [clause_select(dims, colonnes), f"FROM {t}",
              clause_where(s["portee"] + [f"{t}.date BETWEEN (SELECT comparison_start FROM periods) AND (SELECT comparison_end FROM periods)"], filtres)]
    return "\n".join(lignes + (["GROUP BY 1"] if dims else []))


# ---- Fabrique de cartes ---------------------------------------------------------------------------------------------
def sur_graphique(f):
    """Avec decimals à 0, un libellé compact écrit 3M pour 3,7 M, et répète la même valeur sur l'axe."""
    return {k: v for k, v in f.items() if not (k == "decimals" and v == 0)}


def lignes_camembert(couleurs):
    """Une entité garde sa couleur entre le donut et les barres."""
    return [{"key": n, "name": n, "originalName": n, "color": c, "defaultColor": False, "enabled": True, "hidden": False, "isOther": False} for n, c in couleurs.items()]


def formats(colonnes):
    return {"column_settings": {json.dumps(["name", nom.upper()], ensure_ascii=False, separators=(",", ":")): f for nom, f in colonnes.items()}}


def carte(cle, titre, sql, display, viz, description=None):
    return {"cle": cle, "titre": titre, "sql": sql.strip(), "display": display, "viz": viz, "description": description}


def kpi(colonne, titre, sources, valeur, f, filtres=(), arret=None, inverse=False, description=None, recent=False):
    """Tuile tendance : deux lignes (comparaison puis période), comme Polène. sources : {alias: (source, {colonne: expression})}."""
    ctes = debut_periodes(arret)
    for alias, (s, colonnes) in sources.items():
        ctes.append(cte(f"current_{alias}", lecture_courante(s, colonnes, filtres, arret=arret)))
        ctes.append(cte(f"previous_{alias}", lecture_precedente(s, colonnes, filtres)))
    courant = valeur.format(**{a: f"current_{a}" for a in sources})
    precedent = valeur.format(**{a: f"previous_{a}" for a in sources})
    if recent:
        precedent = f"IFF({RECENT}, NULL, {precedent})"
    sql = "WITH " + ",\n\n".join(ctes) + f"""

-- Vraies dates conservées ; l'ordre (comparaison puis actuelle) est imposé par row_rank,
-- car la carte tendance compare la dernière ligne à l'avant-dernière.
SELECT * EXCLUDE (row_rank)
FROM (
    SELECT 0 AS row_rank, periods.comparison_end AS display_date, {precedent} AS {colonne}
    FROM {', '.join('previous_' + a for a in sources)}, periods
    UNION ALL
    SELECT 1 AS row_rank, periods.current_end AS display_date, {courant} AS {colonne}
    FROM {', '.join('current_' + a for a in sources)}, periods
)
ORDER BY row_rank"""
    viz = {"scalar.comparisons": [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "sessun/kpi/" + colonne)), "type": "previousValue"}], **formats({colonne: f})}
    if inverse:
        viz["scalar.switch_positive_negative"] = True
    return carte("kpi_" + colonne, titre, sql, "smartscalar", viz, description)


def serie(colonne, expr, titre, f, couleur, display="bar", courant=None):
    return {"colonne": colonne, "expr": expr, "courant": courant or expr, "titre": titre, "f": f, "couleurs": COULEURS[couleur], "display": display}


def combo(cle, titre, sources, series, arret=None, description=None, un_axe=False):
    """Période en cours contre période de comparaison, recalée sur les mêmes tranches. Mêmes bornes que les tuiles."""
    ctes = debut_periodes(arret)
    borne = ["utils.calendar.date <= (SELECT current_end FROM periods)"] if arret else []
    for alias, (s, colonnes) in sources.items():
        t = s["table"]
        dims = ["{{time_period}} AS time_period"]
        ctes.append(cte(f"current_{alias}", "\n".join([
            clause_select(dims, colonnes), f"FROM {t}", f"    JOIN utils.calendar ON utils.calendar.date = {t}.date",
            clause_where(s["portee"] + borne, ("date",) + tuple(s.get("filtres", ()))),
            "GROUP BY 1"])))
        ctes.append(cte(f"previous_{alias}", "\n".join([
            clause_select(dims, colonnes), f"FROM {t}", "    JOIN periods ON TRUE",
            f"    JOIN utils.calendar ON utils.calendar.date = DATEADD('day', DATEDIFF(day, periods.comparison_start, periods.current_start), {t}.date)",
            clause_where(s["portee"] + [f"{t}.date BETWEEN periods.comparison_start AND periods.comparison_end"], tuple(s.get("filtres", ()))),
            "GROUP BY 1"])))
    pilote = next(iter(sources))
    courants = {a: f"current_{a}" for a in sources}
    precedents = {a: f"previous_{a}" for a in sources}
    lignes = [f"current_{pilote}.time_period"]
    for x in series:
        lignes += [f"{x['courant'].format(**courants)} AS current_{x['colonne']}", f"{x['expr'].format(**precedents)} AS previous_{x['colonne']}"]
    jointures = [f"current_{a}" for a in sources if a != pilote] + [f"previous_{a}" for a in sources]
    sql = "WITH " + ",\n\n".join(ctes) + "\n\nSELECT\n" + ",\n".join("    " + l for l in lignes) + f"\nFROM current_{pilote}\n" + "".join(
        f"    LEFT JOIN {j} ON {j}.time_period = current_{pilote}.time_period\n" for j in jointures) + "ORDER BY 1"
    reglages, metriques, formes = {}, [], {}
    for x in series:
        cur, prev = f"CURRENT_{x['colonne'].upper()}", f"PREVIOUS_{x['colonne'].upper()}"
        metriques += [cur, prev]
        formes.update({f"current_{x['colonne']}": sur_graphique(x["f"]), f"previous_{x['colonne']}": sur_graphique(x["f"])})
        reglages[cur] = {"title": x["titre"], "color": x["couleurs"][0], "display": x["display"]}
        # Seule la période en cours porte des libellés, sinon le graphique devient illisible.
        reglages[prev] = {"title": x["titre"] + " (previous)", "color": x["couleurs"][1], "display": x["display"], "show_series_values": False,
                          **({"line.style": "dashed"} if x["display"] == "line" else {})}
    viz = {"graph.dimensions": ["TIME_PERIOD"], "graph.metrics": metriques, "series_settings": reglages, "graph.x_axis.scale": "timeseries",
           "graph.x_axis.axis_enabled": "compact", "graph.x_axis.labels_enabled": False, "graph.y_axis.labels_enabled": False, "graph.show_values": True,
           "graph.label_value_frequency": "fit", "graph.label_value_formatting": "compact", **formats(formes)}
    if un_axe:
        viz["graph.y_axis.auto_split"] = False
    return carte(cle, titre, sql, "combo", viz, description)


def donut(cle, titre, s, dim, alias, mesure, colonne, f, filtres=(), description=None, couleurs=None):
    sql = lecture_courante(s, {colonne: mesure}, filtres, dims=[f"{dim} AS {alias}"]) + "\nORDER BY 2 DESC"
    viz = {"pie.dimension": [alias.upper()], "pie.metric": colonne.upper(), "pie.show_legend": True, "pie.show_legend_perecent": True, "pie.percent_visibility": "legend",
           "pie.decimal_places": 1, "pie.slice_threshold": 0, **formats({colonne: f})}
    if couleurs:
        viz["pie.rows"] = lignes_camembert(couleurs)
    return carte(cle, titre, sql, "pie", viz, description)


def viz_empile(alias, colonne, f, couleurs=None):
    viz = {"graph.dimensions": ["TIME_PERIOD", alias.upper()], "graph.metrics": [colonne.upper()], "stackable.stack_type": "stacked",
           "graph.x_axis.scale": "timeseries", "graph.x_axis.axis_enabled": "compact", "graph.x_axis.labels_enabled": False, "graph.y_axis.labels_enabled": False,
           "graph.show_values": True, "graph.show_stack_values": "total", "graph.label_value_frequency": "fit", "graph.label_value_formatting": "compact", **formats({colonne: sur_graphique(f)})}
    if couleurs:
        viz["series_settings"] = {n: {"color": c} for n, c in couleurs.items()}
    return viz


def empile(cle, titre, s, dim, alias, mesure, colonne, f, filtres=(), couleurs=None, description=None):
    t = s["table"]
    sql = "\n".join([clause_select(["{{time_period}} AS time_period", f"{dim} AS {alias}"], {colonne: mesure}), f"FROM {t}",
                     f"    JOIN utils.calendar ON utils.calendar.date = {t}.date", clause_where(s["portee"], ("date",) + tuple(filtres)),
                     "GROUP BY 1, 2", f"ORDER BY time_period ASC, {colonne} ASC"])
    return carte(cle, titre, sql, "bar", viz_empile(alias, colonne, f, couleurs), description)


def col(alias, expr, titre, f, delta=True, mini=False, recent=False):
    return {"alias": alias, "expr": expr, "titre": titre, "f": f, "delta": delta, "mini": mini, "recent": recent}


def part(alias, mesure, titre):
    """Part dans le total des lignes, calculée avant la coupe du top N."""
    return col(alias, f"c.{mesure} / NULLIF(SUM(IFF(c.rank = 2, c.{mesure}, 0)) OVER (), 0)", titre, PCT, delta=False)


def tableau(cle, titre, s, dim, alias, titre_dim, mesures, colonnes, tri, filtres=(), arret=None, fin_splio=False, mesures_prec=None,
            total=True, limite=None, ou=(), ordre=None, description=None, mesures_cour=None, plein=False):
    """Tableau avec ligne Total et Δ contre la période de comparaison, comme Polène."""
    noms = list(mesures)
    ctes = debut_periodes(arret, fin_splio)
    dims = [f"{dim} AS {alias}"]
    ctes.append(cte("current_data", lecture_courante(s, mesures_cour or mesures, filtres, dims, arret)))
    ctes.append(cte("previous_data", lecture_precedente(s, mesures_prec or mesures, filtres, dims)))
    if total:
        liste = ", ".join([alias] + noms)
        sommes = ", ".join(f"SUM({n}) AS {n}" for n in noms)
        for periode in ("current", "previous"):
            ctes.append(cte(f"{periode}_final", f"SELECT 2 AS rank, {liste}\nFROM {periode}_data\nUNION ALL\nSELECT 1 AS rank, 'Total' AS {alias}, {sommes}\nFROM {periode}_data"))
    gauche, droite = ("current_final", "previous_final") if total else ("current_data", "previous_data")
    # plein : un produit sans vente sur la période reste listé, c'est la plus forte des baisses.
    lignes = (["c.rank AS rank"] if total else []) + [f"COALESCE(c.{alias}, p.{alias}) AS {alias}" if plein else f"c.{alias} AS {alias}"]
    affichees, reglages = ([{"name": "RANK", "enabled": False}] if total else []) + [{"name": alias.upper(), "enabled": True}], {alias: {"column_title": titre_dim}}
    for x in colonnes:
        lignes.append(f"{x['expr'].format(t='c')} AS {x['alias']}")
        affichees.append({"name": x["alias"].upper(), "enabled": True})
        reglages[x["alias"]] = {**x["f"], "column_title": x["titre"], **({"show_mini_bar": True} if x["mini"] else {})}
        if x["delta"]:
            delta = f"({x['expr'].format(t='c')} - {x['expr'].format(t='p')}) / NULLIF(ABS({x['expr'].format(t='p')}), 0)"
            lignes.append(f"{f'IFF({RECENT}, NULL, {delta})' if x['recent'] else delta} AS delta_{x['alias']}")
            affichees.append({"name": f"DELTA_{x['alias'].upper()}", "enabled": True})
            reglages[f"delta_{x['alias']}"] = {**PCT, "column_title": "Δ " + x["titre"]}
    conditions = ([] if plein else [f"c.{alias} IS NOT NULL"]) + list(ou)
    sql = "WITH " + ",\n\n".join(ctes) + "\n\nSELECT\n" + ",\n".join("    " + l for l in lignes) + f"\nFROM {gauche} AS c\n"
    sql += f"    {'FULL' if plein else 'LEFT'} JOIN {droite} AS p ON p.{alias} = c.{alias}" + (" AND p.rank = c.rank" if total else "") + "\n"
    sql += clause_where(conditions) + "\nORDER BY " + (ordre or (("c.rank ASC, " if total else "") + f"{tri} DESC NULLS LAST"))
    if limite:
        sql += f"\nLIMIT {limite + 1 if total else limite}"
    viz = {"table.columns": affichees, **formats(reglages)}
    if total:
        viz["table.column_formatting"] = [{"columns": [alias.upper()], "type": "single", "operator": "=", "value": "Total", "color": "#6896E9", "highlight_row": True}]
    return carte(cle, titre, sql, "table", viz, description)


# ---- Définitions ----------------------------------------------------------------------------------------------------
NET_HT = "SUM(revenue_ht - refund_value_ht)"
CANAL = """CASE
        WHEN LOWER(medium) = 'paid' AND LOWER(source) IN ('meta', 'tiktok', 'pinterest', 'snapchat') THEN 'Paid social'
        WHEN LOWER(medium) = 'paid' AND LOWER(source) IN ('google', 'microsoft') THEN 'Paid search'
        WHEN LOWER(medium) = 'paid' THEN 'Other paid'
        WHEN LOWER(medium) = 'organic' THEN 'Organic'
        WHEN LOWER(medium) = 'referral' THEN 'Referral'
        WHEN LOWER(medium) = 'ia' THEN 'AI assistants'
        ELSE 'Other'
    END"""
PLATEFORME = "CASE WHEN LOWER(campaign_channel) = 'tiktok' THEN 'TikTok' ELSE INITCAP(campaign_channel) END"
TYPE_PRODUIT = "COALESCE(product_type, 'Not specified')"
CATEGORIE = "INITCAP(REPLACE(REGEXP_REPLACE(product_category, '[0-9]+$', ''), '-', ' '))"
FILTRES_PRODUIT = ("market", "product_type", "product_name")
S_PRODUITS_NOMMES = source(PRODUCTS, f"{PRODUCTS}.product_name <> 'unknown'")
S_MODELES = source(PRODUCTS, f"{PRODUCTS}.product_family IS NOT NULL")

D_NOUVEAUX = "First order across all channels, from Splio: a customer who already bought in store does not count. Stops at the last Splio load, and the comparison covers the same number of days."
D_PREMIERES = "First order seen on the website, updated daily. Also counts customers who already bought in store, so it runs higher than Splio new customers."
D_RECENT = " Returns take about 35 days to come in: figures are provisional and show no change until then."
D_NET = "Website sales minus tax and returns, shipping included. A refund counts on the date of its order." + D_RECENT
D_RETOUR = "Refunded amount / gross revenue incl. tax, for the orders of the period." + D_RECENT
D_P1 = "Previous: the same days in the comparison period, by default the period just before."
D_BOUTIQUE = "Splio receipts, amounts as loaded, tax not available. Stops at the last load, and the comparison covers the same number of days."

SEGMENT = """CASE segments.rfm_segment
        WHEN 'Fidèles' THEN 'Loyal'
        WHEN 'Nouveaux' THEN 'New'
        WHEN 'À risque' THEN 'At risk'
        WHEN 'À réactiver' THEN 'To reactivate'
        WHEN 'Perdus' THEN 'Lost'
        ELSE segments.rfm_segment
    END"""
SEGMENT_TABLE = SEGMENT.replace("segments.", "")
V = {"sales": (S_SALES, {"net_revenue_ht": NET_HT})}
M = {"media": (S_MEDIA, {"cost": "SUM(cost)"})}

CARTES = [
    # ---- Chiffres clés ------------------------------------------------------------------------------------------------
    kpi("cost", "Spend", M, "{media}.cost", EUR, description="Media cost across all platforms: Meta, Google, TikTok, Pinterest."),
    kpi("total_orders", "Orders", {"sales": (S_SALES, {"total_orders": "SUM(orders)"})}, "{sales}.total_orders", ENT, description="Website orders."),
    kpi("blended_cac", "Cost per order", {**M, "sales": (S_SALES, {"total_orders": "SUM(orders)"})}, "{media}.cost / NULLIF({sales}.total_orders, 0)", EUR, inverse=True, description="Spend / website orders."),
    kpi("new_customers", "New customers", {"sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)"})}, "{sales}.new_customers", ENT, arret="splio", description=D_NOUVEAUX),
    kpi("blended_ncac", "New customer CAC", {**M, "sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)"})}, "{media}.cost / NULLIF({sales}.new_customers, 0)", EUR, arret="splio", inverse=True, description="Spend / Splio new customers, on the days covered by the last load."),
    kpi("first_orders", "First orders", {"sales": (S_SALES, {"first_orders": "SUM(first_orders_web)"})}, "{sales}.first_orders", ENT, description=D_PREMIERES),
    kpi("avg_order_value", "AOV incl. tax", {"sales": (S_SALES, {"revenue_ttc": "SUM(revenue_ttc)", "total_orders": "SUM(orders)"})}, "{sales}.revenue_ttc / NULLIF({sales}.total_orders, 0)", EUR, description="Gross revenue incl. tax / orders."),
    kpi("net_revenue_ht", "Net revenue", V, "{sales}.net_revenue_ht", EUR, filtres=("market",), description=D_NET, recent=True),
    kpi("blended_roas", "Blended ROAS", {**V, **M}, "{sales}.net_revenue_ht / NULLIF({media}.cost, 0)", DEC, description="Net revenue excl. tax / spend." + D_RECENT, recent=True),
    kpi("revenue_ttc", "Gross revenue", {"sales": (S_SALES, {"revenue_ttc": "SUM(revenue_ttc)"})}, "{sales}.revenue_ttc", EUR, description="Website sales, tax and shipping included, before returns."),
    kpi("return_rate", "Return rate", {"sales": (S_SALES, {"refund_value_ttc": "SUM(refund_value_ttc)", "revenue_ttc": "SUM(revenue_ttc)"})}, "{sales}.refund_value_ttc / NULLIF({sales}.revenue_ttc, 0)", PCT, filtres=("market",), inverse=True, description=D_RETOUR, recent=True),
    kpi("refund_value_ttc", "Refunded amount", {"sales": (S_SALES, {"refund_value_ttc": "SUM(refund_value_ttc)"})}, "{sales}.refund_value_ttc", EUR, filtres=("market",), inverse=True, description="Website refunds incl. tax, on the date of their order." + D_RECENT, recent=True),
    kpi("total_refunds", "Refunds", {"sales": (S_SALES, {"total_refunds": "SUM(refunds)"})}, "{sales}.total_refunds", ENT, filtres=("market",), inverse=True, description="Number of website refunds, on the date of their order." + D_RECENT, recent=True),
    # ---- Vue d'ensemble : évolutions --------------------------------------------------------------------------------------
    combo("c_orders_revenue", "Orders and net revenue by period", {"sales": (S_SALES, {"net_revenue_ht": NET_HT, "total_orders": "SUM(orders)"})},
          [serie("total_orders", "{sales}.total_orders", "Orders", ENT, "orders"),
           serie("net_revenue_ht", "{sales}.net_revenue_ht", "Net revenue", EUR, "net", "line")], description=D_P1 + D_RECENT),
    combo("c_roas_revenue", "Blended ROAS and net revenue by period", {**V, **M},
          [serie("net_revenue_ht", "{sales}.net_revenue_ht", "Net revenue", EUR, "net"),
           serie("blended_roas", "{sales}.net_revenue_ht / NULLIF({media}.cost, 0)", "Blended ROAS", DEC, "roas", "line")], description=D_P1 + D_RECENT),
    combo("c_cac_orders", "Cost per order and orders by period", {"sales": (S_SALES, {"total_orders": "SUM(orders)"}), **M},
          [serie("total_orders", "{sales}.total_orders", "Orders", ENT, "orders"),
           serie("blended_cac", "{media}.cost / NULLIF({sales}.total_orders, 0)", "Cost per order", EUR, "cost_order", "line")], description=D_P1),
    combo("c_orders_cost", "Orders and spend by period", {"sales": (S_SALES, {"total_orders": "SUM(orders)"}), **M},
          [serie("total_orders", "{sales}.total_orders", "Orders", ENT, "orders"),
           serie("cost", "{media}.cost", "Spend", EUR, "spend", "line")], description=D_P1),
    combo("c_revenue_cost", "Net revenue and spend by period", {**V, **M},
          [serie("net_revenue_ht", "{sales}.net_revenue_ht", "Net revenue", EUR, "net"),
           serie("cost", "{media}.cost", "Spend", EUR, "spend", "line")], description=D_P1 + D_RECENT, un_axe=True),
    combo("c_ncac", "New customer CAC by period (to last Splio load)", {"sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)"}), **M},
          [serie("blended_ncac", "{media}.cost / NULLIF({sales}.new_customers, 0)", "New customer CAC", EUR, "ncac", "line")], arret="splio", description=D_NOUVEAUX),
    combo("c_new_vs_first", "New customers and first orders by period (to last Splio load)", {"sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)", "first_orders": "SUM(first_orders_web)"})},
          [serie("new_customers", "{sales}.new_customers", "New customers", ENT, "new", "line"),
           serie("first_orders", "{sales}.first_orders", "First orders", ENT, "first", "line")], arret="splio", description=D_NOUVEAUX),
    combo("c_new_cost", "New customers and spend by period (to last Splio load)", {"sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)"}), **M},
          [serie("new_customers", "{sales}.new_customers", "New customers", ENT, "new"),
           serie("cost", "{media}.cost", "Spend", EUR, "spend", "line")], arret="splio", description=D_NOUVEAUX),
    # ---- Marchés ------------------------------------------------------------------------------------------------------
    tableau("t_markets", "Performance by market", S_SALES, "market", "market", "Market",
            {"net_revenue_ht": NET_HT, "total_orders": "SUM(orders)", "revenue_ttc": "SUM(revenue_ttc)", "new_customers": f"SUM(IFF({SALES}.date BETWEEN (SELECT comparison_start_splio FROM periods) AND (SELECT comparison_end_splio FROM periods), new_customers_splio, NULL))",
             "first_orders": "SUM(first_orders_web)", "refund_value_ttc": "SUM(refund_value_ttc)"},
            [col("net_revenue_ht", "{t}.net_revenue_ht", "Net revenue", EUR, recent=True), col("total_orders", "{t}.total_orders", "Orders", ENT),
             col("avg_order_value", "{t}.revenue_ttc / NULLIF({t}.total_orders, 0)", "AOV incl. tax", EUR, delta=False), col("new_customers", "{t}.new_customers", "New customers (Splio)", ENT),
             col("first_orders", "{t}.first_orders", "First orders", ENT, delta=False), col("return_rate", "{t}.refund_value_ttc / NULLIF({t}.revenue_ttc, 0)", "Return rate", PCT, delta=False)],
            "net_revenue_ht", filtres=("market",), fin_splio=True,
            mesures_cour={"net_revenue_ht": NET_HT, "total_orders": "SUM(orders)", "revenue_ttc": "SUM(revenue_ttc)",
                          "new_customers": f"SUM(IFF({SALES}.date <= (SELECT last_date FROM last_load), new_customers_splio, NULL))",
                          "first_orders": "SUM(first_orders_web)", "refund_value_ttc": "SUM(refund_value_ttc)"},
            description="Website sales by site version (EN covers countries served in English). No spend by market: Meta runs on a global account since July 2026. New customers stop at the last Splio load." + D_RECENT),
    donut("d_orders_market", "Orders breakdown by market", S_SALES, "market", "market", "SUM(orders)", "total_orders", ENT, couleurs=MARCHES_C),
    empile("e_orders_market", "Orders by period and market", S_SALES, "market", "market", "SUM(orders)", "total_orders", ENT, ("market",), couleurs=MARCHES_C),
    donut("d_revenue_market", "Gross revenue breakdown by market", S_SALES, "market", "market", "SUM(revenue_ttc)", "revenue_ttc", EUR, description="Revenue incl. tax, before returns.", couleurs=MARCHES_C),
    empile("e_revenue_market", "Gross revenue by period and market", S_SALES, "market", "market", "SUM(revenue_ttc)", "revenue_ttc", EUR, ("market",), couleurs=MARCHES_C, description="Revenue incl. tax, before returns."),
    tableau("t_countries", "Performance by shipping country", S_SALES, "country", "country", "Country",
            {"net_revenue_ht": NET_HT, "total_orders": "SUM(orders)", "revenue_ttc": "SUM(revenue_ttc)"},
            [col("net_revenue_ht", "{t}.net_revenue_ht", "Net revenue", EUR, recent=True), col("total_orders", "{t}.total_orders", "Orders", ENT),
             col("avg_order_value", "{t}.revenue_ttc / NULLIF({t}.total_orders, 0)", "AOV incl. tax", EUR)],
            "net_revenue_ht", filtres=("market",), limite=20, description=D_NET),
    # ---- Média et trafic -----------------------------------------------------------------------------------------------
    donut("d_cost_platform", "Spend breakdown by platform", S_MEDIA, PLATEFORME, "platform", "SUM(cost)", "cost", EUR, couleurs=PLATEFORMES),
    empile("e_cost_platform", "Spend by period and platform", S_MEDIA, PLATEFORME, "platform", "SUM(cost)", "cost", EUR, couleurs=PLATEFORMES),
    tableau("t_platforms", "Performance by platform", S_MEDIA, PLATEFORME, "platform", "Platform",
            {"cost": "SUM(cost)", "purchases": "SUM(purchases)", "purchases_value": "SUM(purchases_value)"},
            [col("cost", "{t}.cost", "Spend", EUR), part("cost_share", "cost", "Share of spend"), col("purchases", "{t}.purchases", "Reported purchases", ENT, delta=False),
             col("purchases_value", "{t}.purchases_value", "Reported revenue", EUR), col("declared_roas", "{t}.purchases_value / NULLIF({t}.cost, 0)", "Reported ROAS", DEC),
             col("declared_cpa", "{t}.cost / NULLIF({t}.purchases, 0)", "Reported CPA", EUR, delta=False)],
            "cost", description="Purchases and revenue as reported by each platform, under its own attribution rules. Blended ROAS on the Overview tab uses website sales."),
    donut("d_sessions_channel", "Sessions breakdown by channel", S_TRAFFIC, CANAL, "channel", "SUM(sessions)", "total_sessions", ENT, couleurs=CANAUX_C),
    empile("e_sessions_channel", "Sessions by period and channel", S_TRAFFIC, CANAL, "channel", "SUM(sessions)", "total_sessions", ENT, couleurs=CANAUX_C),
    tableau("t_channels", "Traffic by channel", S_TRAFFIC, CANAL, "channel", "Channel",
            {"total_sessions": "SUM(sessions)", "new_users": "SUM(new_users)", "engaged_sessions": "SUM(engaged_sessions)"},
            [col("total_sessions", "{t}.total_sessions", "Sessions", ENT), part("sessions_share", "total_sessions", "Share of sessions"), col("new_users", "{t}.new_users", "New users", ENT),
             col("engagement_rate", "{t}.engaged_sessions / NULLIF({t}.total_sessions, 0)", "Engagement rate", PCT)],
            "total_sessions", arret="trafic", description="Source: GA4, to the last complete day. Other: sessions GA4 reports without a known medium. GA4 conversions are not configured for Sessùn in Nanga, so there is no conversion rate by channel yet."),
    # ---- Produits -----------------------------------------------------------------------------------------------------
]

PRODUIT_MESURES = {"units_sold": "SUM(units_sold)", "net_revenue_ht": NET_HT, "units_returned": "SUM(units_returned)"}


def colonnes_produit():
    return [col("units_sold", "{t}.units_sold", "Units sold", ENT), col("net_revenue_ht", "{t}.net_revenue_ht", "Net revenue", EUR, recent=True),
            col("return_rate", "{t}.units_returned / NULLIF({t}.units_sold, 0)", "Unit return rate", PCT, delta=False)]


D_PRODUIT = "Website, excluding shipping. Unit return rate: returned units / sold units, for the orders of the period." + D_RECENT
CARTES += [
    tableau("t_types", "Top 10 product types", S_PRODUCTS, TYPE_PRODUIT, "product_type", "Product type", PRODUIT_MESURES, colonnes_produit(), "net_revenue_ht", filtres=FILTRES_PRODUIT, limite=10, description=D_PRODUIT),
    tableau("t_categories", "Top 10 categories", S_PRODUCTS, CATEGORIE, "product_category", "Category", PRODUIT_MESURES, colonnes_produit(), "net_revenue_ht", filtres=FILTRES_PRODUIT, limite=10, description=D_PRODUIT),
    tableau("t_products", "Top 10 products", S_PRODUITS_NOMMES, "product_name", "product_name", "Product", PRODUIT_MESURES, colonnes_produit(), "net_revenue_ht", filtres=FILTRES_PRODUIT, limite=10, description=D_PRODUIT),
    tableau("t_models", "Top 10 models", S_MODELES, "product_family", "product_family", "Model", PRODUIT_MESURES, colonnes_produit(), "net_revenue_ht", filtres=FILTRES_PRODUIT, limite=10, description=D_PRODUIT),
    carte("e_revenue_type", "Gross revenue excl. tax by period and type", "\n".join([
        "WITH " + cte("top_types", "\n".join([f"SELECT {PRODUCTS}.product_type", f"FROM {PRODUCTS}", f"    JOIN utils.calendar ON utils.calendar.date = {PRODUCTS}.date",
                                              clause_where([], ("date",) + FILTRES_PRODUIT), "GROUP BY 1", "ORDER BY SUM(revenue_ht) DESC", "LIMIT 5"])),
        "",
        "SELECT",
        "    {{time_period}} AS time_period,",
        "    COALESCE(top_types.product_type, 'Other') AS product_type,",
        "    SUM(revenue_ht) AS revenue_ht",
        f"FROM {PRODUCTS}",
        f"    JOIN utils.calendar ON utils.calendar.date = {PRODUCTS}.date",
        f"    LEFT JOIN top_types ON top_types.product_type = {PRODUCTS}.product_type",
        clause_where([], ("date",) + FILTRES_PRODUIT),
        "GROUP BY 1, 2",
        "ORDER BY time_period ASC, revenue_ht ASC"]), "bar", viz_empile("product_type", "revenue_ht", EUR, TYPES_C), "Top 5 types of the period, the others grouped. Excl. tax, before returns."),
    tableau("t_declining", "Declining products", S_PRODUITS_NOMMES, "product_name", "product_name", "Product", {"gross_revenue_ht": "SUM(revenue_ht)", "units_sold": "SUM(units_sold)"},
            [col("gross_revenue_ht", "COALESCE({t}.gross_revenue_ht, 0)", "Gross revenue excl. tax", EUR, delta=False), col("revenue_gap", "COALESCE(c.gross_revenue_ht, 0) - p.gross_revenue_ht", "Revenue change", EUR, delta=False),
             col("units_sold", "COALESCE({t}.units_sold, 0)", "Units sold", ENT, delta=False)],
            "revenue_gap", filtres=FILTRES_PRODUIT, total=False, limite=10, ou=["p.gross_revenue_ht > 0"], ordre="revenue_gap ASC", plein=True, description="Top 10 revenue drops against the comparison period, before returns, including products with no sale on the period."),
    tableau("t_returned", "Most returned products", S_PRODUITS_NOMMES, "product_name", "product_name", "Product", PRODUIT_MESURES,
            [col("units_returned", "{t}.units_returned", "Units returned", ENT, delta=False), col("units_sold", "{t}.units_sold", "Units sold", ENT, delta=False),
             col("return_rate", "{t}.units_returned / NULLIF({t}.units_sold, 0)", "Unit return rate", PCT, delta=False)],
            "units_returned", filtres=FILTRES_PRODUIT, total=False, limite=10, description="Ranked by units returned, for the orders of the period." + D_RECENT),
    # ---- Retours ------------------------------------------------------------------------------------------------------
    carte("w_revenue", "From gross to net revenue", "\n".join([
        "WITH " + cte("totals", "\n".join([
            "SELECT", "    SUM(revenue_ttc) AS revenue_ttc,", "    SUM(refund_value_ttc) AS refund_value_ttc,",
            "    SUM(revenue_ttc - revenue_ht) - SUM(refund_value_ttc - refund_value_ht) AS tax",
            f"FROM {SALES}", f"    JOIN utils.calendar ON utils.calendar.date = {SALES}.date", clause_where([], ("date", "market"))])),
        "",
        "SELECT step, amount",
        "FROM (",
        "    SELECT 1 AS step_order, 'Gross revenue' AS step, revenue_ttc AS amount FROM totals",
        "    UNION ALL",
        "    SELECT 2, 'Returns', -refund_value_ttc FROM totals",
        "    UNION ALL",
        "    SELECT 3, 'Tax', -tax FROM totals",
        ")",
        "ORDER BY step_order"]), "waterfall",
          {"graph.dimensions": ["STEP"], "graph.metrics": ["AMOUNT"], "graph.x_axis.scale": "ordinal", "waterfall.show_total": True, "graph.show_values": True,
           "graph.x_axis.labels_enabled": False, "graph.y_axis.labels_enabled": False, "graph.label_value_formatting": "compact", **formats({"amount": sur_graphique(EUR)})}, D_NET),
    combo("c_refunds_rate", "Refunded amount and return rate by order period", {"sales": (dict(S_SALES, filtres=("market",)), {"refund_value_ttc": "SUM(refund_value_ttc)", "revenue_ttc": "SUM(revenue_ttc)"})},
          [serie("refund_value_ttc", "{sales}.refund_value_ttc", "Refunded amount", EUR, "refund", courant="IFF({sales}.time_period > DATEADD(day, -35, CURRENT_DATE), NULL, {sales}.refund_value_ttc)"),
           serie("return_rate", "{sales}.refund_value_ttc / NULLIF({sales}.revenue_ttc, 0)", "Return rate", PCT, "rate", "line", courant="IFF({sales}.time_period > DATEADD(day, -35, CURRENT_DATE), NULL, {sales}.refund_value_ttc / NULLIF({sales}.revenue_ttc, 0))")],
          description="Orders of the last 35 days are not shown: their returns are still coming in."),
    tableau("t_returns", "Returns by market", S_SALES, "market", "market", "Market",
            {"revenue_ttc": "SUM(revenue_ttc)", "refund_value_ttc": "SUM(refund_value_ttc)", "total_refunds": "SUM(refunds)"},
            [col("revenue_ttc", "{t}.revenue_ttc", "Gross revenue", EUR), col("refund_value_ttc", "{t}.refund_value_ttc", "Refunded amount", EUR, recent=True),
             col("total_refunds", "{t}.total_refunds", "Refunds", ENT, recent=True), col("return_rate", "{t}.refund_value_ttc / NULLIF({t}.revenue_ttc, 0)", "Return rate", PCT, recent=True)],
            "revenue_ttc", filtres=("market",), description=D_RETOUR),
    # ---- Boutique -----------------------------------------------------------------------------------------------------
    kpi("retail_revenue", "Retail revenue", {"retail": (S_RETAIL, {"retail_revenue": "SUM(revenue)"})}, "{retail}.retail_revenue", EUR, filtres=("store_id",), arret="boutique", description=D_BOUTIQUE),
    kpi("retail_orders", "Receipts", {"retail": (S_RETAIL, {"retail_orders": "SUM(orders)"})}, "{retail}.retail_orders", ENT, filtres=("store_id",), arret="boutique", description=D_BOUTIQUE),
    kpi("retail_aov", "Retail AOV", {"retail": (S_RETAIL, {"retail_revenue": "SUM(revenue)", "retail_orders": "SUM(orders)"})}, "{retail}.retail_revenue / NULLIF({retail}.retail_orders, 0)", EUR, filtres=("store_id",), arret="boutique", description=D_BOUTIQUE),
    kpi("retail_new_customers", "Retail new customers", {"retail": (S_RETAIL, {"retail_new_customers": "SUM(new_customers)"})}, "{retail}.retail_new_customers", ENT, filtres=("store_id",), arret="boutique", description=D_BOUTIQUE),
    kpi("retail_refund_value", "Retail refunds", {"retail": (S_RETAIL, {"retail_refund_value": "SUM(refund_value)"})}, "{retail}.retail_refund_value", EUR, filtres=("store_id",), arret="boutique", inverse=True, description=D_BOUTIQUE),
    combo("c_retail", "Retail revenue and receipts by period (to last load)", {"retail": (dict(S_RETAIL, filtres=("store_id",)), {"retail_revenue": "SUM(revenue)", "retail_orders": "SUM(orders)"})},
          [serie("retail_revenue", "{retail}.retail_revenue", "Retail revenue", EUR, "net"),
           serie("retail_orders", "{retail}.retail_orders", "Receipts", ENT, "orders", "line")], arret="boutique", description=D_BOUTIQUE),
    tableau("t_stores", "Top 20 stores", S_RETAIL, "store_id", "store_id", "Store",
            {"retail_revenue": "SUM(revenue)", "retail_orders": "SUM(orders)", "retail_new_customers": "SUM(new_customers)", "retail_refund_value": "SUM(refund_value)"},
            [col("retail_revenue", "{t}.retail_revenue", "Revenue", EUR, mini=True), col("retail_orders", "{t}.retail_orders", "Receipts", ENT),
             col("retail_aov", "{t}.retail_revenue / NULLIF({t}.retail_orders, 0)", "AOV", EUR), col("retail_new_customers", "{t}.retail_new_customers", "New customers", ENT),
             col("retail_refund_value", "{t}.retail_refund_value", "Refunded amount", EUR, delta=False)],
            "retail_revenue", filtres=("store_id",), arret="boutique", limite=20, description=D_BOUTIQUE + " Stores shown by code, no store list available yet."),
    # ---- Cohortes et CRM ------------------------------------------------------------------------------------------------
    carte("t_cohorts", "New customer cohorts", f"""
SELECT
    TO_VARCHAR(annee_recrutement) AS recruitment_year,
    INITCAP(origine) AS first_purchase,
    SUM(nb_clients) AS customers,
    SUM(ltv_m3 * nb_clients) / NULLIF(SUM(IFF(ltv_m3 IS NULL, 0, nb_clients)), 0) AS ltv_3_months,
    SUM(ltv_m6 * nb_clients) / NULLIF(SUM(IFF(ltv_m6 IS NULL, 0, nb_clients)), 0) AS ltv_6_months,
    SUM(ltv_m12 * nb_clients) / NULLIF(SUM(IFF(ltv_m12 IS NULL, 0, nb_clients)), 0) AS ltv_12_months,
    SUM(ltv_m24 * nb_clients) / NULLIF(SUM(IFF(ltv_m24 IS NULL, 0, nb_clients)), 0) AS ltv_24_months,
    SUM(repeat_m12 * nb_clients) / NULLIF(SUM(IFF(repeat_m12 IS NULL, 0, nb_clients)), 0) AS orders_12_months
FROM {COHORTS}
GROUP BY 1, 2
ORDER BY 1 DESC, 2""", "table", formats({
        "recruitment_year": {"column_title": "Acquisition year"}, "first_purchase": {"column_title": "First purchase"}, "customers": {**ENT, "column_title": "Customers"},
        "ltv_3_months": {**EUR, "column_title": "LTV at 3 months"}, "ltv_6_months": {**EUR, "column_title": "LTV at 6 months"}, "ltv_12_months": {**EUR, "column_title": "LTV at 12 months"},
        "ltv_24_months": {**EUR, "column_title": "LTV at 24 months"}, "orders_12_months": {**DEC, "column_title": "Orders at 12 months"}}),
          "LTV: average cumulative revenue per customer, incl. tax, net of returns. Web and retail, from Splio, up to one month behind. An empty cell means the cohort has not reached that age yet."),
    carte("d_rfm", "Customers by segment", f"""
SELECT
    {SEGMENT_TABLE} AS rfm_segment,
    SUM(customers) AS customers
FROM {RFM}
GROUP BY 1
ORDER BY 2 DESC""", "pie", {"pie.dimension": ["RFM_SEGMENT"], "pie.metric": "CUSTOMERS", "pie.show_legend": True, "pie.show_legend_perecent": True, "pie.percent_visibility": "legend", "pie.decimal_places": 1, "pie.slice_threshold": 0, "pie.rows": lignes_camembert(SEGMENTS_C), **formats({"customers": ENT})}),
    carte("d_rfm_revenue", "Cumulative net revenue by segment", f"""
SELECT
    {SEGMENT_TABLE} AS rfm_segment,
    SUM(net_revenue) AS net_revenue
FROM {RFM}
GROUP BY 1
ORDER BY 2 DESC""", "pie", {"pie.dimension": ["RFM_SEGMENT"], "pie.metric": "NET_REVENUE", "pie.show_legend": True, "pie.show_legend_perecent": True, "pie.percent_visibility": "legend", "pie.decimal_places": 1, "pie.slice_threshold": 0, "pie.rows": lignes_camembert(SEGMENTS_C), **formats({"net_revenue": EUR})},
          "Incl. tax, net of returns, since each customer's first purchase, as of the last Splio load."),
    carte("t_rfm", "Customer base by RFM segment", f"""
WITH segments AS (
    SELECT
        rfm_segment,
        SUM(customers) AS customers,
        SUM(net_revenue) AS net_revenue
    FROM {RFM}
    GROUP BY 1
)

SELECT
    {SEGMENT} AS rfm_segment,
    CASE segments.rfm_segment
        WHEN 'Champions' THEN 'Under 12 months, 5+ orders or €565+ net'
        WHEN 'Fidèles' THEN 'Under 12 months, 2 to 4 orders'
        WHEN 'Nouveaux' THEN 'Under 12 months, 1 order'
        WHEN 'À risque' THEN '12 to 23 months, 2+ orders'
        WHEN 'À réactiver' THEN '12 to 23 months, 1 order'
        ELSE '24 months or more'
    END AS segment_rule,
    customers,
    customers / SUM(customers) OVER () AS customers_share,
    net_revenue,
    net_revenue / SUM(net_revenue) OVER () AS revenue_share
FROM segments
ORDER BY CASE segments.rfm_segment WHEN 'Champions' THEN 1 WHEN 'Fidèles' THEN 2 WHEN 'Nouveaux' THEN 3 WHEN 'À risque' THEN 4 WHEN 'À réactiver' THEN 5 ELSE 6 END""", "table", formats({
        "rfm_segment": {"column_title": "Segment"}, "segment_rule": {"column_title": "Last purchase and frequency"}, "customers": {**ENT, "column_title": "Customers"},
        "customers_share": {**PCT, "column_title": "Share of customers"}, "net_revenue": {**EUR, "column_title": "Cumulative net revenue incl. tax"}, "revenue_share": {**PCT, "column_title": "Share of revenue"}}), "Since each customer's first purchase, as of the last Splio load."),
]

BASE = ("date", "time_period", "comparison_date")
KPI = 3
# Onglet : filtres posés sur ses tuiles, puis (clé de carte ou titre, ligne, colonne, largeur, hauteur).
ONGLETS = [
    ("Overview", BASE, [
        ("# Overview", 0, 0, 24, 2),
        ("kpi_cost", 2, 0, 4, 2 * KPI),
        ("kpi_total_orders", 2, 4, 4, KPI), ("kpi_blended_cac", 5, 4, 4, KPI),
        ("kpi_new_customers", 2, 8, 4, KPI), ("kpi_blended_ncac", 5, 8, 4, KPI),
        ("kpi_first_orders", 2, 12, 4, KPI), ("kpi_avg_order_value", 5, 12, 4, KPI),
        ("kpi_net_revenue_ht", 2, 16, 4, KPI), ("kpi_blended_roas", 5, 16, 4, KPI),
        ("kpi_revenue_ttc", 2, 20, 4, KPI), ("kpi_return_rate", 5, 20, 4, KPI),
        ("c_orders_revenue", 8, 0, 24, 5),
        ("## Paid investment and sales", 13, 0, 24, 2),
        ("c_roas_revenue", 15, 0, 12, 5), ("c_cac_orders", 15, 12, 12, 5),
        ("c_orders_cost", 20, 0, 12, 5), ("c_revenue_cost", 20, 12, 12, 5),
        ("### Focus on new customers", 25, 0, 24, 1),
        ("c_ncac", 26, 0, 12, 5), ("c_new_vs_first", 26, 12, 12, 5),
        ("c_new_cost", 31, 0, 24, 5),
        ("t_markets", 36, 0, 24, 9),
    ]),
    ("Media & Traffic", BASE, [
        ("# Media", 0, 0, 24, 2),
        ("d_cost_platform", 2, 0, 8, 6), ("e_cost_platform", 2, 8, 16, 6),
        ("t_platforms", 8, 0, 24, 5),
        ("# Traffic", 13, 0, 24, 2),
        ("d_sessions_channel", 15, 0, 8, 6), ("e_sessions_channel", 15, 8, 16, 6),
        ("t_channels", 21, 0, 24, 7),
    ]),
    ("Markets", BASE + ("market",), [
        ("# Performance by market", 0, 0, 24, 2),
        ("d_orders_market", 2, 0, 8, 6), ("e_orders_market", 2, 8, 16, 6),
        ("d_revenue_market", 8, 0, 8, 6), ("e_revenue_market", 8, 8, 16, 6),
        ("t_markets", 14, 0, 24, 9),
        ("# Performance by country", 23, 0, 24, 2),
        ("t_countries", 25, 0, 24, 12),
    ]),
    ("Products", BASE + FILTRES_PRODUIT, [
        ("# Performance by product", 0, 0, 24, 2),
        ("t_types", 2, 0, 12, 9), ("t_categories", 2, 12, 12, 9),
        ("t_products", 11, 0, 12, 9), ("t_models", 11, 12, 12, 9),
        ("e_revenue_type", 20, 0, 24, 6),
        ("# Watch list", 26, 0, 24, 2),
        ("t_declining", 28, 0, 12, 8), ("t_returned", 28, 12, 12, 8),
    ]),
    ("Returns", BASE + ("market",), [
        ("# Returns", 0, 0, 24, 2),
        ("kpi_refund_value_ttc", 2, 0, 6, KPI), ("kpi_total_refunds", 2, 6, 6, KPI), ("kpi_return_rate", 2, 12, 6, KPI), ("kpi_net_revenue_ht", 2, 18, 6, KPI),
        ("w_revenue", 5, 0, 12, 7), ("c_refunds_rate", 5, 12, 12, 7),
        ("t_returns", 12, 0, 24, 9),
    ]),
    ("Retail", BASE + ("store_id",), [
        ("# Retail", 0, 0, 24, 2),
        ("kpi_retail_revenue", 2, 0, 5, KPI), ("kpi_retail_orders", 2, 5, 5, KPI), ("kpi_retail_aov", 2, 10, 4, KPI), ("kpi_retail_new_customers", 2, 14, 5, KPI), ("kpi_retail_refund_value", 2, 19, 5, KPI),
        ("c_retail", 5, 0, 24, 6),
        ("t_stores", 11, 0, 24, 15),
    ]),
    ("Cohorts & CRM", (), [
        ("# Cohorts", 0, 0, 24, 2),
        ("t_cohorts", 2, 0, 24, 14),
        ("# Customer base", 16, 0, 24, 2),
        ("t_rfm", 18, 0, 24, 6),
        ("d_rfm", 24, 0, 12, 6), ("d_rfm_revenue", 24, 12, 12, 6),
    ]),
]

PARAM = {"date": "sessun_date", "time_period": "sessun_time_period", "comparison_date": "sessun_comparison", "market": "sessun_market",
         "product_type": "sessun_product_type", "product_name": "sessun_product_name", "store_id": "sessun_store"}
TITRE_TEXTE = {"text.align_horizontal": "center", "text.align_vertical": "middle", "dashcard.background": False}


# ---- Écriture -------------------------------------------------------------------------------------------------------
def champs(mb):
    """Identifiants des champs : les filtres s'y rattachent. Ils n'existent qu'après la synchro Metabase."""
    def lire(table):
        t = next(x for x in http.get(mb, "/api/database/" + str(DB) + "/schema/CLIENT_DATA") if x["name"].upper() == table)
        return {f["name"].upper(): f["id"] for f in http.get(mb, f"/api/table/{t['id']}/query_metadata")["fields"]}
    return {"ventes": lire("SESSUN__SALES_DAILY_METRICS"), "produits": lire("SESSUN__PRODUCT_DAILY_METRICS"), "boutique": lire("SESSUN__RETAIL_DAILY_METRICS")}


def tags_de(sql, ch):
    tags = {}
    for nom in sorted(set(re.findall(r"\{\{(\w+)\}\}", sql))):
        base = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "sessun/" + nom)), "name": nom, "display-name": nom, "required": False}
        if nom == "time_period":
            tags[nom] = {**base, "type": "temporal-unit", "dimension": ["field", CALENDRIER, None]}
        elif nom in ("date", "comparison_date"):
            tags[nom] = {**base, "type": "dimension", "dimension": ["field", CALENDRIER, None], "widget-type": "date/all-options"}
        else:
            if nom == "market":
                champ = ch["produits" if PRODUCTS in sql else "ventes"]["MARKET"]
            elif nom == "store_id":
                champ = ch["boutique"]["STORE_ID"]
            else:
                champ = ch["produits"][nom.upper()]
            tags[nom] = {**base, "type": "dimension", "dimension": ["field", champ, None], "widget-type": "string/="}
    return tags


def existants(mb):
    items = http.get(mb, f"/api/collection/{COLLECTION}/items?models=card&models=dashboard&limit=500")["data"]
    return {(i["model"], i["name"]): i["id"] for i in items}


def ecrire_cartes(mb):
    titres = [c["titre"] for c in CARTES]
    doublons = {t for t in titres if titres.count(t) > 1}
    if doublons:
        raise ValueError(f"titres de cartes en double : {doublons}")
    ch, deja, ids = champs(mb), existants(mb), {}
    for c in CARTES:
        nom = f"{c['titre']} | Sessùn"
        payload = {"name": nom, "display": c["display"], "visualization_settings": c["viz"], "collection_id": COLLECTION, "description": c["description"],
                   "dataset_query": {"type": "native", "database": DB, "native": {"query": c["sql"], "template-tags": tags_de(c["sql"], ch)}}}
        if ("card", nom) in deja:
            cards.put_card(mb, deja[("card", nom)], payload)
            ids[c["cle"]] = deja[("card", nom)]
        else:
            ids[c["cle"]] = http.post(mb, "/api/card", json=payload)["id"]
    return ids


def ecrire_dashboard(mb, ids):
    params = [
        {"id": PARAM["date"], "name": "Date", "slug": "date", "type": "date/all-options", "sectionId": "date", "default": "past30days"},
        {"id": PARAM["time_period"], "name": "Time period", "slug": "time_period", "type": "temporal-unit", "sectionId": "temporal-unit",
         "temporal_units": ["day", "week", "month", "quarter", "year"], "default": "week"},
        {"id": PARAM["market"], "name": "Market", "slug": "market", "type": "string/=", "sectionId": "string",
         "values_query_type": "list", "values_source_type": "static-list", "values_source_config": {"values": MARCHES}},
        {"id": PARAM["product_type"], "name": "Product type", "slug": "product_type", "type": "string/=", "sectionId": "string"},
        {"id": PARAM["product_name"], "name": "Product", "slug": "product_name", "type": "string/=", "sectionId": "string"},
        {"id": PARAM["store_id"], "name": "Store", "slug": "store_id", "type": "string/=", "sectionId": "string"},
        {"id": PARAM["comparison_date"], "name": "Comparison date", "slug": "comparison_date", "type": "date/all-options", "sectionId": "date", "required": False},
    ]
    par_cle = {c["cle"]: c for c in CARTES}
    did = DASHBOARD
    # Les onglets gardent leur id quand leur nom ne change pas : un lien avec tab= continue de marcher.
    onglets_avant = {t["name"]: t["id"] for t in dashboards.get_dashboard(mb, did).get("tabs", [])}
    tabs, tuiles, dc, neuf = [], [], -1, -1
    for pos, (onglet, filtres, contenu) in enumerate(ONGLETS):
        tab = onglets_avant.get(onglet)
        if tab is None:
            tab, neuf = neuf, neuf - 1
        tabs.append({"id": tab, "name": onglet, "position": pos})
        for quoi, row, col_, sx, sy in contenu:
            base = {"id": dc, "dashboard_tab_id": tab, "row": row, "col": col_, "size_x": sx, "size_y": sy}
            if quoi in par_cle:
                c, cid = par_cle[quoi], ids[quoi]
                reglages = {"card.title": c["titre"], **({"card.description": c["description"]} if c["description"] else {})}
                utiles = [t for t in filtres if "{{%s}}" % t in c["sql"]]
                tuiles.append({**base, "card_id": cid, "visualization_settings": reglages,
                               "parameter_mappings": [{"parameter_id": PARAM[t], "card_id": cid, "target": ["dimension", ["template-tag", t], {"stage-number": 0}]} for t in utiles]})
            else:
                tuiles.append({**base, "card_id": None, "parameter_mappings": [],
                               "visualization_settings": {"virtual_card": {"name": None, "display": "text", "visualization_settings": {}, "dataset_query": {}, "archived": False}, "text": quoi, **TITRE_TEXTE}})
            dc -= 1
    description = "Sessùn media, web sales, retail and CRM. Sources: Nanga for media, Sessùn BigQuery for sales and Splio."
    # Le dashboard est réécrit en entier : la vérification « rien de perdu » de put_dashboard n'a de sens que pour une retouche.
    http.put(mb, f"/api/dashboard/{did}", json={"name": NOM, "description": description, "parameters": params, "tabs": tabs, "dashcards": tuiles, "width": "full"})
    relu = dashboards.get_dashboard(mb, did)
    if len(relu["dashcards"]) != len(tuiles) or len(relu["tabs"]) != len(tabs):
        raise ValueError(f"dashboard {did} : {len(relu['dashcards'])} tuiles relues sur {len(tuiles)}, {len(relu['tabs'])} onglets sur {len(tabs)}")
    return did


# ---- Contrôle -------------------------------------------------------------------------------------------------------
def parametres(periode, unite):
    return [{"id": PARAM["date"], "type": "date/all-options", "value": periode, "target": ["dimension", ["template-tag", "date"], {"stage-number": 0}]},
            {"id": PARAM["time_period"], "type": "temporal-unit", "value": unite, "target": ["dimension", ["template-tag", "time_period"], {"stage-number": 0}]}]


def jouer(mb, did, dc, params):
    r = http.post(mb, f"/api/dashboard/{did}/dashcard/{dc['id']}/card/{dc['card_id']}/query", json={"parameters": params}, timeout=300)
    if r.get("error"):
        return None, str(r["error"])[:300]
    return r["data"], None


def lire_sql(mb, sql):
    r = http.post(mb, "/api/dataset", json={"database": DB, "type": "native", "native": {"query": sql}}, timeout=300)
    if r.get("error"):
        raise ValueError(str(r["error"])[:300])
    return r["data"]["rows"]


def controler_tuiles(mb, did, d, params, libelle):
    """Joue chaque tuile comme le dashboard. Une tuile vide ou en erreur est un échec, pas une note."""
    onglets = {t["id"]: t["name"] for t in d["tabs"]}
    echecs = 0
    for dc in sorted(d["dashcards"], key=lambda x: ([t["id"] for t in d["tabs"]].index(x["dashboard_tab_id"]), x["row"], x["col"])):
        if not dc.get("card_id"):
            continue
        titre = dc["visualization_settings"].get("card.title") or ""
        data, err = jouer(mb, did, dc, params)
        lignes = data["rows"] if data else []
        vide = not lignes or all(v is None for l in lignes for v in l)
        if err or vide:
            echecs += 1
            print(f"  {libelle} {onglets[dc['dashboard_tab_id']][:16]:16} {titre[:48]:48} {'ERREUR ' + err if err else 'VIDE'}")
    print(f"{libelle} : {echecs} tuile(s) en échec sur {sum(1 for x in d['dashcards'] if x.get('card_id'))}")
    return echecs


def controler_coherence(mb, did, d, params):
    """Une tuile peut répondre et être fausse : les chiffres clés, les lignes Total et le SQL direct doivent se recouper."""
    def tuile(titre):
        return next(x for x in d["dashcards"] if x.get("card_id") and x["visualization_settings"].get("card.title") == titre)

    def kpi_lu(titre, rang=-1):
        data, err = jouer(mb, did, tuile(titre), params)
        if err:
            raise ValueError(f"{titre} : {err}")
        return float(data["rows"][rang][1])

    def total_lu(titre, colonne):
        data, err = jouer(mb, did, tuile(titre), params)
        if err:
            raise ValueError(f"{titre} : {err}")
        noms = [c["name"] for c in data["cols"]]
        return float(next(l for l in data["rows"] if "Total" in l)[noms.index(colonne)])

    depenses, ca, commandes, nouveaux = kpi_lu("Spend"), kpi_lu("Net revenue"), kpi_lu("Orders"), kpi_lu("New customers")
    # Le mois de contrôle précède la dernière semaine de Splio : sur janvier à septembre, aucune borne n'intervient.
    precedent = lire_sql(mb, f"SELECT SUM(orders) FROM {SALES} WHERE date BETWEEN DATEADD(day, -273, '2026-01-01'::DATE) AND '2025-12-31'::DATE")[0][0]
    attendus = [("Blended ROAS", kpi_lu("Blended ROAS"), ca / depenses), ("Blended CAC", kpi_lu("Cost per order"), depenses / commandes),
                ("New customer CAC", kpi_lu("New customer CAC"), depenses / nouveaux),
                ("Total marchés CA", total_lu("Performance by market", "NET_REVENUE_HT"), ca), ("Total marchés commandes", total_lu("Performance by market", "TOTAL_ORDERS"), commandes),
                ("Total plateformes", total_lu("Performance by platform", "COST"), depenses), ("Total retours", total_lu("Returns by market", "REFUND_VALUE_TTC"), kpi_lu("Refunded amount")),
                ("Total magasins", total_lu("Top 20 stores", "RETAIL_REVENUE"), kpi_lu("Retail revenue")),
                ("Commandes période précédente", kpi_lu("Orders", 0), float(precedent))]
    ecarts = 0
    for nom, lu, attendu in attendus:
        ok = abs(lu - attendu) <= 0.001 * abs(attendu)
        ecarts += 0 if ok else 1
        print(f"  cohérence {nom}: {lu:.2f} pour {attendu:.2f} attendu {'OK' if ok else 'KO'}")
    return ecarts


def controler_arret(mb, did, d):
    """Sur la période par défaut, Splio ne couvre qu'une partie des jours : les deux lignes doivent porter sur la même durée."""
    dc = next(x for x in d["dashcards"] if x.get("card_id") and x["visualization_settings"].get("card.title") == "New customers")
    data, err = jouer(mb, did, dc, parametres("past30days", "week"))
    if err:
        print("  arrêt Splio : ERREUR", err)
        return 1
    avant, apres = data["rows"]
    attendu = lire_sql(mb, f"""
WITH b AS (
    SELECT DATEADD(day, -30, CURRENT_DATE) AS debut, (SELECT DATEADD(day, -1, MAX(date)) FROM {SALES} WHERE new_customers_splio IS NOT NULL) AS fin
)
SELECT
    (SELECT SUM(new_customers_splio) FROM {SALES}, b WHERE date BETWEEN DATEADD(day, -(DATEDIFF(day, debut, fin) + 1), debut) AND DATEADD(day, -1, debut)),
    (SELECT SUM(new_customers_splio) FROM {SALES}, b WHERE date BETWEEN debut AND fin)
FROM b""")[0]
    ok = float(avant[1]) == float(attendu[0]) and float(apres[1]) == float(attendu[1])
    print(f"  arrêt Splio : {avant[0][:10]} {avant[1]} puis {apres[0][:10]} {apres[1]}, attendu {attendu[0]} puis {attendu[1]} {'OK' if ok else 'KO'}")
    net = next(x for x in d["dashcards"] if x.get("card_id") and x["visualization_settings"].get("card.title") == "Net revenue")
    lignes = jouer(mb, did, net, parametres("past30days", "week"))[0]["rows"]
    recent_ok = lignes[0][1] is None and lignes[1][1] is not None
    print(f"  pas d'évolution sous 35 jours : {lignes[0][1]} puis {lignes[1][1]} {'OK' if recent_ok else 'KO'}")
    return (0 if ok else 1) + (0 if recent_ok else 1)


def controler(mb, did):
    d = dashboards.get_dashboard(mb, did)
    long_terme = parametres("2026-01-01~2026-09-30", "month")
    defaut = parametres("past30days", "week")
    return (controler_tuiles(mb, did, d, long_terme, "janvier à septembre") + controler_tuiles(mb, did, d, defaut, "30 derniers jours")
            + controler_coherence(mb, did, d, long_terme) + controler_arret(mb, did, d))


def principal():
    mb = connect()
    if len(sys.argv) > 1 and sys.argv[1] == "controle":
        did = DASHBOARD
    else:
        ids = ecrire_cartes(mb)
        print(len(ids), "cartes écrites")
        did = ecrire_dashboard(mb, ids)
    print("dashboard", did, f"{mb.domain}/dashboard/{did}")
    return 1 if controler(mb, did) else 0


if __name__ == "__main__":
    sys.exit(principal())
