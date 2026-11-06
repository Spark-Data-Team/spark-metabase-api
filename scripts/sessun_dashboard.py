# -*- coding: utf-8 -*-
"""Campagne : dashboard « Média et ventes | Sessùn », d'après la maquette validée au point du 05/11/2026.

Rejouable : une carte ou un dashboard déjà présent dans la collection Sessùn est mis à jour, jamais dupliqué.

    .venv/bin/python scripts/sessun_dashboard.py          # crée ou met à jour, puis contrôle
    .venv/bin/python scripts/sessun_dashboard.py controle # contrôle seulement

Sources : GLOBAL.CAMPAIGN_DAILY_METRICS pour le média, ANALYTICS.GOOGLE__ANALYTICS_METRICS pour le trafic,
CLIENT_DATA.SESSUN__* pour le reste. SESSUN__MEDIA_DAILY_METRICS ne sert qu'à la copie vers BigQuery.
Les filtres de champ imposent des tables sans alias : Metabase écrit "CLIENT_DATA"."TABLE"."COLONNE".
Un filtre de dashboard ne s'applique qu'à UN champ par carte (mesuré : le second reste à 1 = 1, sans erreur). Une carte qui
croise ventes et dépenses filtre donc les jours sur les ventes, et les dépenses suivent ces jours (JOURS).
"""
import json
import sys
import uuid

from spark_metabase_api import cards, connect, dashboards, http

DB = 144
COLLECTION = 15237
NOM = "Média et ventes | Sessùn"
CLIENT = "rec7aHUXyxAvMBEiw"
MARCHES = ["FR", "DE", "EN", "ES", "GB", "NL", "IT", "US", "CH"]

VENTES = "client_data.sessun__sales_daily_metrics"
PRODUITS = "client_data.sessun__product_daily_metrics"
BOUTIQUE = "client_data.sessun__retail_daily_metrics"
COHORTES = "client_data.sessun__crm_cohort_metrics"
RFM = "client_data.sessun__rfm_metrics"
MEDIA = "global.campaign_daily_metrics"
TRAFIC = "analytics.google__analytics_metrics"
CLIENT_MEDIA = f"client_id = '{CLIENT}'"

# Les nouveaux clients s'arrêtent au dernier chargement Splio : les dépenses aussi, sinon le coût par client serait gonflé.
FIN_SPLIO = f"(SELECT MAX(date) FROM {VENTES} WHERE new_customers_splio IS NOT NULL)"

JOURS = f"jours AS (SELECT DISTINCT date FROM {VENTES} WHERE {{{{date}}}})"

EUR = {"number_style": "currency", "currency": "EUR", "currency_style": "symbol", "decimals": 0}
# Sur un graphique en millions, zéro décimale fait lire 3,7 M en « €3M » et répète « €3M » sur l'axe.
EUR_M = {**EUR, "decimals": 1}
PCT = {"number_style": "percent", "decimals": 1}
UN = {"number_style": "decimal", "decimals": 1}
ENT = {"number_style": "decimal", "decimals": 0}
COULEURS = {"Meta": "#509EE3", "Google": "#EF8C8C", "TikTok": "#88BF4D", "Pinterest": "#A989C5", "Microsoft": "#F2A86F",
            "Premières commandes sur le site": "#F2A86F", "Nouveaux clients (Splio)": "#509EE3"}


def fmt(**colonnes):
    return {"column_settings": {json.dumps(["name", nom.replace("_", " ")], ensure_ascii=False): f for nom, f in colonnes.items()}}


def fmt_noms(colonnes):
    return {"column_settings": {json.dumps(["name", nom], ensure_ascii=False): f for nom, f in colonnes.items()}}


def carte(cle, titre, sql, display="scalar", viz=None):
    return {"cle": cle, "titre": titre, "sql": sql.strip(), "display": display, "viz": viz or {}}


def scalaire(cle, titre, sql, f):
    return carte(cle, titre, sql, "scalar", fmt_noms({titre: f}))


def barres(x, series, empile=True, extra=None):
    v = {"graph.dimensions": x, "graph.metrics": series, "graph.x_axis.title_text": "", "graph.y_axis.title_text": ""}
    if empile:
        v["stackable.stack_type"] = "stacked"
    v.update(extra or {})
    return v


def courbe(x, series, f, extra=None):
    v = {"graph.dimensions": [x], "graph.metrics": series, "graph.x_axis.scale": "timeseries", "graph.show_values": True,
         "graph.x_axis.title_text": "", "graph.y_axis.title_text": ""}
    v.update(fmt_noms({s: f for s in series}))
    v.update(extra or {})
    return v


def couleurs(*noms):
    return {"series_settings": {n: {"color": COULEURS[n]} for n in noms}}


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
CA_NET = "SUM(revenue_ht - refund_value_ht)"

CARTES = [
    # ---- Vue d'ensemble -------------------------------------------------------------------------------------------
    scalaire("kpi_depenses", "Dépenses média", f"""SELECT SUM(cost) AS "Dépenses média" FROM {MEDIA} WHERE {CLIENT_MEDIA} AND {{{{date_media}}}}""", EUR),
    scalaire("kpi_ca_net", "CA HT net", f"""SELECT {CA_NET} AS "CA HT net" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", EUR),
    scalaire("kpi_ca_ttc", "CA TTC avant retours", f"""SELECT SUM(revenue_ttc) AS "CA TTC avant retours" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", EUR),
    scalaire("kpi_commandes", "Commandes", f"""SELECT SUM(orders) AS "Commandes" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", ENT),
    scalaire("kpi_panier", "Panier moyen TTC", f"""SELECT SUM(revenue_ttc) / NULLIF(SUM(orders), 0) AS "Panier moyen TTC" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", EUR),
    scalaire("kpi_nouveaux", "Nouveaux clients", f"""SELECT SUM(new_customers_splio) AS "Nouveaux clients" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", ENT),
    scalaire("kpi_roas", "ROAS global", f"""
WITH {JOURS},
ventes AS (SELECT {CA_NET} AS ca FROM {VENTES} WHERE date IN (SELECT date FROM jours)),
depenses AS (SELECT SUM(cost) AS cout FROM {MEDIA} WHERE {CLIENT_MEDIA} AND date IN (SELECT date FROM jours))
SELECT ca / NULLIF(cout, 0) AS "ROAS global" FROM ventes, depenses""", UN),
    scalaire("kpi_cpa", "Coût par nouveau client", f"""
WITH {JOURS},
clients AS (SELECT SUM(new_customers_splio) AS nb FROM {VENTES} WHERE date IN (SELECT date FROM jours)),
depenses AS (SELECT SUM(cost) AS cout FROM {MEDIA} WHERE {CLIENT_MEDIA} AND date IN (SELECT date FROM jours) AND date <= {FIN_SPLIO})
SELECT cout / NULLIF(nb, 0) AS "Coût par nouveau client" FROM clients, depenses""", EUR),
    scalaire("kpi_rembourse", "Montant remboursé", f"""SELECT SUM(refund_value_ttc) AS "Montant remboursé" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", EUR),
    scalaire("kpi_taux_retour", "Taux de retour", f"""SELECT SUM(refund_value_ttc) / NULLIF(SUM(revenue_ttc), 0) AS "Taux de retour" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", PCT),
    carte("depenses_mois", "Dépenses par plateforme", f"""
SELECT DATE_TRUNC('month', date) AS "Mois", {PLATEFORME} AS "Plateforme", SUM(cost) AS "Dépenses"
FROM {MEDIA} WHERE {CLIENT_MEDIA} AND {{{{date_media}}}} GROUP BY 1, 2 ORDER BY 1, 2""", "bar",
          {**barres(["Mois", "Plateforme"], ["Dépenses"], extra={"graph.x_axis.scale": "timeseries"}), **fmt_noms({"Dépenses": EUR}), **couleurs("Meta", "Google", "TikTok", "Pinterest")}),
    carte("ca_mois", "CA HT net", f"""
SELECT DATE_TRUNC('month', date) AS "Mois", {CA_NET} AS "CA HT net"
FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}} GROUP BY 1 ORDER BY 1""", "bar",
          {**barres(["Mois"], ["CA HT net"], empile=False, extra={"graph.x_axis.scale": "timeseries", "graph.show_values": True}), **fmt_noms({"CA HT net": EUR_M})}),
    carte("roas_mois", "ROAS global", f"""
WITH {JOURS},
ventes AS (SELECT DATE_TRUNC('month', date) AS mois, {CA_NET} AS ca FROM {VENTES} WHERE date IN (SELECT date FROM jours) GROUP BY 1),
depenses AS (SELECT DATE_TRUNC('month', date) AS mois, SUM(cost) AS cout FROM {MEDIA} WHERE {CLIENT_MEDIA} AND date IN (SELECT date FROM jours) GROUP BY 1)
SELECT v.mois AS "Mois", v.ca / NULLIF(d.cout, 0) AS "ROAS global" FROM ventes AS v JOIN depenses AS d ON d.mois = v.mois ORDER BY 1""", "line", courbe("Mois", ["ROAS global"], UN)),
    carte("cpa_mois", "Coût par nouveau client", f"""
WITH {JOURS},
clients AS (SELECT DATE_TRUNC('month', date) AS mois, SUM(new_customers_splio) AS nb FROM {VENTES} WHERE date IN (SELECT date FROM jours) AND new_customers_splio IS NOT NULL GROUP BY 1),
depenses AS (SELECT DATE_TRUNC('month', date) AS mois, SUM(cost) AS cout FROM {MEDIA} WHERE {CLIENT_MEDIA} AND date IN (SELECT date FROM jours) AND date <= {FIN_SPLIO} GROUP BY 1)
SELECT c.mois AS "Mois", d.cout / NULLIF(c.nb, 0) AS "Coût par nouveau client" FROM clients AS c JOIN depenses AS d ON d.mois = c.mois ORDER BY 1""", "line", courbe("Mois", ["Coût par nouveau client"], EUR)),
    # ---- Média et trafic ------------------------------------------------------------------------------------------
    carte("depenses_semaine", "Dépenses par semaine et par plateforme", f"""
SELECT DATE_TRUNC('week', date) AS "Semaine", {PLATEFORME} AS "Plateforme", SUM(cost) AS "Dépenses"
FROM {MEDIA} WHERE {CLIENT_MEDIA} AND {{{{date_media}}}} GROUP BY 1, 2 ORDER BY 1, 2""", "bar",
          {**barres(["Semaine", "Plateforme"], ["Dépenses"], extra={"graph.x_axis.scale": "timeseries"}), **fmt_noms({"Dépenses": EUR}), **couleurs("Meta", "Google", "TikTok", "Pinterest")}),
    carte("declare", "Ce que chaque plateforme déclare", f"""
SELECT {PLATEFORME} AS "Plateforme", SUM(cost) AS "Dépenses", SUM(cost) / NULLIF(SUM(SUM(cost)) OVER (), 0) AS "Part des dépenses",
    SUM(purchases_value) AS "CA déclaré", SUM(purchases_value) / NULLIF(SUM(cost), 0) AS "ROAS déclaré"
FROM {MEDIA} WHERE {CLIENT_MEDIA} AND {{{{date_media}}}} GROUP BY 1 ORDER BY 2 DESC""", "table",
          fmt_noms({"Dépenses": EUR, "Part des dépenses": PCT, "CA déclaré": EUR, "ROAS déclaré": UN})),
    carte("trafic", "Trafic par canal", f"""
SELECT {CANAL} AS "Canal", SUM(sessions) AS "Sessions", SUM(sessions) / NULLIF(SUM(SUM(sessions)) OVER (), 0) AS "Part des sessions",
    SUM(new_users) AS "Nouveaux visiteurs", SUM(engaged_sessions) / NULLIF(SUM(sessions), 0) AS "Taux d'engagement"
FROM {TRAFIC} WHERE {CLIENT_MEDIA} AND {{{{date_trafic}}}} GROUP BY 1 ORDER BY 2 DESC""", "table",
          fmt_noms({"Sessions": ENT, "Part des sessions": PCT, "Nouveaux visiteurs": ENT, "Taux d'engagement": PCT})),
    # ---- Marchés --------------------------------------------------------------------------------------------------
    carte("marches", "Résultats par marché", f"""
SELECT market AS "Marché", {CA_NET} AS "CA HT net", SUM(orders) AS "Commandes", SUM(revenue_ttc) / NULLIF(SUM(orders), 0) AS "Panier moyen TTC",
    SUM(new_customers_splio) AS "Nouveaux clients", SUM(refund_value_ttc) AS "Montant remboursé", SUM(refund_value_ttc) / NULLIF(SUM(revenue_ttc), 0) AS "Taux de retour"
FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}} GROUP BY 1 ORDER BY 2 DESC""", "table",
          fmt_noms({"CA HT net": EUR, "Commandes": ENT, "Panier moyen TTC": EUR, "Nouveaux clients": ENT, "Montant remboursé": EUR, "Taux de retour": PCT})),
    carte("marches_ca", "CA HT net par marché", f"""
SELECT market AS "Marché", {CA_NET} AS "CA HT net" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}} GROUP BY 1 ORDER BY 2 DESC""", "bar",
          {**barres(["Marché"], ["CA HT net"], empile=False, extra={"graph.show_values": True, "graph.x_axis.scale": "ordinal", "graph.label_value_frequency": "all"}), **fmt_noms({"CA HT net": EUR_M})}),
    carte("pays_ca", "CA HT net par pays de livraison", f"""
SELECT country AS "Pays", {CA_NET} AS "CA HT net", SUM(orders) AS "Commandes" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}} GROUP BY 1 ORDER BY 2 DESC LIMIT 15""", "table",
          fmt_noms({"CA HT net": EUR, "Commandes": ENT})),
    # ---- Boutique -------------------------------------------------------------------------------------------------
    scalaire("bo_ca", "CA boutique", f"""SELECT SUM(revenue) AS "CA boutique" FROM {BOUTIQUE} WHERE {{{{date_boutique}}}}""", EUR),
    scalaire("bo_tickets", "Tickets", f"""SELECT SUM(orders) AS "Tickets" FROM {BOUTIQUE} WHERE {{{{date_boutique}}}}""", ENT),
    scalaire("bo_panier", "Panier moyen", f"""SELECT SUM(revenue) / NULLIF(SUM(orders), 0) AS "Panier moyen" FROM {BOUTIQUE} WHERE {{{{date_boutique}}}}""", EUR),
    scalaire("bo_nouveaux", "Nouveaux clients boutique", f"""SELECT SUM(new_customers) AS "Nouveaux clients boutique" FROM {BOUTIQUE} WHERE {{{{date_boutique}}}}""", ENT),
    scalaire("bo_rembourse", "Remboursé en boutique", f"""SELECT SUM(refund_value) AS "Remboursé en boutique" FROM {BOUTIQUE} WHERE {{{{date_boutique}}}}""", EUR),
    carte("bo_mois", "CA boutique par mois", f"""
SELECT DATE_TRUNC('month', date) AS "Mois", SUM(revenue) AS "CA boutique" FROM {BOUTIQUE} WHERE {{{{date_boutique}}}} GROUP BY 1 ORDER BY 1""", "bar",
          {**barres(["Mois"], ["CA boutique"], empile=False, extra={"graph.x_axis.scale": "timeseries", "graph.show_values": True, "graph.label_value_formatting": "full"}), **fmt_noms({"CA boutique": EUR})}),
    carte("bo_magasins", "Top 20 des magasins", f"""
SELECT store_id AS "Magasin", SUM(revenue) AS "CA", SUM(orders) AS "Tickets", SUM(revenue) / NULLIF(SUM(orders), 0) AS "Panier moyen", SUM(new_customers) AS "Nouveaux clients", SUM(refund_value) AS "Remboursé"
FROM {BOUTIQUE} WHERE {{{{date_boutique}}}} GROUP BY 1 ORDER BY 2 DESC LIMIT 20""", "table",
          fmt_noms({"CA": EUR, "Tickets": ENT, "Panier moyen": EUR, "Nouveaux clients": ENT, "Remboursé": EUR})),
    # ---- Nouveaux clients -----------------------------------------------------------------------------------------
    scalaire("nc_site", "Premières commandes sur le site", f"""SELECT SUM(first_orders_web) AS "Premières commandes sur le site" FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", ENT),
    scalaire("nc_couverture", "Commandes retrouvées dans Splio", f"""
SELECT SUM(orders_in_splio) / NULLIF(SUM(IFF(orders_in_splio IS NULL, 0, orders)), 0) AS "Commandes retrouvées dans Splio"
FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}""", PCT),
    carte("nc_mois", "Nouveaux clients par mois", f"""
SELECT DATE_TRUNC('month', date) AS "Mois", SUM(new_customers_splio) AS "Nouveaux clients (Splio)", SUM(first_orders_web) AS "Premières commandes sur le site"
FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}} GROUP BY 1 ORDER BY 1""", "line",
          courbe("Mois", ["Nouveaux clients (Splio)", "Premières commandes sur le site"], ENT, couleurs("Nouveaux clients (Splio)", "Premières commandes sur le site"))),
    # ---- Cohortes et CRM ------------------------------------------------------------------------------------------
    carte("cohortes", "Cohortes de nouveaux clients", f"""
SELECT annee_recrutement::VARCHAR AS "Recrutement", origine AS "Premier achat", SUM(nb_clients) AS "Clients",
    SUM(ltv_m3 * nb_clients) / NULLIF(SUM(IFF(ltv_m3 IS NULL, 0, nb_clients)), 0) AS "CA net à 3 mois",
    SUM(ltv_m6 * nb_clients) / NULLIF(SUM(IFF(ltv_m6 IS NULL, 0, nb_clients)), 0) AS "CA net à 6 mois",
    SUM(ltv_m12 * nb_clients) / NULLIF(SUM(IFF(ltv_m12 IS NULL, 0, nb_clients)), 0) AS "CA net à 12 mois",
    SUM(ltv_m24 * nb_clients) / NULLIF(SUM(IFF(ltv_m24 IS NULL, 0, nb_clients)), 0) AS "CA net à 24 mois",
    SUM(repeat_m12 * nb_clients) / NULLIF(SUM(IFF(repeat_m12 IS NULL, 0, nb_clients)), 0) AS "Commandes à 12 mois"
FROM {COHORTES} GROUP BY 1, 2 ORDER BY 1 DESC, 2""", "table",
          fmt_noms({"Clients": ENT, "CA net à 3 mois": EUR, "CA net à 6 mois": EUR, "CA net à 12 mois": EUR, "CA net à 24 mois": EUR, "Commandes à 12 mois": {"number_style": "decimal", "decimals": 2}})),
    carte("rfm", "Base clients par segment RFM", f"""
WITH segments AS (
    SELECT rfm_segment, SUM(customers) AS clients, SUM(net_revenue) AS ca FROM {RFM} GROUP BY 1
)
SELECT rfm_segment AS "Segment",
    CASE rfm_segment
        WHEN 'Champions' THEN 'Moins de 12 mois, 5 commandes ou plus, ou 565 € nets ou plus'
        WHEN 'Fidèles' THEN 'Moins de 12 mois, 2 à 4 commandes'
        WHEN 'Nouveaux' THEN 'Moins de 12 mois, une commande'
        WHEN 'À risque' THEN '12 à 23 mois, 2 commandes ou plus'
        WHEN 'À réactiver' THEN '12 à 23 mois, une commande'
        ELSE '24 mois ou plus'
    END AS "Dernier achat et fréquence",
    clients AS "Clients", clients / SUM(clients) OVER () AS "Part des clients",
    ca AS "CA net cumulé", ca / SUM(ca) OVER () AS "Part du CA"
FROM segments
ORDER BY CASE rfm_segment WHEN 'Champions' THEN 1 WHEN 'Fidèles' THEN 2 WHEN 'Nouveaux' THEN 3 WHEN 'À risque' THEN 4 WHEN 'À réactiver' THEN 5 ELSE 6 END""", "table",
          fmt_noms({"Clients": ENT, "Part des clients": PCT, "CA net cumulé": EUR, "Part du CA": PCT})),
    # ---- Retours --------------------------------------------------------------------------------------------------
    carte("cascade", "Du CA TTC au CA HT net", f"""
WITH t AS (
    SELECT SUM(revenue_ttc) AS ttc, SUM(refund_value_ttc) AS retours,
        SUM(revenue_ttc - revenue_ht) - SUM(refund_value_ttc - refund_value_ht) AS tva
    FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}}
)
SELECT "Étape", "Montant" FROM (
    SELECT 1 AS o, 'CA TTC' AS "Étape", ttc AS "Montant" FROM t
    UNION ALL SELECT 2, 'Retours', -retours FROM t
    UNION ALL SELECT 3, 'TVA', -tva FROM t
) ORDER BY o""", "waterfall",
          {"graph.dimensions": ["Étape"], "graph.metrics": ["Montant"], "graph.x_axis.scale": "ordinal", "waterfall.show_total": True,
           "graph.show_values": True, "graph.x_axis.title_text": "", "graph.y_axis.title_text": "", **fmt_noms({"Montant": EUR_M})}),
    carte("retour_mois", "Taux de retour", f"""
SELECT DATE_TRUNC('month', date) AS "Mois", SUM(refund_value_ttc) / NULLIF(SUM(revenue_ttc), 0) AS "Taux de retour"
FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}} GROUP BY 1 ORDER BY 1""", "line", courbe("Mois", ["Taux de retour"], PCT)),
    carte("retour_marche", "Retours par marché", f"""
SELECT market AS "Marché", SUM(revenue_ttc) AS "CA TTC", SUM(refund_value_ttc) AS "Montant remboursé", SUM(refund_value_ttc) / NULLIF(SUM(revenue_ttc), 0) AS "Taux de retour"
FROM {VENTES} WHERE {{{{date}}}} AND {{{{market}}}} GROUP BY 1 ORDER BY 2 DESC""", "table",
          fmt_noms({"CA TTC": EUR, "Montant remboursé": EUR, "Taux de retour": PCT})),
    # ---- Produits -------------------------------------------------------------------------------------------------
    carte("categories", "Performance par catégorie", f"""
SELECT product_category AS "Catégorie", {CA_NET} AS "CA HT net", {CA_NET} / NULLIF(SUM({CA_NET}) OVER (), 0) AS "Part du CA", SUM(units_sold) AS "Articles vendus",
    SUM(units_returned) / NULLIF(SUM(units_sold), 0) AS "Taux de retour"
FROM {PRODUITS} WHERE {{{{date_produit}}}} AND {{{{market_produit}}}} GROUP BY 1 ORDER BY 2 DESC""", "table",
          fmt_noms({"CA HT net": EUR, "Part du CA": PCT, "Articles vendus": ENT, "Taux de retour": PCT})),
    carte("produits", "Top 30 des produits", f"""
SELECT product_name AS "Produit", MAX(product_category) AS "Catégorie", {CA_NET} AS "CA HT net", SUM(units_sold) AS "Articles vendus",
    SUM(units_returned) / NULLIF(SUM(units_sold), 0) AS "Taux de retour"
FROM {PRODUITS} WHERE {{{{date_produit}}}} AND {{{{market_produit}}}} AND product_name <> 'unknown' GROUP BY 1 ORDER BY 3 DESC LIMIT 30""", "table",
          fmt_noms({"CA HT net": EUR, "Articles vendus": ENT, "Taux de retour": PCT})),
]

# Onglet -> tuiles : (clé de carte ou texte, ligne, colonne, largeur, hauteur)
KPI = 3
ONGLETS = [
    ("Vue d'ensemble", [
        ("kpi_depenses", 0, 0, 5, KPI), ("kpi_ca_net", 0, 5, 5, KPI), ("kpi_ca_ttc", 0, 10, 5, KPI), ("kpi_commandes", 0, 15, 5, KPI), ("kpi_panier", 0, 20, 4, KPI),
        ("kpi_nouveaux", 3, 0, 5, KPI), ("kpi_roas", 3, 5, 5, KPI), ("kpi_cpa", 3, 10, 5, KPI), ("kpi_rembourse", 3, 15, 5, KPI), ("kpi_taux_retour", 3, 20, 4, KPI),
        ("Le CA, les commandes et les retours sont ceux du site web. **Le filtre Marché ne s'applique ni aux dépenses, ni au ROAS, ni au coût par client** : les dépenses ne se répartissent pas par marché. Nouveaux clients et coût par client s'arrêtent au dernier chargement de Splio.", 6, 0, 24, 2),
        ("depenses_mois", 8, 0, 12, 7), ("ca_mois", 8, 12, 12, 7), ("roas_mois", 15, 0, 12, 7), ("cpa_mois", 15, 12, 12, 7),
    ]),
    ("Média et trafic", [
        ("depenses_semaine", 0, 0, 24, 8),
        ("declare", 8, 0, 24, 5),
        ("Le ROAS déclaré est calculé par chaque plateforme selon ses propres règles d'attribution. Il se lit à côté du ROAS global de l'onglet Vue d'ensemble, calculé sur les ventes du site.", 13, 0, 24, 2),
        ("trafic", 15, 0, 24, 7),
        ("Source GA4. Les conversions GA4 ne sont pas configurées pour Sessùn dans Nanga : pas de taux de conversion par canal pour l'instant.", 22, 0, 24, 2),
    ]),
    ("Marchés", [
        ("Ventes du site par version du site (`EN` regroupe les pays servis en anglais). **Pas de dépenses, de ROAS ni de coût par client par marché** : depuis juillet 2026, Meta passe par un compte global, et le pays n'est lisible dans le nom de campagne que pour 12 % du coût social.", 0, 0, 24, 2),
        ("marches", 2, 0, 24, 8),
        ("marches_ca", 10, 0, 12, 8), ("pays_ca", 10, 12, 12, 8),
    ]),
    ("Boutique", [
        ("bo_ca", 0, 0, 5, KPI), ("bo_tickets", 0, 5, 5, KPI), ("bo_panier", 0, 10, 4, KPI), ("bo_nouveaux", 0, 14, 5, KPI), ("bo_rembourse", 0, 19, 5, KPI),
        ("Tickets Splio : **à jour au dernier chargement seulement**, jusqu'à un mois de retard. Montants tels que chargés, TVA non disponible. Les magasins sont affichés par code, faute de référentiel.", 3, 0, 24, 2),
        ("bo_mois", 5, 0, 24, 7),
        ("bo_magasins", 12, 0, 24, 15),
    ]),
    ("Nouveaux clients", [
        ("kpi_nouveaux", 0, 0, 6, KPI), ("nc_site", 0, 6, 6, KPI), ("kpi_cpa", 0, 12, 6, KPI), ("nc_couverture", 0, 18, 6, KPI),
        ("**Nouveaux clients (Splio)** : première commande tous canaux, un client déjà venu en boutique ne compte pas. C'est la référence, mais elle s'arrête au dernier chargement. **Premières commandes sur le site** : disponible chaque jour, mais compte aussi d'anciens clients.", 3, 0, 24, 2),
        ("nc_mois", 5, 0, 12, 8), ("cpa_mois", 5, 12, 12, 8),
    ]),
    ("Cohortes et CRM", [
        ("Web et boutique, d'après Splio : **jusqu'à un mois de retard**. Une case vide signifie que la cohorte n'a pas encore atteint cette durée. Les filtres de période et de marché ne s'appliquent pas à cet onglet.", 0, 0, 24, 2),
        ("cohortes", 2, 0, 24, 14),
        ("rfm", 16, 0, 24, 6),
    ]),
    ("Retours", [
        ("kpi_rembourse", 0, 0, 8, KPI), ("kpi_taux_retour", 0, 8, 8, KPI), ("kpi_ca_net", 0, 16, 8, KPI),
        ("Site web. Un remboursement compte à sa propre date, pas à celle de la commande : le taux monte donc après les pics de commandes de janvier et de juillet, quand les retours arrivent et que les commandes baissent. Le CA HT net inclut les frais de port.", 3, 0, 24, 2),
        ("cascade", 5, 0, 12, 8), ("retour_mois", 5, 12, 12, 8),
        ("retour_marche", 13, 0, 24, 8),
    ]),
    ("Produits", [
        ("Site web, hors frais de port. Le taux de retour compare les articles retournés aux articles vendus sur la période.", 0, 0, 24, 2),
        ("categories", 2, 0, 24, 9),
        ("produits", 11, 0, 24, 12),
    ]),
]

TEXTE_LARGEUR = {"text.align_vertical": "middle", "dashcard.background": False}


def champs(mb):
    """Identifiants des champs : les filtres de champ s'y rattachent. Ils n'existent qu'après la synchro Metabase."""
    def lire(schema, table):
        t = next(x for x in http.get(mb, f"/api/database/{DB}/schema/{schema}") if x["name"].upper() == table)
        return {f["name"].upper(): f["id"] for f in http.get(mb, f"/api/table/{t['id']}/query_metadata")["fields"]}
    ventes = lire("CLIENT_DATA", "SESSUN__SALES_DAILY_METRICS")
    produits = lire("CLIENT_DATA", "SESSUN__PRODUCT_DAILY_METRICS")
    return {
        "date": (ventes["DATE"], "date/all-options"),
        "market": (ventes["MARKET"], "string/="),
        "date_media": (lire("GLOBAL", "CAMPAIGN_DAILY_METRICS")["DATE"], "date/all-options"),
        "date_trafic": (lire("ANALYTICS", "GOOGLE__ANALYTICS_METRICS")["DATE"], "date/all-options"),
        "date_boutique": (lire("CLIENT_DATA", "SESSUN__RETAIL_DAILY_METRICS")["DATE"], "date/all-options"),
        "date_produit": (produits["DATE"], "date/all-options"),
        "market_produit": (produits["MARKET"], "string/="),
    }


def tags_de(sql, ch):
    tags = {}
    for nom, (champ, widget) in ch.items():
        if "{{%s}}" % nom in sql:
            tags[nom] = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "sessun/" + nom)), "name": nom, "display-name": nom, "type": "dimension",
                         "dimension": ["field", champ, None], "widget-type": widget, "required": False}
    return tags


def existants(mb):
    items = http.get(mb, f"/api/collection/{COLLECTION}/items?models=card&models=dashboard&limit=500")["data"]
    return {(i["model"], i["name"]): i["id"] for i in items}


def ecrire_cartes(mb):
    ch, deja, ids = champs(mb), existants(mb), {}
    for c in CARTES:
        nom = f"{c['titre']} | Sessùn"
        payload = {"name": nom, "display": c["display"], "visualization_settings": c["viz"], "collection_id": COLLECTION,
                   "dataset_query": {"type": "native", "database": DB, "native": {"query": c["sql"], "template-tags": tags_de(c["sql"], ch)}}}
        # Deux cartes peuvent porter le même titre (mensuelle et chiffre clé) : la clé les distingue dans le nom.
        if sum(1 for x in CARTES if x["titre"] == c["titre"]) > 1:
            nom = payload["name"] = f"{c['titre']} ({'chiffre' if c['display'] == 'scalar' else 'par mois'}) | Sessùn"
        if ("card", nom) in deja:
            cards.put_card(mb, deja[("card", nom)], payload)
            ids[c["cle"]] = deja[("card", nom)]
        else:
            ids[c["cle"]] = http.post(mb, "/api/card", json=payload)["id"]
    return ids


def ecrire_dashboard(mb, ids):
    params = [
        {"id": "sessun_date", "name": "Période", "slug": "date", "type": "date/all-options", "sectionId": "date", "default": "past12months"},
        {"id": "sessun_market", "name": "Marché", "slug": "market", "type": "string/=", "sectionId": "string",
         "values_query_type": "list", "values_source_type": "static-list", "values_source_config": {"values": MARCHES}},
    ]
    vers_param = {"date": "sessun_date", "date_media": "sessun_date", "date_trafic": "sessun_date", "date_boutique": "sessun_date",
                  "date_produit": "sessun_date", "market": "sessun_market", "market_produit": "sessun_market"}
    par_cle = {c["cle"]: c for c in CARTES}
    tabs, tuiles, dc, tab = [], [], -1, -1
    for pos, (onglet, contenu) in enumerate(ONGLETS):
        tabs.append({"id": tab, "name": onglet, "position": pos})
        for quoi, row, col, sx, sy in contenu:
            base = {"id": dc, "dashboard_tab_id": tab, "row": row, "col": col, "size_x": sx, "size_y": sy}
            if quoi in par_cle:
                cid = ids[quoi]
                tags = [t for t in vers_param if "{{%s}}" % t in par_cle[quoi]["sql"]]
                tuiles.append({**base, "card_id": cid, "visualization_settings": {"card.title": par_cle[quoi]["titre"]},
                               "parameter_mappings": [{"parameter_id": vers_param[t], "card_id": cid, "target": ["dimension", ["template-tag", t], {"stage-number": 0}]} for t in tags]})
            else:
                tuiles.append({**base, "card_id": None, "parameter_mappings": [],
                               "visualization_settings": {"virtual_card": {"name": None, "display": "text", "visualization_settings": {}, "dataset_query": {}, "archived": False}, "text": quoi, **TEXTE_LARGEUR}})
            dc -= 1
        tab -= 1
    deja = existants(mb)
    did = deja.get(("dashboard", NOM)) or http.post(mb, "/api/dashboard", json={"name": NOM, "collection_id": COLLECTION})["id"]
    description = "Média, ventes web, boutique et CRM de Sessùn. Sources : Nanga pour le média, leur BigQuery pour les ventes et Splio."
    # Le dashboard est réécrit en entier : la vérification « rien de perdu » de put_dashboard n'a de sens que pour une retouche.
    http.put(mb, f"/api/dashboard/{did}", json={"description": description, "parameters": params, "tabs": tabs, "dashcards": tuiles, "width": "full"})
    relu = dashboards.get_dashboard(mb, did)
    if len(relu["dashcards"]) != len(tuiles) or len(relu["tabs"]) != len(tabs):
        raise ValueError(f"dashboard {did} : {len(relu['dashcards'])} tuiles relues sur {len(tuiles)}, {len(relu['tabs'])} onglets sur {len(tabs)}")
    return did


def valeur(mb, did, dc, params):
    r = http.post(mb, f"/api/dashboard/{did}/dashcard/{dc['id']}/card/{dc['card_id']}/query", json={"parameters": params}, timeout=300)
    if r.get("error"):
        return None, str(r["error"])[:200]
    return r["data"]["rows"], None


def controler(mb, did, periode="2026-01-01~2026-09-30"):
    """Joue chaque tuile comme le dashboard le ferait. Une tuile vide ou en erreur est un échec, pas une note."""
    d = dashboards.get_dashboard(mb, did)
    onglets = {t["id"]: t["name"] for t in d["tabs"]}
    ps = [{"id": "sessun_date", "type": "date/all-options", "value": periode,
           "target": ["dimension", ["template-tag", "date"], {"stage-number": 0}]}]
    echecs = 0
    for dc in sorted(d["dashcards"], key=lambda x: (x["dashboard_tab_id"], x["row"], x["col"])):
        if not dc.get("card_id"):
            continue
        titre = dc["visualization_settings"].get("card.title") or ""
        lignes, err = valeur(mb, did, dc, ps)
        vide = not lignes or (len(lignes) == 1 and all(v is None for v in lignes[0]))
        if err or vide:
            echecs += 1
        etat = "ERREUR " + err if err else ("VIDE" if vide else (str(lignes[0][0])[:16] if len(lignes) == 1 else f"{len(lignes)} lignes"))
        print(f"  {onglets[dc['dashboard_tab_id']][:16]:16} {titre[:38]:38} {etat}")
    print(f"{echecs} tuile(s) en échec sur {sum(1 for x in d['dashcards'] if x.get('card_id'))}")
    return echecs + controler_coherence(mb, did, d, ps)


def controler_coherence(mb, did, d, ps):
    """Une tuile peut répondre et être fausse (filtre appliqué à moitié) : les chiffres clés doivent se recouper entre eux."""
    def kpi(titre):
        dc = next(x for x in d["dashcards"] if x.get("card_id") and x["card"]["display"] == "scalar"
                  and x["visualization_settings"].get("card.title") == titre)
        return float(valeur(mb, did, dc, ps)[0][0][0])
    depenses, ca, nouveaux = kpi("Dépenses média"), kpi("CA HT net"), kpi("Nouveaux clients")
    ecarts = 0
    for nom, lu, attendu in [("ROAS global", kpi("ROAS global"), ca / depenses),
                             ("Coût par nouveau client", kpi("Coût par nouveau client"), depenses / nouveaux)]:
        ok = abs(lu - attendu) < 0.01 * attendu
        ecarts += 0 if ok else 1
        print(f"  cohérence {nom}: {lu:.2f} pour {attendu:.2f} attendu {'OK' if ok else 'KO'}")
    return ecarts


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
