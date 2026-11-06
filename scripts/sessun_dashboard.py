# -*- coding: utf-8 -*-
"""Campagne : dashboard « Média et ventes | Sessùn », sur le modèle de « Shopify | Polène » (16427).

Rejouable : une carte ou un dashboard déjà présent dans la collection Sessùn est mis à jour, jamais dupliqué.

    .venv/bin/python scripts/sessun_dashboard.py          # crée ou met à jour, puis contrôle
    .venv/bin/python scripts/sessun_dashboard.py controle # contrôle seulement

Même forme de requêtes que Polène : les dates passent par utils.calendar, donc un seul {{date}} filtre ventes et dépenses
dans la même carte ; {{time_period}} règle la granularité, {{comparison_date}} la période de comparaison (vide : les N jours
d'avant). Sources : GLOBAL.CAMPAIGN_DAILY_METRICS pour le média, ANALYTICS.GOOGLE__ANALYTICS_METRICS pour le trafic,
CLIENT_DATA.SESSUN__* pour le reste. Les tables restent sans alias : Metabase écrit "SCHEMA"."TABLE"."COLONNE".

Décisions de Louis du 06/11/2026 : nouveaux clients Splio arrêtés au dernier chargement, sur deux périodes de même durée ;
ROAS sur le CA HT net de retours ; filtre Marché hors de la Vue d'ensemble (les dépenses ne se répartissent pas par marché).
"""
import json
import re
import sys
import textwrap
import uuid

from spark_metabase_api import cards, connect, dashboards, http

DB = 144
COLLECTION = 15237
NOM = "Média et ventes | Sessùn"
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

# Palette de Polène.
VENTES_C, VENTES_P = "#FC926D", "#FDC1AB"
COMMANDES_C, COMMANDES_P = "#6896E9", "#A0BDF1"
DEPENSES_C, DEPENSES_P = "#F7C41F", "#FDC1AB"
ORANGE_C = "#ED8535"
BLEU_C = "#227FD2"
LIGNE_C, LIGNE_P = "#6896E9", "#A0BDF1"
PLATEFORMES = {"Meta": "#6896E9", "Google": "#F8E26F", "TikTok": "#EAB1E1", "Pinterest": "#E66775"}
MARCHES_C = {"FR": "#6896E9", "DE": "#FC926D", "EN": "#88BF4D", "ES": "#F7C41F", "GB": "#A989C5", "NL": "#51B8A6", "US": "#E66775", "IT": "#EAB1E1", "CH": "#8C9BAE"}
CANAUX_C = {"Social payant": "#E66775", "Search payant": "#FC926D", "Autres": "#6896E9", "Organique": "#F7C41F", "Sites référents": "#A989C5", "Assistants IA": "#EAB1E1", "Autre payant": "#51B8A6"}


def source(table, *portee):
    return {"table": table, "portee": list(portee)}


S_SALES = source(SALES)
S_MEDIA = source(MEDIA, f"{MEDIA}.client_id = '{CLIENT}' -- Sessùn")
S_TRAFFIC = source(TRAFFIC, f"{TRAFFIC}.client_id = '{CLIENT}' -- Sessùn")
S_PRODUCTS = source(PRODUCTS)
S_RETAIL = source(RETAIL)

# Splio et les tickets boutique sont chargés à la main, jusqu'à un mois de retard.
CHARGEMENTS = {
    "splio": f"SELECT MAX(date) AS last_date\nFROM {SALES}\nWHERE new_customers_splio IS NOT NULL",
    "boutique": f"SELECT MAX(date) AS last_date\nFROM {RETAIL}",
}


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
        colonnes.append(f"DATEADD(day, DATEDIFF(day, cur.start_date, LEAST(cur.end_date, (SELECT last_date FROM last_load))), {debut_cmp}) AS comparison_end_splio")
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


def kpi(colonne, titre, sources, valeur, f, filtres=(), arret=None, inverse=False, description=None):
    """Tuile tendance : deux lignes (comparaison puis période), comme Polène. sources : {alias: (source, {colonne: expression})}."""
    ctes = debut_periodes(arret)
    for alias, (s, colonnes) in sources.items():
        ctes.append(cte(f"current_{alias}", lecture_courante(s, colonnes, filtres, arret=arret)))
        ctes.append(cte(f"previous_{alias}", lecture_precedente(s, colonnes, filtres)))
    courant = valeur.format(**{a: f"current_{a}" for a in sources})
    precedent = valeur.format(**{a: f"previous_{a}" for a in sources})
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


def serie(colonne, expr, titre, f, couleur, couleur_p, display="bar"):
    return {"colonne": colonne, "expr": expr, "titre": titre, "f": f, "couleur": couleur, "couleur_p": couleur_p, "display": display}


def combo(cle, titre, sources, series, arret=None, description=None):
    """Période en cours contre période précédente, recalée sur les mêmes tranches, comme Polène."""
    ctes = [cte("last_load", CHARGEMENTS[arret])] if arret else []
    ctes.append(cte("date_range", "SELECT\n    MIN(date) AS min_date,\n    MAX(date) AS max_date,\n    MAX(date) - MIN(date) + 1 AS days\nFROM utils.calendar\nWHERE TRUE\n    " + tag("date")))
    borne = ["utils.calendar.date <= (SELECT last_date FROM last_load)"] if arret else []
    for alias, (s, colonnes) in sources.items():
        t = s["table"]
        dims = ["{{time_period}} AS time_period"]
        ctes.append(cte(f"current_{alias}", "\n".join([
            clause_select(dims, colonnes), f"FROM {t}", f"    JOIN utils.calendar ON utils.calendar.date = {t}.date",
            clause_where(s["portee"] + borne, ("date",) + tuple(s.get("filtres", ()))),
            "GROUP BY 1"])))
        ctes.append(cte(f"previous_{alias}", "\n".join([
            clause_select(dims, colonnes), f"FROM {t}", "    JOIN date_range ON TRUE",
            f"    JOIN utils.calendar ON utils.calendar.date = DATEADD('day', date_range.days, {t}.date)",
            clause_where(s["portee"] + [f"{t}.date >= DATEADD('day', -date_range.days, date_range.min_date)", f"{t}.date < date_range.min_date"] + borne, tuple(s.get("filtres", ()))),
            "GROUP BY 1"])))
    pilote = next(iter(sources))
    courants = {a: f"current_{a}" for a in sources}
    precedents = {a: f"previous_{a}" for a in sources}
    lignes = [f"current_{pilote}.time_period"]
    for x in series:
        lignes += [f"{x['expr'].format(**courants)} AS current_{x['colonne']}", f"{x['expr'].format(**precedents)} AS previous_{x['colonne']}"]
    jointures = [f"current_{a}" for a in sources if a != pilote] + [f"previous_{a}" for a in sources]
    sql = "WITH " + ",\n\n".join(ctes) + "\n\nSELECT\n" + ",\n".join("    " + l for l in lignes) + f"\nFROM current_{pilote}\n" + "".join(
        f"    LEFT JOIN {j} ON {j}.time_period = current_{pilote}.time_period\n" for j in jointures) + "ORDER BY 1"
    reglages, metriques, formes = {}, [], {}
    for x in series:
        cur, prev = f"CURRENT_{x['colonne'].upper()}", f"PREVIOUS_{x['colonne'].upper()}"
        metriques += [cur, prev]
        formes.update({f"current_{x['colonne']}": sur_graphique(x["f"]), f"previous_{x['colonne']}": sur_graphique(x["f"])})
        trait = {"line.interpolate": "cardinal"} if x["display"] in ("area", "line") else {}
        reglages[cur] = {"title": x["titre"], "color": x["couleur"], "display": x["display"], **trait}
        reglages[prev] = {"title": x["titre"] + " (P-1)", "color": x["couleur_p"], "display": x["display"], **trait,
                          **({"line.style": "dashed"} if x["display"] in ("area", "line") else {})}
    viz = {"graph.dimensions": ["TIME_PERIOD"], "graph.metrics": metriques, "series_settings": reglages, "graph.x_axis.scale": "timeseries",
           "graph.x_axis.axis_enabled": "compact", "graph.x_axis.labels_enabled": False, "graph.y_axis.labels_enabled": False, "graph.show_values": True,
           "graph.label_value_frequency": "fit", "graph.label_value_formatting": "compact", **formats(formes)}
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


def col(alias, expr, titre, f, delta=True, mini=False):
    return {"alias": alias, "expr": expr, "titre": titre, "f": f, "delta": delta, "mini": mini}


def part(alias, mesure, titre):
    """Part dans le total des lignes, calculée avant la coupe du top N."""
    return col(alias, f"c.{mesure} / NULLIF(SUM(IFF(c.rank = 2, c.{mesure}, 0)) OVER (), 0)", titre, PCT, delta=False)


def tableau(cle, titre, s, dim, alias, titre_dim, mesures, colonnes, tri, filtres=(), arret=None, fin_splio=False, mesures_prec=None,
            total=True, limite=None, ou=(), ordre=None, description=None):
    """Tableau avec ligne Total et Δ contre la période de comparaison, comme Polène."""
    noms = list(mesures)
    ctes = debut_periodes(arret, fin_splio)
    dims = [f"{dim} AS {alias}"]
    ctes.append(cte("current_data", lecture_courante(s, mesures, filtres, dims, arret)))
    ctes.append(cte("previous_data", lecture_precedente(s, mesures_prec or mesures, filtres, dims)))
    if total:
        liste = ", ".join([alias] + noms)
        sommes = ", ".join(f"SUM({n}) AS {n}" for n in noms)
        for periode in ("current", "previous"):
            ctes.append(cte(f"{periode}_final", f"SELECT 2 AS rank, {liste}\nFROM {periode}_data\nUNION ALL\nSELECT 1 AS rank, 'Total' AS {alias}, {sommes}\nFROM {periode}_data"))
    gauche, droite = ("current_final", "previous_final") if total else ("current_data", "previous_data")
    lignes = (["c.rank AS rank"] if total else []) + [f"c.{alias} AS {alias}"]
    affichees, reglages = ([{"name": "RANK", "enabled": False}] if total else []) + [{"name": alias.upper(), "enabled": True}], {alias: {"column_title": titre_dim}}
    for x in colonnes:
        lignes.append(f"{x['expr'].format(t='c')} AS {x['alias']}")
        affichees.append({"name": x["alias"].upper(), "enabled": True})
        reglages[x["alias"]] = {**x["f"], "column_title": x["titre"], **({"show_mini_bar": True} if x["mini"] else {})}
        if x["delta"]:
            lignes.append(f"({x['expr'].format(t='c')} - {x['expr'].format(t='p')}) / NULLIF(ABS({x['expr'].format(t='p')}), 0) AS delta_{x['alias']}")
            affichees.append({"name": f"DELTA_{x['alias'].upper()}", "enabled": True})
            reglages[f"delta_{x['alias']}"] = {**PCT, "column_title": "Δ " + x["titre"], **({"show_mini_bar": True} if x["mini"] else {})}
    conditions = [f"c.{alias} IS NOT NULL"] + list(ou)
    sql = "WITH " + ",\n\n".join(ctes) + "\n\nSELECT\n" + ",\n".join("    " + l for l in lignes) + f"\nFROM {gauche} AS c\n"
    sql += f"    LEFT JOIN {droite} AS p ON p.{alias} = c.{alias}" + (" AND p.rank = c.rank" if total else "") + "\n"
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
        WHEN LOWER(medium) = 'paid' AND LOWER(source) IN ('meta', 'tiktok', 'pinterest', 'snapchat') THEN 'Social payant'
        WHEN LOWER(medium) = 'paid' AND LOWER(source) IN ('google', 'microsoft') THEN 'Search payant'
        WHEN LOWER(medium) = 'paid' THEN 'Autre payant'
        WHEN LOWER(medium) = 'organic' THEN 'Organique'
        WHEN LOWER(medium) = 'referral' THEN 'Sites référents'
        WHEN LOWER(medium) = 'ia' THEN 'Assistants IA'
        ELSE 'Autres'
    END"""
PLATEFORME = "CASE WHEN LOWER(campaign_channel) = 'tiktok' THEN 'TikTok' ELSE INITCAP(campaign_channel) END"
TYPE_PRODUIT = "COALESCE(product_type, 'Non renseigné')"
CATEGORIE = "INITCAP(REPLACE(REGEXP_REPLACE(product_category, '[0-9]+$', ''), '-', ' '))"
FILTRES_PRODUIT = ("market", "product_type", "product_name")
S_PRODUITS_NOMMES = source(PRODUCTS, f"{PRODUCTS}.product_name <> 'unknown'")
S_MODELES = source(PRODUCTS, f"{PRODUCTS}.product_family IS NOT NULL")

D_NOUVEAUX = "Première commande tous canaux d'après Splio : un client déjà venu en boutique ne compte pas. S'arrête au dernier chargement de Splio, et la comparaison porte sur la même durée."
D_PREMIERES = "Première commande vue sur le site, à jour chaque jour. Compte aussi des clients déjà venus en boutique, donc plus haut que les nouveaux clients Splio."
D_NET = "Ventes du site, moins la TVA et les retours, frais de port inclus. Un remboursement compte à sa propre date."
D_RETOUR = "Montant remboursé / CA TTC de la période. Un remboursement compte à sa propre date, donc le taux monte après les pics de commandes de janvier et de juillet."
D_P1 = "P-1 : les mêmes jours sur la période juste avant."
D_BOUTIQUE = "Tickets Splio, montants tels que chargés, TVA non disponible. S'arrête au dernier chargement, et la comparaison porte sur la même durée."

V = {"sales": (S_SALES, {"net_revenue_ht": NET_HT})}
M = {"media": (S_MEDIA, {"cost": "SUM(cost)"})}

CARTES = [
    # ---- Chiffres clés ------------------------------------------------------------------------------------------------
    kpi("cost", "Dépenses", M, "{media}.cost", EUR, description="Coût média de toutes les plateformes : Meta, Google, TikTok, Pinterest."),
    kpi("total_orders", "Commandes", {"sales": (S_SALES, {"total_orders": "SUM(orders)"})}, "{sales}.total_orders", ENT, description="Commandes du site web."),
    kpi("blended_cac", "Coût / commande", {**M, "sales": (S_SALES, {"total_orders": "SUM(orders)"})}, "{media}.cost / NULLIF({sales}.total_orders, 0)", EUR, inverse=True, description="Dépenses / commandes du site."),
    kpi("new_customers", "Nouveaux clients", {"sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)"})}, "{sales}.new_customers", ENT, arret="splio", description=D_NOUVEAUX),
    kpi("blended_ncac", "Coût / nv client", {**M, "sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)"})}, "{media}.cost / NULLIF({sales}.new_customers, 0)", EUR, arret="splio", inverse=True, description="Dépenses / nouveaux clients Splio, sur les jours couverts par le dernier chargement."),
    kpi("first_orders", "1res commandes", {"sales": (S_SALES, {"first_orders": "SUM(first_orders_web)"})}, "{sales}.first_orders", ENT, description=D_PREMIERES),
    kpi("avg_order_value", "Panier moyen TTC", {"sales": (S_SALES, {"revenue_ttc": "SUM(revenue_ttc)", "total_orders": "SUM(orders)"})}, "{sales}.revenue_ttc / NULLIF({sales}.total_orders, 0)", EUR, description="CA TTC avant retours / commandes."),
    kpi("net_revenue_ht", "CA HT net", V, "{sales}.net_revenue_ht", EUR, filtres=("market",), description=D_NET),
    kpi("blended_roas", "ROAS global", {**V, **M}, "{sales}.net_revenue_ht / NULLIF({media}.cost, 0)", DEC, description="CA HT net / dépenses."),
    kpi("revenue_ttc", "CA TTC brut", {"sales": (S_SALES, {"revenue_ttc": "SUM(revenue_ttc)"})}, "{sales}.revenue_ttc", EUR, description="Ventes du site, TVA et frais de port inclus, avant retours."),
    kpi("return_rate", "Taux de retour", {"sales": (S_SALES, {"refund_value_ttc": "SUM(refund_value_ttc)", "revenue_ttc": "SUM(revenue_ttc)"})}, "{sales}.refund_value_ttc / NULLIF({sales}.revenue_ttc, 0)", PCT, filtres=("market",), inverse=True, description=D_RETOUR),
    kpi("refund_value_ttc", "Montant remboursé", {"sales": (S_SALES, {"refund_value_ttc": "SUM(refund_value_ttc)"})}, "{sales}.refund_value_ttc", EUR, filtres=("market",), inverse=True, description="Remboursements TTC du site, à leur propre date."),
    kpi("total_refunds", "Remboursements", {"sales": (S_SALES, {"total_refunds": "SUM(refunds)"})}, "{sales}.total_refunds", ENT, filtres=("market",), inverse=True, description="Nombre de remboursements du site, à leur propre date."),
    # ---- Vue d'ensemble : évolutions --------------------------------------------------------------------------------------
    combo("c_orders_revenue", "Commandes et CA HT net par période", {"sales": (S_SALES, {"net_revenue_ht": NET_HT, "total_orders": "SUM(orders)"})},
          [serie("net_revenue_ht", "{sales}.net_revenue_ht", "CA HT net", EUR, VENTES_C, VENTES_P, "area"),
           serie("total_orders", "{sales}.total_orders", "Commandes", ENT, COMMANDES_C, COMMANDES_P)], description=D_P1),
    combo("c_roas_revenue", "ROAS global et CA HT net par période", {**V, **M},
          [serie("net_revenue_ht", "{sales}.net_revenue_ht", "CA HT net", EUR, ORANGE_C, VENTES_P),
           serie("blended_roas", "{sales}.net_revenue_ht / NULLIF({media}.cost, 0)", "ROAS global", DEC, LIGNE_C, LIGNE_P, "line")], description=D_P1),
    combo("c_cac_orders", "Coût par commande et commandes par période", {"sales": (S_SALES, {"total_orders": "SUM(orders)"}), **M},
          [serie("total_orders", "{sales}.total_orders", "Commandes", ENT, COMMANDES_C, COMMANDES_P),
           serie("blended_cac", "{media}.cost / NULLIF({sales}.total_orders, 0)", "Coût par commande", EUR, ORANGE_C, VENTES_P, "line")], description=D_P1),
    combo("c_orders_cost", "Commandes et dépenses par période", {"sales": (S_SALES, {"total_orders": "SUM(orders)"}), **M},
          [serie("total_orders", "{sales}.total_orders", "Commandes", ENT, BLEU_C, COMMANDES_P),
           serie("cost", "{media}.cost", "Dépenses", EUR, DEPENSES_C, DEPENSES_P, "area")], description=D_P1),
    combo("c_revenue_cost", "CA HT net et dépenses par période", {**V, **M},
          [serie("net_revenue_ht", "{sales}.net_revenue_ht", "CA HT net", EUR, ORANGE_C, VENTES_P),
           serie("cost", "{media}.cost", "Dépenses", EUR, LIGNE_C, LIGNE_P, "area")], description=D_P1),
    combo("c_ncac", "Coût par nouveau client par période", {"sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)"}), **M},
          [serie("blended_ncac", "{media}.cost / NULLIF({sales}.new_customers, 0)", "Coût par nouveau client", EUR, ORANGE_C, VENTES_P, "line")], arret="splio", description=D_NOUVEAUX),
    combo("c_new_vs_first", "Nouveaux clients et premières commandes site par période", {"sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)", "first_orders": "SUM(first_orders_web)"})},
          [serie("new_customers", "{sales}.new_customers", "Nouveaux clients", ENT, LIGNE_C, LIGNE_P, "line"),
           serie("first_orders", "{sales}.first_orders", "Premières commandes site", ENT, ORANGE_C, VENTES_P, "line")], arret="splio", description=D_NOUVEAUX),
    combo("c_new_cost", "Nouveaux clients et dépenses par période", {"sales": (S_SALES, {"new_customers": "SUM(new_customers_splio)"}), **M},
          [serie("new_customers", "{sales}.new_customers", "Nouveaux clients", ENT, BLEU_C, COMMANDES_P),
           serie("cost", "{media}.cost", "Dépenses", EUR, DEPENSES_C, DEPENSES_P, "line")], arret="splio", description=D_NOUVEAUX),
    # ---- Marchés ------------------------------------------------------------------------------------------------------
    tableau("t_markets", "Performances par marché", S_SALES, "market", "market", "Marché",
            {"net_revenue_ht": NET_HT, "total_orders": "SUM(orders)", "revenue_ttc": "SUM(revenue_ttc)", "new_customers": "SUM(new_customers_splio)",
             "first_orders": "SUM(first_orders_web)", "refund_value_ttc": "SUM(refund_value_ttc)"},
            [col("net_revenue_ht", "{t}.net_revenue_ht", "CA HT net", EUR), col("total_orders", "{t}.total_orders", "Commandes", ENT),
             col("avg_order_value", "{t}.revenue_ttc / NULLIF({t}.total_orders, 0)", "Panier moyen TTC", EUR), col("new_customers", "{t}.new_customers", "Nouveaux clients", ENT),
             col("first_orders", "{t}.first_orders", "Premières commandes site", ENT), col("return_rate", "{t}.refund_value_ttc / NULLIF({t}.revenue_ttc, 0)", "Taux de retour", PCT)],
            "net_revenue_ht", filtres=("market",), fin_splio=True,
            mesures_prec={"net_revenue_ht": NET_HT, "total_orders": "SUM(orders)", "revenue_ttc": "SUM(revenue_ttc)",
                          "new_customers": f"SUM(IFF({SALES}.date <= (SELECT comparison_end_splio FROM periods), new_customers_splio, NULL))",
                          "first_orders": "SUM(first_orders_web)", "refund_value_ttc": "SUM(refund_value_ttc)"},
            description="Ventes du site par version du site (EN regroupe les pays servis en anglais). Pas de dépenses par marché : Meta passe par un compte global depuis juillet 2026. Nouveaux clients comparés sur la même durée, jusqu'au dernier chargement de Splio."),
    donut("d_orders_market", "Répartition des commandes par marché", S_SALES, "market", "market", "SUM(orders)", "total_orders", ENT, ("market",), couleurs=MARCHES_C),
    empile("e_orders_market", "Commandes par période et par marché", S_SALES, "market", "market", "SUM(orders)", "total_orders", ENT, ("market",), couleurs=MARCHES_C),
    donut("d_revenue_market", "Répartition du CA TTC par marché", S_SALES, "market", "market", "SUM(revenue_ttc)", "revenue_ttc", EUR, ("market",), "CA TTC avant retours.", couleurs=MARCHES_C),
    empile("e_revenue_market", "CA TTC par période et par marché", S_SALES, "market", "market", "SUM(revenue_ttc)", "revenue_ttc", EUR, ("market",), couleurs=MARCHES_C, description="CA TTC avant retours."),
    tableau("t_countries", "Performances par pays de livraison", S_SALES, "country", "country", "Pays",
            {"net_revenue_ht": NET_HT, "total_orders": "SUM(orders)", "revenue_ttc": "SUM(revenue_ttc)"},
            [col("net_revenue_ht", "{t}.net_revenue_ht", "CA HT net", EUR), col("total_orders", "{t}.total_orders", "Commandes", ENT),
             col("avg_order_value", "{t}.revenue_ttc / NULLIF({t}.total_orders, 0)", "Panier moyen TTC", EUR)],
            "net_revenue_ht", filtres=("market",), limite=20),
    # ---- Média et trafic -----------------------------------------------------------------------------------------------
    donut("d_cost_platform", "Répartition des dépenses par plateforme", S_MEDIA, PLATEFORME, "platform", "SUM(cost)", "cost", EUR, couleurs=PLATEFORMES),
    empile("e_cost_platform", "Dépenses par période et par plateforme", S_MEDIA, PLATEFORME, "platform", "SUM(cost)", "cost", EUR, couleurs=PLATEFORMES),
    tableau("t_platforms", "Performances par plateforme", S_MEDIA, PLATEFORME, "platform", "Plateforme",
            {"cost": "SUM(cost)", "purchases": "SUM(purchases)", "purchases_value": "SUM(purchases_value)"},
            [col("cost", "{t}.cost", "Dépenses", EUR), part("cost_share", "cost", "Part des dépenses"), col("purchases", "{t}.purchases", "Achats déclarés", ENT),
             col("purchases_value", "{t}.purchases_value", "CA déclaré", EUR), col("declared_roas", "{t}.purchases_value / NULLIF({t}.cost, 0)", "ROAS déclaré", DEC),
             col("declared_cpa", "{t}.cost / NULLIF({t}.purchases, 0)", "Coût par achat déclaré", EUR)],
            "cost", description="Achats et CA tels que déclarés par chaque plateforme, selon ses propres règles d'attribution. Le ROAS global de la Vue d'ensemble se calcule sur les ventes du site."),
    donut("d_sessions_channel", "Répartition des sessions par canal", S_TRAFFIC, CANAL, "channel", "SUM(sessions)", "total_sessions", ENT, couleurs=CANAUX_C),
    empile("e_sessions_channel", "Sessions par période et par canal", S_TRAFFIC, CANAL, "channel", "SUM(sessions)", "total_sessions", ENT, couleurs=CANAUX_C),
    tableau("t_channels", "Trafic par canal", S_TRAFFIC, CANAL, "channel", "Canal",
            {"total_sessions": "SUM(sessions)", "new_users": "SUM(new_users)", "engaged_sessions": "SUM(engaged_sessions)"},
            [col("total_sessions", "{t}.total_sessions", "Sessions", ENT), part("sessions_share", "total_sessions", "Part des sessions"), col("new_users", "{t}.new_users", "Nouveaux visiteurs", ENT),
             col("engagement_rate", "{t}.engaged_sessions / NULLIF({t}.total_sessions, 0)", "Taux d'engagement", PCT)],
            "total_sessions", description="Source GA4. Les conversions GA4 ne sont pas configurées pour Sessùn dans Nanga : pas de taux de conversion par canal pour l'instant."),
    # ---- Produits -----------------------------------------------------------------------------------------------------
]

PRODUIT_MESURES = {"units_sold": "SUM(units_sold)", "net_revenue_ht": NET_HT, "units_returned": "SUM(units_returned)"}


def colonnes_produit():
    return [col("units_sold", "{t}.units_sold", "Articles vendus", ENT, mini=True), col("net_revenue_ht", "{t}.net_revenue_ht", "CA HT net", EUR, mini=True),
            part("revenue_share", "net_revenue_ht", "Part du CA"), col("return_rate", "{t}.units_returned / NULLIF({t}.units_sold, 0)", "Taux de retour", PCT)]


D_PRODUIT = "Site web, hors frais de port. Le taux de retour compare les articles retournés aux articles vendus sur la période."
CARTES += [
    tableau("t_types", "Top types de produit (vs P-1)", S_PRODUCTS, TYPE_PRODUIT, "product_type", "Type de produit", PRODUIT_MESURES, colonnes_produit(), "net_revenue_ht", filtres=FILTRES_PRODUIT, description=D_PRODUIT),
    tableau("t_categories", "Top catégories (vs P-1)", S_PRODUCTS, CATEGORIE, "product_category", "Catégorie", PRODUIT_MESURES, colonnes_produit(), "net_revenue_ht", filtres=FILTRES_PRODUIT, description=D_PRODUIT),
    tableau("t_products", "Top 10 des produits (vs P-1)", S_PRODUITS_NOMMES, "product_name", "product_name", "Produit", PRODUIT_MESURES, colonnes_produit(), "net_revenue_ht", filtres=FILTRES_PRODUIT, limite=10, description=D_PRODUIT),
    tableau("t_models", "Top 10 des modèles (vs P-1)", S_MODELES, "product_family", "product_family", "Modèle", PRODUIT_MESURES, colonnes_produit(), "net_revenue_ht", filtres=FILTRES_PRODUIT, limite=10, description=D_PRODUIT),
    carte("e_revenue_type", "CA HT avant retours par période et par type", "\n".join([
        "WITH " + cte("top_types", "\n".join([f"SELECT {PRODUCTS}.product_type", f"FROM {PRODUCTS}", f"    JOIN utils.calendar ON utils.calendar.date = {PRODUCTS}.date",
                                              clause_where([], ("date",) + FILTRES_PRODUIT), "GROUP BY 1", "ORDER BY SUM(revenue_ht) DESC", "LIMIT 8"])),
        "",
        "SELECT",
        "    {{time_period}} AS time_period,",
        "    COALESCE(top_types.product_type, 'Autres') AS product_type,",
        "    SUM(revenue_ht) AS revenue_ht",
        f"FROM {PRODUCTS}",
        f"    JOIN utils.calendar ON utils.calendar.date = {PRODUCTS}.date",
        f"    LEFT JOIN top_types ON top_types.product_type = {PRODUCTS}.product_type",
        clause_where([], ("date",) + FILTRES_PRODUIT),
        "GROUP BY 1, 2",
        "ORDER BY time_period ASC, revenue_ht ASC"]), "bar", viz_empile("product_type", "revenue_ht", EUR), "Les 8 premiers types de la période, les autres regroupés. Avant retours : un retour compte à sa propre date et ferait passer certaines barres sous zéro."),
    tableau("t_declining", "Produits en baisse", S_PRODUITS_NOMMES, "product_name", "product_name", "Produit", PRODUIT_MESURES,
            [col("net_revenue_ht", "{t}.net_revenue_ht", "CA HT net", EUR), col("revenue_gap", "c.net_revenue_ht - p.net_revenue_ht", "Écart de CA", EUR, delta=False), col("units_sold", "{t}.units_sold", "Articles vendus", ENT)],
            "revenue_gap", filtres=FILTRES_PRODUIT, total=False, limite=10, ou=["p.net_revenue_ht > 0"], ordre="revenue_gap ASC", description="Les 10 plus fortes baisses de CA HT net contre la période de comparaison."),
    tableau("t_returned", "Produits les plus retournés", S_PRODUITS_NOMMES, "product_name", "product_name", "Produit", PRODUIT_MESURES,
            [col("units_returned", "{t}.units_returned", "Articles retournés", ENT), col("units_sold", "{t}.units_sold", "Articles vendus", ENT, delta=False),
             col("return_rate", "{t}.units_returned / NULLIF({t}.units_sold, 0)", "Taux de retour", PCT)],
            "units_returned", filtres=FILTRES_PRODUIT, total=False, limite=10, description="Classés par articles retournés. Un retour compte à sa propre date : le taux peut dépasser 100 % sur un produit qui ne se vend plus."),
    # ---- Retours ------------------------------------------------------------------------------------------------------
    carte("w_revenue", "Du CA TTC au CA HT net", "\n".join([
        "WITH " + cte("totals", "\n".join([
            "SELECT", "    SUM(revenue_ttc) AS revenue_ttc,", "    SUM(refund_value_ttc) AS refund_value_ttc,",
            "    SUM(revenue_ttc - revenue_ht) - SUM(refund_value_ttc - refund_value_ht) AS tax",
            f"FROM {SALES}", f"    JOIN utils.calendar ON utils.calendar.date = {SALES}.date", clause_where([], ("date", "market"))])),
        "",
        "SELECT step, amount",
        "FROM (",
        "    SELECT 1 AS step_order, 'CA TTC' AS step, revenue_ttc AS amount FROM totals",
        "    UNION ALL",
        "    SELECT 2, 'Retours', -refund_value_ttc FROM totals",
        "    UNION ALL",
        "    SELECT 3, 'TVA', -tax FROM totals",
        ")",
        "ORDER BY step_order"]), "waterfall",
          {"graph.dimensions": ["STEP"], "graph.metrics": ["AMOUNT"], "graph.x_axis.scale": "ordinal", "waterfall.show_total": True, "graph.show_values": True,
           "graph.x_axis.labels_enabled": False, "graph.y_axis.labels_enabled": False, "graph.label_value_formatting": "compact", **formats({"amount": sur_graphique(EUR)})}, D_NET),
    combo("c_refunds_rate", "Montant remboursé et taux de retour par période", {"sales": (dict(S_SALES, filtres=("market",)), {"refund_value_ttc": "SUM(refund_value_ttc)", "revenue_ttc": "SUM(revenue_ttc)"})},
          [serie("refund_value_ttc", "{sales}.refund_value_ttc", "Montant remboursé", EUR, ORANGE_C, VENTES_P),
           serie("return_rate", "{sales}.refund_value_ttc / NULLIF({sales}.revenue_ttc, 0)", "Taux de retour", PCT, LIGNE_C, LIGNE_P, "line")], description=D_RETOUR),
    tableau("t_returns", "Retours par marché", S_SALES, "market", "market", "Marché",
            {"revenue_ttc": "SUM(revenue_ttc)", "refund_value_ttc": "SUM(refund_value_ttc)", "total_refunds": "SUM(refunds)"},
            [col("revenue_ttc", "{t}.revenue_ttc", "CA TTC", EUR), col("refund_value_ttc", "{t}.refund_value_ttc", "Montant remboursé", EUR),
             col("total_refunds", "{t}.total_refunds", "Remboursements", ENT), col("return_rate", "{t}.refund_value_ttc / NULLIF({t}.revenue_ttc, 0)", "Taux de retour", PCT)],
            "revenue_ttc", filtres=("market",), description=D_RETOUR),
    # ---- Boutique -----------------------------------------------------------------------------------------------------
    kpi("retail_revenue", "CA boutique", {"retail": (S_RETAIL, {"retail_revenue": "SUM(revenue)"})}, "{retail}.retail_revenue", EUR, filtres=("store_id",), arret="boutique", description=D_BOUTIQUE),
    kpi("retail_orders", "Tickets", {"retail": (S_RETAIL, {"retail_orders": "SUM(orders)"})}, "{retail}.retail_orders", ENT, filtres=("store_id",), arret="boutique", description=D_BOUTIQUE),
    kpi("retail_aov", "Panier moyen boutique", {"retail": (S_RETAIL, {"retail_revenue": "SUM(revenue)", "retail_orders": "SUM(orders)"})}, "{retail}.retail_revenue / NULLIF({retail}.retail_orders, 0)", EUR, filtres=("store_id",), arret="boutique", description=D_BOUTIQUE),
    kpi("retail_new_customers", "Nouveaux clients boutique", {"retail": (S_RETAIL, {"retail_new_customers": "SUM(new_customers)"})}, "{retail}.retail_new_customers", ENT, filtres=("store_id",), arret="boutique", description=D_BOUTIQUE),
    kpi("retail_refund_value", "Remboursé en boutique", {"retail": (S_RETAIL, {"retail_refund_value": "SUM(refund_value)"})}, "{retail}.retail_refund_value", EUR, filtres=("store_id",), arret="boutique", inverse=True, description=D_BOUTIQUE),
    combo("c_retail", "CA boutique et tickets par période", {"retail": (dict(S_RETAIL, filtres=("store_id",)), {"retail_revenue": "SUM(revenue)", "retail_orders": "SUM(orders)"})},
          [serie("retail_revenue", "{retail}.retail_revenue", "CA boutique", EUR, ORANGE_C, VENTES_P),
           serie("retail_orders", "{retail}.retail_orders", "Tickets", ENT, LIGNE_C, LIGNE_P, "line")], arret="boutique", description=D_BOUTIQUE),
    tableau("t_stores", "Top 20 des magasins (vs P-1)", S_RETAIL, "store_id", "store_id", "Magasin",
            {"retail_revenue": "SUM(revenue)", "retail_orders": "SUM(orders)", "retail_new_customers": "SUM(new_customers)", "retail_refund_value": "SUM(refund_value)"},
            [col("retail_revenue", "{t}.retail_revenue", "CA", EUR, mini=True), col("retail_orders", "{t}.retail_orders", "Tickets", ENT),
             col("retail_aov", "{t}.retail_revenue / NULLIF({t}.retail_orders, 0)", "Panier moyen", EUR), col("retail_new_customers", "{t}.retail_new_customers", "Nouveaux clients", ENT),
             col("retail_refund_value", "{t}.retail_refund_value", "Remboursé", EUR)],
            "retail_revenue", filtres=("store_id",), arret="boutique", limite=20, description=D_BOUTIQUE + " Magasins affichés par code, faute de référentiel."),
    # ---- Cohortes et CRM ------------------------------------------------------------------------------------------------
    carte("t_cohorts", "Cohortes de nouveaux clients", f"""
SELECT
    TO_VARCHAR(annee_recrutement) AS recruitment_year,
    origine AS first_purchase,
    SUM(nb_clients) AS customers,
    SUM(ltv_m3 * nb_clients) / NULLIF(SUM(IFF(ltv_m3 IS NULL, 0, nb_clients)), 0) AS ltv_3_months,
    SUM(ltv_m6 * nb_clients) / NULLIF(SUM(IFF(ltv_m6 IS NULL, 0, nb_clients)), 0) AS ltv_6_months,
    SUM(ltv_m12 * nb_clients) / NULLIF(SUM(IFF(ltv_m12 IS NULL, 0, nb_clients)), 0) AS ltv_12_months,
    SUM(ltv_m24 * nb_clients) / NULLIF(SUM(IFF(ltv_m24 IS NULL, 0, nb_clients)), 0) AS ltv_24_months,
    SUM(repeat_m12 * nb_clients) / NULLIF(SUM(IFF(repeat_m12 IS NULL, 0, nb_clients)), 0) AS orders_12_months
FROM {COHORTS}
GROUP BY 1, 2
ORDER BY 1 DESC, 2""", "table", formats({
        "recruitment_year": {"column_title": "Recrutement"}, "first_purchase": {"column_title": "Premier achat"}, "customers": {**ENT, "column_title": "Clients"},
        "ltv_3_months": {**EUR, "column_title": "CA net à 3 mois"}, "ltv_6_months": {**EUR, "column_title": "CA net à 6 mois"}, "ltv_12_months": {**EUR, "column_title": "CA net à 12 mois"},
        "ltv_24_months": {**EUR, "column_title": "CA net à 24 mois"}, "orders_12_months": {**DEC, "column_title": "Commandes à 12 mois"}}),
          "Web et boutique, d'après Splio, jusqu'à un mois de retard. Une case vide signifie que la cohorte n'a pas encore atteint cette durée."),
    carte("d_rfm", "Répartition des clients par segment", f"""
SELECT
    rfm_segment,
    SUM(customers) AS customers
FROM {RFM}
GROUP BY 1
ORDER BY 2 DESC""", "pie", {"pie.dimension": ["RFM_SEGMENT"], "pie.metric": "CUSTOMERS", "pie.show_legend": True, "pie.show_legend_perecent": True, "pie.percent_visibility": "legend", "pie.decimal_places": 1, "pie.slice_threshold": 0, **formats({"customers": ENT})}),
    carte("t_rfm", "Base clients par segment RFM", f"""
WITH segments AS (
    SELECT
        rfm_segment,
        SUM(customers) AS customers,
        SUM(net_revenue) AS net_revenue
    FROM {RFM}
    GROUP BY 1
)

SELECT
    rfm_segment,
    CASE rfm_segment
        WHEN 'Champions' THEN 'Moins de 12 mois, 5 commandes ou plus, ou 565 € nets ou plus'
        WHEN 'Fidèles' THEN 'Moins de 12 mois, 2 à 4 commandes'
        WHEN 'Nouveaux' THEN 'Moins de 12 mois, une commande'
        WHEN 'À risque' THEN '12 à 23 mois, 2 commandes ou plus'
        WHEN 'À réactiver' THEN '12 à 23 mois, une commande'
        ELSE '24 mois ou plus'
    END AS segment_rule,
    customers,
    customers / SUM(customers) OVER () AS customers_share,
    net_revenue,
    net_revenue / SUM(net_revenue) OVER () AS revenue_share
FROM segments
ORDER BY CASE rfm_segment WHEN 'Champions' THEN 1 WHEN 'Fidèles' THEN 2 WHEN 'Nouveaux' THEN 3 WHEN 'À risque' THEN 4 WHEN 'À réactiver' THEN 5 ELSE 6 END""", "table", formats({
        "rfm_segment": {"column_title": "Segment"}, "segment_rule": {"column_title": "Dernier achat et fréquence"}, "customers": {**ENT, "column_title": "Clients", "show_mini_bar": True},
        "customers_share": {**PCT, "column_title": "Part des clients"}, "net_revenue": {**EUR, "column_title": "CA net cumulé", "show_mini_bar": True}, "revenue_share": {**PCT, "column_title": "Part du CA"}})),
]

BASE = ("date", "time_period", "comparison_date")
KPI = 3
# Onglet : filtres posés sur ses tuiles, puis (clé de carte ou titre, ligne, colonne, largeur, hauteur).
ONGLETS = [
    ("Vue d'ensemble", BASE, [
        ("# Vue d'ensemble", 0, 0, 24, 2),
        ("kpi_cost", 2, 0, 4, 2 * KPI),
        ("kpi_total_orders", 2, 4, 4, KPI), ("kpi_blended_cac", 5, 4, 4, KPI),
        ("kpi_new_customers", 2, 8, 4, KPI), ("kpi_blended_ncac", 5, 8, 4, KPI),
        ("kpi_first_orders", 2, 12, 4, KPI), ("kpi_avg_order_value", 5, 12, 4, KPI),
        ("kpi_net_revenue_ht", 2, 16, 4, KPI), ("kpi_blended_roas", 5, 16, 4, KPI),
        ("kpi_revenue_ttc", 2, 20, 4, KPI), ("kpi_return_rate", 5, 20, 4, KPI),
        ("c_orders_revenue", 8, 0, 24, 5),
        ("## Investissement média et ventes", 13, 0, 24, 2),
        ("c_roas_revenue", 15, 0, 12, 5), ("c_cac_orders", 15, 12, 12, 5),
        ("c_orders_cost", 20, 0, 12, 5), ("c_revenue_cost", 20, 12, 12, 5),
        ("### Nouveaux clients", 25, 0, 24, 1),
        ("c_ncac", 26, 0, 12, 5), ("c_new_vs_first", 26, 12, 12, 5),
        ("c_new_cost", 31, 0, 24, 5),
        ("t_markets", 36, 0, 24, 9),
    ]),
    ("Média et trafic", BASE, [
        ("# Média", 0, 0, 24, 2),
        ("d_cost_platform", 2, 0, 8, 6), ("e_cost_platform", 2, 8, 16, 6),
        ("t_platforms", 8, 0, 24, 5),
        ("# Trafic", 13, 0, 24, 2),
        ("d_sessions_channel", 15, 0, 8, 6), ("e_sessions_channel", 15, 8, 16, 6),
        ("t_channels", 21, 0, 24, 7),
    ]),
    ("Marchés", BASE + ("market",), [
        ("# Performance par marché", 0, 0, 24, 2),
        ("d_orders_market", 2, 0, 8, 6), ("e_orders_market", 2, 8, 16, 6),
        ("d_revenue_market", 8, 0, 8, 6), ("e_revenue_market", 8, 8, 16, 6),
        ("t_markets", 14, 0, 24, 9),
        ("# Performance par pays", 23, 0, 24, 2),
        ("t_countries", 25, 0, 24, 12),
    ]),
    ("Produits", BASE + FILTRES_PRODUIT, [
        ("# Performance par produit", 0, 0, 24, 2),
        ("t_types", 2, 0, 12, 8), ("t_categories", 2, 12, 12, 8),
        ("t_products", 10, 0, 12, 9), ("t_models", 10, 12, 12, 9),
        ("e_revenue_type", 19, 0, 24, 6),
        ("# À surveiller", 25, 0, 24, 2),
        ("t_declining", 27, 0, 12, 8), ("t_returned", 27, 12, 12, 8),
    ]),
    ("Retours", BASE + ("market",), [
        ("# Retours", 0, 0, 24, 2),
        ("kpi_refund_value_ttc", 2, 0, 6, KPI), ("kpi_total_refunds", 2, 6, 6, KPI), ("kpi_return_rate", 2, 12, 6, KPI), ("kpi_net_revenue_ht", 2, 18, 6, KPI),
        ("w_revenue", 5, 0, 12, 7), ("c_refunds_rate", 5, 12, 12, 7),
        ("t_returns", 12, 0, 24, 9),
    ]),
    ("Boutique", BASE + ("store_id",), [
        ("# Boutique", 0, 0, 24, 2),
        ("kpi_retail_revenue", 2, 0, 5, KPI), ("kpi_retail_orders", 2, 5, 5, KPI), ("kpi_retail_aov", 2, 10, 4, KPI), ("kpi_retail_new_customers", 2, 14, 5, KPI), ("kpi_retail_refund_value", 2, 19, 5, KPI),
        ("c_retail", 5, 0, 24, 6),
        ("t_stores", 11, 0, 24, 15),
    ]),
    ("Cohortes et CRM", (), [
        ("# Cohortes", 0, 0, 24, 2),
        ("t_cohorts", 2, 0, 24, 14),
        ("# Base clients", 16, 0, 24, 2),
        ("d_rfm", 18, 0, 8, 6), ("t_rfm", 18, 8, 16, 6),
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
        {"id": PARAM["date"], "name": "Période", "slug": "date", "type": "date/all-options", "sectionId": "date", "default": "past30days"},
        {"id": PARAM["time_period"], "name": "Granularité", "slug": "time_period", "type": "temporal-unit", "sectionId": "temporal-unit",
         "temporal_units": ["day", "week", "month", "quarter", "year"], "default": "week"},
        {"id": PARAM["market"], "name": "Marché", "slug": "market", "type": "string/=", "sectionId": "string",
         "values_query_type": "list", "values_source_type": "static-list", "values_source_config": {"values": MARCHES}},
        {"id": PARAM["product_type"], "name": "Type de produit", "slug": "product_type", "type": "string/=", "sectionId": "string"},
        {"id": PARAM["product_name"], "name": "Produit", "slug": "product_name", "type": "string/=", "sectionId": "string"},
        {"id": PARAM["store_id"], "name": "Magasin", "slug": "store_id", "type": "string/=", "sectionId": "string"},
        {"id": PARAM["comparison_date"], "name": "Comparer à", "slug": "comparison_date", "type": "date/all-options", "sectionId": "date", "required": False},
    ]
    par_cle = {c["cle"]: c for c in CARTES}
    deja = existants(mb)
    did = deja.get(("dashboard", NOM)) or http.post(mb, "/api/dashboard", json={"name": NOM, "collection_id": COLLECTION})["id"]
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
    description = "Média, ventes web, boutique et CRM de Sessùn. Sources : Nanga pour le média, leur BigQuery pour les ventes et Splio."
    # Le dashboard est réécrit en entier : la vérification « rien de perdu » de put_dashboard n'a de sens que pour une retouche.
    http.put(mb, f"/api/dashboard/{did}", json={"description": description, "parameters": params, "tabs": tabs, "dashcards": tuiles, "width": "full"})
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

    depenses, ca, commandes, nouveaux = kpi_lu("Dépenses"), kpi_lu("CA HT net"), kpi_lu("Commandes"), kpi_lu("Nouveaux clients")
    # Le mois de contrôle précède la dernière semaine de Splio : sur janvier à septembre, aucune borne n'intervient.
    precedent = lire_sql(mb, f"SELECT SUM(orders) FROM {SALES} WHERE date BETWEEN DATEADD(day, -273, '2026-01-01'::DATE) AND '2025-12-31'::DATE")[0][0]
    attendus = [("ROAS global", kpi_lu("ROAS global"), ca / depenses), ("Coût par commande", kpi_lu("Coût / commande"), depenses / commandes),
                ("Coût par nouveau client", kpi_lu("Coût / nv client"), depenses / nouveaux),
                ("Total marchés CA", total_lu("Performances par marché", "NET_REVENUE_HT"), ca), ("Total marchés commandes", total_lu("Performances par marché", "TOTAL_ORDERS"), commandes),
                ("Total plateformes", total_lu("Performances par plateforme", "COST"), depenses), ("Total retours", total_lu("Retours par marché", "REFUND_VALUE_TTC"), kpi_lu("Montant remboursé")),
                ("Total magasins", total_lu("Top 20 des magasins (vs P-1)", "RETAIL_REVENUE"), kpi_lu("CA boutique")),
                ("Commandes période précédente", kpi_lu("Commandes", 0), float(precedent))]
    ecarts = 0
    for nom, lu, attendu in attendus:
        ok = abs(lu - attendu) <= 0.001 * abs(attendu)
        ecarts += 0 if ok else 1
        print(f"  cohérence {nom}: {lu:.2f} pour {attendu:.2f} attendu {'OK' if ok else 'KO'}")
    return ecarts


def controler_arret(mb, did, d):
    """Sur la période par défaut, Splio ne couvre qu'une partie des jours : les deux lignes doivent porter sur la même durée."""
    dc = next(x for x in d["dashcards"] if x.get("card_id") and x["visualization_settings"].get("card.title") == "Nouveaux clients")
    data, err = jouer(mb, did, dc, parametres("past30days", "week"))
    if err:
        print("  arrêt Splio : ERREUR", err)
        return 1
    avant, apres = data["rows"]
    attendu = lire_sql(mb, f"""
WITH b AS (
    SELECT DATEADD(day, -30, CURRENT_DATE) AS debut, (SELECT MAX(date) FROM {SALES} WHERE new_customers_splio IS NOT NULL) AS fin
)
SELECT
    (SELECT SUM(new_customers_splio) FROM {SALES}, b WHERE date BETWEEN DATEADD(day, -(DATEDIFF(day, debut, fin) + 1), debut) AND DATEADD(day, -1, debut)),
    (SELECT SUM(new_customers_splio) FROM {SALES}, b WHERE date BETWEEN debut AND fin)
FROM b""")[0]
    ok = float(avant[1]) == float(attendu[0]) and float(apres[1]) == float(attendu[1])
    print(f"  arrêt Splio : {avant[0][:10]} {avant[1]} puis {apres[0][:10]} {apres[1]}, attendu {attendu[0]} puis {attendu[1]} {'OK' if ok else 'KO'}")
    return 0 if ok else 1


def controler(mb, did):
    d = dashboards.get_dashboard(mb, did)
    long_terme = parametres("2026-01-01~2026-09-30", "month")
    defaut = parametres("past30days", "week")
    return (controler_tuiles(mb, did, d, long_terme, "janvier à septembre") + controler_tuiles(mb, did, d, defaut, "30 derniers jours")
            + controler_coherence(mb, did, d, long_terme) + controler_arret(mb, did, d))


def principal():
    mb = connect()
    if len(sys.argv) > 1 and sys.argv[1] == "controle":
        did = existants(mb)[("dashboard", NOM)]
    else:
        ids = ecrire_cartes(mb)
        print(len(ids), "cartes écrites")
        did = ecrire_dashboard(mb, ids)
    print("dashboard", did, f"{mb.domain}/dashboard/{did}")
    return 1 if controler(mb, did) else 0


if __name__ == "__main__":
    sys.exit(principal())
