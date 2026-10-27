"""Crée « OpenAI ChatGPT Ads | Internal (all clients) » : tous les clients d'un canal côte à côte.

Les dashboards « Client VS Industry | Internal » (29901 / 29902) savent filtrer un
canal, mais sont pensés pour UN client sélectionné : les courbes ne montrent que la
ligne Global sans client. Ce dashboard reprend leurs cartes qui tiennent sans client
(scalaires, top 10, courbes globales) et ajoute des cartes natives « par client »,
sur trois onglets : Général (médias, tous les clients), Lead et Ecom (conversions,
comparables seulement entre clients du même modèle).

    python scripts/create_channel_internal_dashboard.py            # dry-run : plan + SQL validé
    python scripts/create_channel_internal_dashboard.py --apply    # crée cartes + dashboard
    python scripts/create_channel_internal_dashboard.py --rollback <dashboard_id>,<card_id>,...
    python scripts/create_channel_internal_dashboard.py --split 30384 [--apply]     # v1 → onglets
    python scripts/create_channel_internal_dashboard.py --unsplit migration/snapshot-split-....json

Issue Airtable rec1XqZGDGvbxDFaY.
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")   # console Windows en cp1252 sinon

from spark_metabase_api import connect, cards, http, dashboards  # noqa: E402

CHANNEL = "openai"
NOM = "OpenAI ChatGPT Ads | Internal (all clients)"
DESCRIPTION = "Channel: 'OpenAI'; Audience: 'Internal'"
COLLECTION_DASHBOARD = 3725     # Benchmarks & Demo Dashboards (comme 29901 / 29902)
COLLECTION_CARTES = 216         # cartes génériques « (benchmark) »
DB = 144
DONNEURS = {"ecom": 29901, "leadgen": 29902}
ALIAS_SLUG = {"exclude_client_from_industry": "exclude_client"}
DATE_DEFAUT = "past90days"      # le levier n'existe que depuis septembre 2026
DOSSIER_TRACE = os.path.join(os.path.dirname(__file__), "..", "migration")

CHAMPS = {"clients": 392829, "exclude_client": 392829, "date": 426427, "channel": 396835, "time_periods": 426427}
TAGS = {
    "clients":        {"type": "dimension", "widget-type": "category", "display-name": "Clients"},
    "exclude_client": {"type": "dimension", "widget-type": "string/=", "display-name": "Exclude client"},
    "date":           {"type": "dimension", "widget-type": "date/all-options", "display-name": "Date"},
    "channel":        {"type": "dimension", "widget-type": "category", "display-name": "Channel"},
    "time_periods":   {"type": "temporal-unit", "display-name": "Time periods"},
}
# Filtres du dashboard : slug → (nom, type, défaut, tag des cartes natives)
PARAMETRES = [
    ("client",         "Client",         "category",         None,          "clients"),
    ("exclude_client", "Exclude client", "string/=",         None,          "exclude_client"),
    ("date_filter",    "Date Filter",    "date/all-options", DATE_DEFAUT,   "date"),
    ("time_period",    "Time period",    "temporal-unit",    "week",        "time_periods"),
    ("channel",        "Channel",        "category",         [CHANNEL],     "channel"),
]

# Même chaîne de jointures que les cartes benchmark : utils.clients porte prospect / is_demo,
# reports.campaign_details porte le canal. Pas de jointure sur l'industrie : c'est elle qui
# démultiplie les montants des cartes 56568 / 56569 quand aucun client n'est choisi.
BASE_SQL = """
WITH base AS (
    SELECT
        utils.clients.name AS client_name,
        {{time_periods}} AS time_period,
        global.campaign_daily_metrics.cost,
        global.campaign_daily_metrics.impressions,
        global.campaign_daily_metrics.clicks,
        global.campaign_daily_metrics.leads,
        global.campaign_daily_metrics.purchases,
        global.campaign_daily_metrics.purchases_value
    FROM utils.clients
        JOIN utils.client_ad_platforms ON utils.client_ad_platforms.client_id = utils.clients.id
        JOIN reports.campaign_details ON reports.campaign_details.account_id = utils.client_ad_platforms.account_id
        JOIN global.campaign_daily_metrics ON global.campaign_daily_metrics.campaign_id = reports.campaign_details.campaign_id
    WHERE TRUE
        AND prospect = FALSE AND is_demo = FALSE
        [[AND {{clients}}]]
        [[AND NOT {{exclude_client}}]]
        [[AND {{date}}]]
        [[AND {{channel}}]]
        {modele}
)
"""
# Un filtre de dashboard vaut pour tous les onglets : le modèle de l'onglet est donc écrit
# dans la carte. Sous-requête plutôt que jointure : un client à deux lignes de catégorie
# ne doit pas doubler ses montants.
MODELES = {"lead": "lead generation", "ecom": "e-commerce"}


def base(modele=None):
    filtre = ""
    if modele:
        filtre = ("AND utils.clients.name IN (SELECT client_name FROM utils.client_categories "
                  "WHERE model = '{}')".format(MODELES[modele]))
    return BASE_SQL.replace("{modele}", filtre)


def sql_tableau(colonnes, modele=None, tri="cost"):
    return base(modele) + """
SELECT
    client_name,
    {colonnes}
FROM base
GROUP BY 1
ORDER BY {tri} DESC
""".format(colonnes=",\n    ".join("{} AS {}".format(expr, nom) for nom, expr in colonnes), tri=tri)


def sql_par_date(colonne, expression, modele=None):
    return base(modele) + """
SELECT time_period, client_name, {expression} AS {colonne}
FROM base
GROUP BY 1, 2
ORDER BY 1, 2
""".format(expression=expression, colonne=colonne)


def sql_scalaire(colonne, expression, modele):
    return base(modele) + """
SELECT {expression} AS {colonne}
FROM base
""".format(expression=expression, colonne=colonne)


EXPR = {
    "cost": "SUM(cost)", "impressions": "SUM(impressions)", "clicks": "SUM(clicks)",
    "cpm": "SUM(cost) / NULLIF(SUM(impressions), 0) * 1000",
    "cpc": "SUM(cost) / NULLIF(SUM(clicks), 0)",
    "ctr": "SUM(clicks) / NULLIF(SUM(impressions), 0)::float",
    "leads": "SUM(leads)",
    "cost_per_lead": "SUM(cost) / NULLIF(SUM(leads), 0)",
    "lead_rate": "SUM(leads) / NULLIF(SUM(clicks), 0)::float",
    "purchases": "SUM(purchases)",
    "revenue": "SUM(purchases_value)",
    "roas": "SUM(purchases_value) / NULLIF(SUM(cost), 0)",
    "cac": "SUM(cost) / NULLIF(SUM(purchases), 0)",
    "purchase_rate": "SUM(purchases) / NULLIF(SUM(clicks), 0)::float",
}


def cols(*noms):
    return [(n, EXPR[n]) for n in noms]


POURCENT = {"number_style": "percent", "decimals": 2}
DEVISE = {"number_style": "currency", "currency": "EUR", "currency_style": "symbol", "decimals": 2}
RATIO = {"decimals": 2}
FORMATS = {"cost": DEVISE, "cpm": DEVISE, "cpc": DEVISE, "cost_per_lead": DEVISE, "revenue": DEVISE, "cac": DEVISE,
           "ctr": POURCENT, "lead_rate": POURCENT, "purchase_rate": POURCENT, "roas": RATIO}
SERIES_PAR_CLIENT = {"graph.dimensions": ["TIME_PERIOD", "CLIENT_NAME"], "graph.x_axis.scale": "timeseries"}


def formats(*noms):
    return {"column_settings": {'["name","{}"]'.format(n.upper()): FORMATS[n] for n in noms if n in FORMATS}}


def carte_tableau(nom, noms, modele=None):
    return (nom, sql_tableau(cols(*noms), modele), "table", formats(*noms))


def carte_par_date(nom, colonne, modele=None, empile=False):
    viz = dict(SERIES_PAR_CLIENT, **{"graph.metrics": [colonne.upper()]}, **formats(colonne))
    if empile:
        viz["stackable.stack_type"] = "stacked"
    return (nom, sql_par_date(colonne, EXPR[colonne], modele), "bar" if empile else "line", viz)


def carte_scalaire(nom, colonne, modele):
    return (nom, sql_scalaire(colonne, EXPR[colonne], modele), "scalar", dict(formats(colonne), **{"card.title": nom.split(" (")[0]}))


MEDIA = ("cost", "impressions", "clicks", "cpm", "cpc", "ctr")

# (nom, sql, display, visualization_settings). Les 5 premières existent déjà sur 30384
# (57576-57580) : ne jamais les réordonner, --split les retrouve par position.
CARTES = [
    carte_tableau("Performance by client (all clients)", MEDIA),
    carte_par_date("Cost by client by date (all clients)", "cost", empile=True),
    carte_par_date("CPC by client by date (all clients)", "cpc"),
    carte_par_date("CTR by client by date (all clients)", "ctr"),
    carte_par_date("CPM by client by date (all clients)", "cpm"),
    # Onglet Lead
    carte_scalaire("Cost (all lead gen clients)", "cost", "lead"),
    carte_scalaire("Leads (all lead gen clients)", "leads", "lead"),
    carte_scalaire("Cost per lead (all lead gen clients)", "cost_per_lead", "lead"),
    carte_scalaire("Lead rate (all lead gen clients)", "lead_rate", "lead"),
    carte_tableau("Lead gen performance by client (all clients)",
                  ("cost", "clicks", "ctr", "cpc", "leads", "lead_rate", "cost_per_lead"), "lead"),
    carte_par_date("Leads by client by date (all lead gen clients)", "leads", "lead", empile=True),
    carte_par_date("Cost per lead by client by date (all lead gen clients)", "cost_per_lead", "lead"),
    # Onglet Ecom
    carte_scalaire("Cost (all ecom clients)", "cost", "ecom"),
    carte_scalaire("Purchases (all ecom clients)", "purchases", "ecom"),
    carte_scalaire("Revenue (all ecom clients)", "revenue", "ecom"),
    carte_scalaire("ROAS (all ecom clients)", "roas", "ecom"),
    carte_tableau("Ecom performance by client (all clients)",
                  ("cost", "clicks", "ctr", "cpc", "purchases", "purchase_rate", "revenue", "roas", "cac"), "ecom"),
    carte_par_date("Revenue by client by date (all ecom clients)", "revenue", "ecom", empile=True),
    carte_par_date("ROAS by client by date (all ecom clients)", "roas", "ecom"),
]
NB_CARTES_V1 = 5
CARTE_DESCRIPTION = ("Tous les clients d'un canal côte à côte (filtre channel), sans jointure sur l'industrie. "
                     "Conçue pour les dashboards internes « all clients ».")

# Grille 24 colonnes par onglet. "neuf:i" = i-ème carte de CARTES ; un entier = carte
# existante, câblée comme sur son donneur ; "texte:..." = tuile de texte.
# Général = médias seulement : les conversions ne se comparent qu'entre clients du même modèle.
ONGLETS = ["Général", "Lead", "Ecom"]
GRILLE = [
    # (onglet, référence, row, col, size_x, size_y)
    ("Général", 2309, 0, 0, 8, 3), ("Général", 2307, 0, 8, 8, 3), ("Général", 2180, 0, 16, 8, 3),
    ("Général", "texte:## Par client", 3, 0, 24, 1),
    ("Général", "neuf:0", 4, 0, 24, 6),
    ("Général", "neuf:1", 10, 0, 24, 6),
    ("Général", "neuf:2", 16, 0, 12, 6), ("Général", "neuf:3", 16, 12, 12, 6),
    ("Général", "neuf:4", 22, 0, 12, 6), ("Général", 2196, 22, 12, 12, 6),
    ("Général", 2195, 28, 0, 12, 6), ("Général", 2198, 28, 12, 12, 6),
    ("Général", "texte:## Tous clients confondus", 34, 0, 24, 1),
    ("Général", 2116, 35, 0, 8, 5), ("Général", 2115, 35, 8, 8, 5), ("Général", 2187, 35, 16, 8, 5),

    ("Lead", "neuf:5", 0, 0, 6, 3), ("Lead", "neuf:6", 0, 6, 6, 3),
    ("Lead", "neuf:7", 0, 12, 6, 3), ("Lead", "neuf:8", 0, 18, 6, 3),
    ("Lead", "neuf:9", 3, 0, 24, 6),
    ("Lead", "neuf:10", 9, 0, 12, 6), ("Lead", "neuf:11", 9, 12, 12, 6),

    ("Ecom", "neuf:12", 0, 0, 6, 3), ("Ecom", "neuf:13", 0, 6, 6, 3),
    ("Ecom", "neuf:14", 0, 12, 6, 3), ("Ecom", "neuf:15", 0, 18, 6, 3),
    ("Ecom", "neuf:16", 3, 0, 24, 6),
    ("Ecom", "neuf:17", 9, 0, 12, 6), ("Ecom", "neuf:18", 9, 12, 12, 6),
]


# ─── Cartes natives ──────────────────────────────────────────────────

def tags_natifs():
    out = {}
    for nom, spec in TAGS.items():
        out[nom] = dict(spec, id="{}-all-clients".format(nom), name=nom,
                        dimension=["field", CHAMPS[nom], {"base-type": "type/Date" if nom in ("date", "time_periods") else "type/Text"}])
    return out


def payload_carte(nom, sql, display, viz):
    return {"name": nom, "description": CARTE_DESCRIPTION, "collection_id": COLLECTION_CARTES, "display": display,
            "type": "question", "dataset_query": {"database": DB, "type": "native",
                                                  "native": {"query": sql, "template-tags": tags_natifs()}},
            "visualization_settings": viz}


def parametres_test():
    cible = lambda tag: ["dimension", ["template-tag", tag]]
    return [{"type": "category", "target": cible("channel"), "value": [CHANNEL]},
            {"type": "date/all-options", "target": cible("date"), "value": DATE_DEFAUT},
            {"type": "temporal-unit", "target": cible("time_periods"), "value": "week"}]


def valider_sql(mb, cartes=CARTES):
    """Exécute chaque carte native sans la créer (lecture seule) et affiche un extrait."""
    print("\n== Cartes natives : exécution de test (channel = {}, {})".format(CHANNEL, DATE_DEFAUT))
    for nom, sql, display, viz in cartes:
        q = payload_carte(nom, sql, display, viz)["dataset_query"]
        r = http.post(mb, "/api/dataset", json=dict(q, parameters=parametres_test()))
        if r.get("status") != "completed":
            raise RuntimeError("{} : {}".format(nom, (r.get("error") or "")[:300]))
        data = r["data"]
        cols = [c["name"] for c in data["cols"]]
        print("   {:40s} {:4d} lignes | {}".format(nom[:40], len(data["rows"]), ", ".join(cols)))
        for row in data["rows"][:3]:
            print("      ", [round(v, 3) if isinstance(v, float) else v for v in row])


# ─── Cartes existantes ───────────────────────────────────────────────

def slugs(dash):
    return {p["id"]: p["slug"] for p in dash.get("parameters", [])}


def traduire_mappings(dc, dash_source, ids_cible, card_id):
    """Recâble les filtres d'une dashcard par slug ; les slugs absents de la cible sont ignorés."""
    src = slugs(dash_source)
    out, perdus = [], []
    for pm in dc.get("parameter_mappings", []):
        slug = src.get(pm["parameter_id"])
        slug = ALIAS_SLUG.get(slug, slug)
        if slug in ids_cible:
            out.append({"parameter_id": ids_cible[slug], "card_id": card_id, "target": pm["target"]})
        else:
            perdus.append(slug)
    return out, perdus


def trouver_donneur(donneurs, card_id):
    for dash in donneurs.values():
        for dc in dash["dashcards"]:
            if dc.get("card_id") == card_id:
                return dash, dc
    raise LookupError("carte {} : absente de {}".format(card_id, list(donneurs)))


def tuile_texte(donneurs, texte):
    modele = next(dc for dc in donneurs["ecom"]["dashcards"] if dc.get("card_id") is None)
    viz = dict(modele["visualization_settings"], text=texte)
    return viz


def verifier_grille(grille):
    """Aucune tuile ne sort d'un onglet connu, ne dépasse la grille ni n'en chevauche une autre."""
    occupe = {}
    for onglet, ref, row, col, sx, sy in grille:
        if onglet not in ONGLETS:
            raise ValueError("{} : onglet inconnu {!r}".format(ref, onglet))
        if col + sx > 24:
            raise ValueError("{} dépasse les 24 colonnes".format(ref))
        for r in range(row, row + sy):
            for c in range(col, col + sx):
                if (onglet, r, c) in occupe:
                    raise ValueError("{} chevauche {} en ({}, {}, {})".format(ref, occupe[(onglet, r, c)], onglet, r, c))
                occupe[(onglet, r, c)] = ref


# ─── Plan ────────────────────────────────────────────────────────────

def construire_plan(mb, ids_cible=None):
    verifier_grille(GRILLE)
    donneurs = {k: dashboards.get_dashboard(mb, v) for k, v in DONNEURS.items()}
    # Les ids de filtres sont choisis ici (slug) : Metabase les accepte tels quels à la création.
    ids_cible = ids_cible or {slug: "all-clients-{}".format(slug) for slug, *_ in PARAMETRES}
    tuiles, avertissements = [], []
    for onglet, ref, row, col, sx, sy in GRILLE:
        tuile = {"onglet": onglet, "row": row, "col": col, "size_x": sx, "size_y": sy}
        if isinstance(ref, int):
            dash, dc = trouver_donneur(donneurs, ref)
            mappings, perdus = traduire_mappings(dc, dash, ids_cible, ref)
            if perdus:
                avertissements.append("carte {} ({}) : filtres non recâblés {}".format(ref, dc["card"]["name"], perdus))
            tuile.update(card_id=ref, nom=dc["card"]["name"], donneur=dash["id"], mappings=mappings,
                         viz=dict(dc.get("visualization_settings") or {}))
        elif ref.startswith("neuf:"):
            i = int(ref.split(":")[1])
            tuile.update(neuf=i, nom=CARTES[i][0], mappings=[
                {"parameter_id": ids_cible[slug], "target": ["dimension", ["template-tag", tag]]}
                for slug, _n, _t, _d, tag in PARAMETRES])
        else:
            tuile.update(texte=ref.split(":", 1)[1], viz=tuile_texte(donneurs, ref.split(":", 1)[1]))
        tuiles.append(tuile)
    return {"ids_cible": ids_cible, "tuiles": tuiles, "avertissements": avertissements}


def afficher_plan(plan):
    print("== « {} » dans la collection {}".format(NOM, COLLECTION_DASHBOARD))
    print("   filtres : " + ", ".join("{} (défaut {})".format(s, d) for s, _n, _t, d, _tag in PARAMETRES))
    print("   {} cartes natives dans le plan (collection {})".format(len(CARTES), COLLECTION_CARTES))
    for t in plan["tuiles"]:
        pos = "   {:8s} r{:2d} c{:2d} {:2d}x{} |".format(t["onglet"], t["row"], t["col"], t["size_x"], t["size_y"])
        if "card_id" in t:
            print(pos, "{:6d} {:55s} câblage de {} ({} filtres)".format(
                t["card_id"], t["nom"][:55], t["donneur"], len(t["mappings"])))
        elif "neuf" in t:
            print(pos, "neuf:{:<2d} {:55s} ({} filtres)".format(t["neuf"], t["nom"][:55], len(t["mappings"])))
        else:
            print(pos, "texte  {}".format(t["texte"]))
    for a in plan["avertissements"]:
        print("   ! " + a)


# ─── Application ─────────────────────────────────────────────────────

def appliquer(mb, plan):
    crees = {"cartes": [], "dashboard": None}
    try:
        for nom, sql, display, viz in CARTES:
            c = http.post(mb, "/api/card", json=payload_carte(nom, sql, display, viz))
            crees["cartes"].append(c["id"])
            print("   carte {} créée : {}".format(c["id"], nom))

        parametres = [{"id": plan["ids_cible"][slug], "slug": slug, "name": nom, "type": typ, "default": defaut}
                      for slug, nom, typ, defaut, _tag in PARAMETRES]
        dash = http.post(mb, "/api/dashboard", json={
            "name": NOM, "description": DESCRIPTION, "collection_id": COLLECTION_DASHBOARD, "parameters": parametres})
        did = crees["dashboard"] = dash["id"]
        print("   dashboard {} créé".format(did))
        poser_tuiles(mb, did, plan, crees["cartes"])
    except Exception:
        print("   échec : archivage de ce qui a été créé")
        rollback(mb, crees["dashboard"], crees["cartes"])
        raise
    return crees


def poser_tuiles(mb, did, plan, ids_cartes):
    """Remplace onglets et tuiles du dashboard par ceux du plan ; ids_cartes[i] = carte de CARTES[i]."""
    tabs = [{"id": -1 - k, "name": nom} for k, nom in enumerate(ONGLETS)]
    tab_id = {t["name"]: t["id"] for t in tabs}
    dashcards = []
    for i, t in enumerate(plan["tuiles"]):
        dc = {"id": -100 - i, "dashboard_tab_id": tab_id[t["onglet"]],
              "row": t["row"], "col": t["col"], "size_x": t["size_x"], "size_y": t["size_y"],
              "parameter_mappings": [], "visualization_settings": t.get("viz") or {}}
        if "card_id" in t:
            dc.update(card_id=t["card_id"], parameter_mappings=t["mappings"])
        elif "neuf" in t:
            cid = ids_cartes[t["neuf"]]
            dc.update(card_id=cid, parameter_mappings=[dict(m, card_id=cid) for m in t["mappings"]])
        else:
            dc.update(card_id=None)
        dashcards.append(dc)
    relu = dashboards.put_dashboard(mb, did, {"tabs": tabs, "dashcards": dashcards})
    print("   {} onglets, {} tuiles posées, {} filtres".format(
        len(relu.get("tabs") or []), len(relu["dashcards"]), len(relu["parameters"])))
    controler(mb, relu)
    return relu


def controler(mb, dash):
    """Rejoue chaque tuile avec les filtres par défaut ; lève si une tuile est vide ou en erreur."""
    pid = {p["slug"]: p for p in dash["parameters"]}
    prm = [{"id": pid[s]["id"], "type": pid[s]["type"], "value": pid[s]["default"], "target": None}
           for s in ("date_filter", "time_period", "channel")]
    suspectes = []
    for dc in dash["dashcards"]:
        if not dc.get("card_id"):
            continue
        r = http.post(mb, "/api/dashboard/{}/dashcard/{}/card/{}/query".format(dash["id"], dc["id"], dc["card_id"]),
                      json={"parameters": prm})
        rows = (r.get("data") or {}).get("rows") or []
        etat = r.get("status")
        print("      {:6d} {:50s} {} {}l {}".format(dc["card_id"], dc["card"]["name"][:50], etat, len(rows),
                                                   (r.get("error") or str(rows[:1]))[:60]))
        if etat != "completed" or not rows:
            suspectes.append(dc["card_id"])
    if suspectes:
        raise RuntimeError("tuiles vides ou en erreur : {}".format(suspectes))


def tracer(crees):
    os.makedirs(DOSSIER_TRACE, exist_ok=True)
    chemin = os.path.join(DOSSIER_TRACE, "channel-internal-dashboard-{}.json".format(datetime.now().strftime("%Y%m%dT%H%M%S")))
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(crees, f, ensure_ascii=False, indent=2)
    print("\ntrace : {}".format(chemin))


def derniere_trace():
    traces = sorted(f for f in os.listdir(DOSSIER_TRACE) if f.startswith("channel-internal-dashboard-"))
    if not traces:
        raise FileNotFoundError("aucune trace channel-internal-dashboard-*.json dans {}".format(DOSSIER_TRACE))
    with open(os.path.join(DOSSIER_TRACE, traces[-1]), encoding="utf-8") as f:
        return json.load(f)


def diviser(mb, did, apply):
    """Passe un dashboard créé en v1 (un seul écran) aux onglets Général / Lead / Ecom.

    Réutilise les 5 cartes v1 (la 1re perd ses colonnes de conversion), crée les
    cartes des onglets Lead et Ecom, puis remplace onglets et tuiles."""
    trace = derniere_trace()
    if trace["dashboard"] != did:
        raise ValueError("la dernière trace porte sur le dashboard {}, pas {}".format(trace["dashboard"], did))
    ids_v1 = trace["cartes"][:NB_CARTES_V1]
    for cid, (nom, *_r) in zip(ids_v1, CARTES):
        if cards.get_card(mb, cid)["name"] != nom:
            raise ValueError("carte {} : nom inattendu, la trace ne correspond plus".format(cid))

    dash = dashboards.get_dashboard(mb, did)
    ids_cible = {p["slug"]: p["id"] for p in dash["parameters"]}
    plan = construire_plan(mb, ids_cible)
    afficher_plan(plan)
    nouvelles = CARTES[NB_CARTES_V1:]
    print("\n   carte {} : SQL réduit aux colonnes média ; {} cartes à créer".format(ids_v1[0], len(nouvelles)))
    valider_sql(mb, [CARTES[0]] + nouvelles)
    if not apply:
        print("\nDry-run : rien n'a été écrit. Relancer avec --apply.")
        return

    os.makedirs(DOSSIER_TRACE, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%dT%H%M%S")
    snapshot = {"dashboard": dash, "carte": cards.get_card(mb, ids_v1[0])}
    chemin = os.path.join(DOSSIER_TRACE, "snapshot-split-{}-{}.json".format(did, horodatage))
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=1)
    print("\n-- snapshot : {}".format(chemin))

    crees = []
    try:
        nom, sql, display, viz = CARTES[0]
        p = payload_carte(nom, sql, display, viz)
        cards.put_card(mb, ids_v1[0], {"dataset_query": p["dataset_query"], "visualization_settings": viz})
        print("   carte {} mise à jour".format(ids_v1[0]))
        for nom, sql, display, viz in nouvelles:
            c = http.post(mb, "/api/card", json=payload_carte(nom, sql, display, viz))
            crees.append(c["id"])
            print("   carte {} créée : {}".format(c["id"], nom))
        poser_tuiles(mb, did, plan, ids_v1 + crees)
    except Exception:
        print("   échec : restauration depuis {}".format(chemin))
        restaurer_split(mb, chemin, crees)
        raise
    with open(os.path.join(DOSSIER_TRACE, "channel-internal-dashboard-{}.json".format(horodatage)), "w", encoding="utf-8") as f:
        json.dump({"dashboard": did, "cartes": ids_v1 + crees}, f, ensure_ascii=False, indent=2)
    print("\nrollback : --unsplit {}".format(chemin))


def restaurer_split(mb, chemin, crees=None):
    """Remet le dashboard et la carte v1 tels que dans le snapshot, archive les cartes créées."""
    with open(chemin, encoding="utf-8") as f:
        snap = json.load(f)
    carte = snap["carte"]
    cards.put_card(mb, carte["id"], {"dataset_query": carte["dataset_query"],
                                     "visualization_settings": carte["visualization_settings"]})
    dash = snap["dashboard"]
    dashcards = [dict(dc, id=-1 - i) for i, dc in enumerate(dash["dashcards"])]
    dashboards.put_dashboard(mb, dash["id"], {"tabs": dash.get("tabs") or [], "dashcards": dashcards})
    if crees is None:
        crees = [cid for cid in derniere_trace()["cartes"][NB_CARTES_V1:]]
    for cid in crees:
        http.put(mb, "/api/card/{}".format(cid), json={"archived": True})
    print("   dashboard {} et carte {} restaurés, {} cartes archivées".format(dash["id"], carte["id"], len(crees)))


def rollback(mb, did, cartes):
    """Archive le dashboard (None s'il n'a pas été créé) puis les cartes."""
    if did is not None:
        http.put(mb, "/api/dashboard/{}".format(did), json={"archived": True})
        print("dashboard {} archivé".format(did))
    for cid in cartes:
        http.put(mb, "/api/card/{}".format(cid), json={"archived": True})
        print("carte {} archivée".format(cid))


# ─── CLI ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="crée réellement les cartes et le dashboard")
    ap.add_argument("--rollback", help="<dashboard_id>,<card_id>,... à archiver (voir la trace)")
    ap.add_argument("--split", type=int, help="dashboard v1 déjà créé : passe aux onglets Général / Lead / Ecom")
    ap.add_argument("--unsplit", help="snapshot-split-*.json : défait --split")
    args = ap.parse_args()

    mb = connect()
    if args.split:
        diviser(mb, args.split, args.apply)
        return
    if args.unsplit:
        restaurer_split(mb, args.unsplit)
        return
    if args.rollback:
        ids = [int(x) for x in args.rollback.split(",")]
        rollback(mb, ids[0], ids[1:])
        return

    plan = construire_plan(mb)
    afficher_plan(plan)
    valider_sql(mb)

    if not args.apply:
        print("\nDry-run : rien n'a été écrit. Relancer avec --apply.")
        return

    print("\n-- création")
    crees = appliquer(mb, plan)
    tracer(crees)
    print("{}/dashboard/{}".format(mb.domain, crees["dashboard"]))


if __name__ == "__main__":
    main()
