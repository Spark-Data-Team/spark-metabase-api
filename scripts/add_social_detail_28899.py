#!/usr/bin/env python3
"""Issue #21639 (Angéline) : détail campagne sociale par source sur le dash 28899.

Crée 3 cartes tableau (CPL, CP MQL, CPA par source Facebook/TikTok), les pose en
bas de l'onglet Blended Leviers avec un titre de section, et câble les filtres
date, comparaison, client, levier et source acquisition.

Dépenses : Meta -> ligne Facebook, TikTok Ads -> ligne TikTok, rattachées au
levier Campagne sociale (mêmes périmètres que la carte blended 54643). Volumes :
mart conversions limité au paid (levier Campagne sociale), sinon le social
organique fausserait les coûts. Le filtre source acquisition ne s'applique
qu'aux volumes : les dépenses plateforme ne connaissent pas cette dimension.

Usage : python3 scripts/add_social_detail_28899.py [--yes]
Sans --yes : dry-run (création simulée, aucun écrit).
"""
import argparse
import copy
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from spark_metabase_api import Metabase_API

DASHBOARD_ID = 28899
TAB_LEVIERS = 9870
COLLECTION_ID = 13785          # même collection que les cartes HubSpot Comptastar
VIZ_DONOR = 54646              # Performance par levier : formats € / % des colonnes
MAPPING_DONOR = 54643          # Coût par lead blended : cible des 5 filtres sur Online Only

# Champs Metabase des tags (relevés sur la carte 54643)
FIELD = {
    "comparison_window": 392834,  # metabase_filters.comparison_windows.name
    "date": 419201,               # utils.calendar.date
    "client": 541978,             # HUBSPOT__CONVERSION_DAILY_METRICS.CLIENT_NAME
    "levier": 541987,             # ...LEVIER
    "source_acquisition": 542025, # ...SOURCE_ACQUISITION
}
WIDGET = {
    "comparison_window": "category",
    "date": "date/all-options",
    "client": "category",
    "levier": "string/=",
    "source_acquisition": "string/=",
}
DISPLAY = {
    "comparison_window": "Comparison window",
    "date": "Date",
    "client": "Client",
    "levier": "Levier",
    "source_acquisition": "Source acquisition",
}

# Filtre du dash -> tag de la carte
PARAM_TO_TAG = {
    "91ef07e6": "date",
    "9b4f41fc": "comparison_window",
    "7d429477": "client",
    "79e3c318": "levier",
    "1f54d492": "source_acquisition",
}

CARDS = [
    ("lead", "Leads", "CPL", "Coût par lead — détail campagne sociale (HubSpot)"),
    ("mql", "MQL", "CP MQL", "Coût par MQL — détail campagne sociale (HubSpot)"),
    ("client", "Clients", "CPA", "Coût par client — détail campagne sociale (HubSpot)"),
]

SECTION_TITLE = "# Détail campagne sociale"

SQL = """WITH cw AS (
    SELECT name AS comparison_window FROM metabase_filters.comparison_windows
    WHERE {{{{comparison_window}}}} LIMIT 1
),
get_current_dates AS (
    SELECT MIN(date) AS current_min_date, MAX(date) AS current_max_date, MAX(date) - MIN(date) + 1 AS days
    FROM utils.calendar WHERE {{{{date}}}}
),
get_previous_dates AS (
    SELECT MIN(date) AS previous_min_date, MAX(date) AS previous_max_date
    FROM utils.calendar, cw, get_current_dates AS d
    WHERE TRUE
      AND date >= (CASE WHEN cw.comparison_window = 'previous_period' THEN DATEADD(day, -days, d.current_min_date)
                        WHEN cw.comparison_window = 'previous_month'  THEN DATEADD(month, -1, d.current_min_date)
                        ELSE DATEADD(year, -1, d.current_min_date) END)
      AND date <  (CASE WHEN cw.comparison_window = 'previous_period' THEN d.current_min_date
                        WHEN cw.comparison_window = 'previous_month'  THEN DATEADD(month, -1, DATEADD(day, 1, d.current_max_date))
                        ELSE DATEADD(year, -1, DATEADD(day, 1, d.current_max_date)) END)
),
-- Périmètres : transportent les filtres client et levier vers le côté dépense,
-- qu'un tag ne peut pas viser directement (même mécanique que la carte 54643).
perimetre_client AS (
    SELECT DISTINCT CLIENT_NAME FROM HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS WHERE TRUE [[AND {{{{client}}}}]]
),
perimetre_levier AS (
    SELECT DISTINCT LEVIER FROM HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS WHERE TRUE [[AND {{{{levier}}}}]]
),
-- Dépenses paid par plateforme, rattachées au levier Campagne sociale.
depenses AS (
    SELECT 'Facebook' AS source, m."DATE"::date AS jour, m.cost
    FROM META.META__CAMPAIGN_DAILY_METRICS AS m
    WHERE m.CLIENT_NAME IN (SELECT CLIENT_NAME FROM perimetre_client)
      AND 'Campagne sociale' IN (SELECT LEVIER FROM perimetre_levier)
    UNION ALL
    SELECT 'TikTok', t."DATE"::date, t.cost
    FROM TIKTOK.TIKTOK__CAMPAIGN_DAILY_METRICS AS t
    WHERE t.CLIENT_NAME IN (SELECT CLIENT_NAME FROM perimetre_client)
      AND 'Campagne sociale' IN (SELECT LEVIER FROM perimetre_levier)
),
-- Volumes paid uniquement : la source Facebook contient aussi du social
-- organique (levier Social organique) que les dépenses ne couvrent pas.
conv_courant AS (
    SELECT analytics_source_data_1 AS source, SUM(nb_conversions) AS nb
    FROM HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS, get_current_dates AS d
    WHERE conversion_type = '{conv_type}'
      AND analytics_source_data_1 IN ('Facebook', 'TikTok')
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS.LEVIER = 'Campagne sociale'
      [[AND {{{{client}}}}]] [[AND {{{{levier}}}}]] [[AND {{{{source_acquisition}}}}]]
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS."DATE" >= d.current_min_date
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS."DATE" <= d.current_max_date
    GROUP BY 1
),
conv_precedent AS (
    SELECT analytics_source_data_1 AS source, SUM(nb_conversions) AS nb
    FROM HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS, get_previous_dates AS d
    WHERE conversion_type = '{conv_type}'
      AND analytics_source_data_1 IN ('Facebook', 'TikTok')
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS.LEVIER = 'Campagne sociale'
      [[AND {{{{client}}}}]] [[AND {{{{levier}}}}]] [[AND {{{{source_acquisition}}}}]]
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS."DATE" >= d.previous_min_date
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS."DATE" <= d.previous_max_date
    GROUP BY 1
),
dep_courant AS (
    SELECT source, SUM(cost) AS depense FROM depenses, get_current_dates AS d
    WHERE jour >= d.current_min_date AND jour <= d.current_max_date GROUP BY 1
),
dep_precedent AS (
    SELECT source, SUM(cost) AS depense FROM depenses, get_previous_dates AS d
    WHERE jour >= d.previous_min_date AND jour <= d.previous_max_date GROUP BY 1
),
courant AS (
    SELECT COALESCE(d.source, c.source) AS source, d.depense, COALESCE(c.nb, 0) AS nb,
           d.depense / NULLIF(c.nb, 0) AS cout
    FROM dep_courant AS d FULL OUTER JOIN conv_courant AS c ON c.source = d.source
),
precedent AS (
    SELECT COALESCE(d.source, c.source) AS source, d.depense, COALESCE(c.nb, 0) AS nb,
           d.depense / NULLIF(c.nb, 0) AS cout
    FROM dep_precedent AS d FULL OUTER JOIN conv_precedent AS c ON c.source = d.source
)
SELECT
    c.source  AS "Source",
    c.depense AS "Dépenses",  c.depense / NULLIF(p.depense, 0) - 1 AS "Dépenses (évol.)",
    c.nb      AS "{label_vol}",  c.nb   / NULLIF(p.nb, 0)      - 1 AS "{label_vol} (évol.)",
    c.cout    AS "{label_cost}", c.cout / NULLIF(p.cout, 0)    - 1 AS "{label_cost} (évol.)"
FROM courant AS c LEFT JOIN precedent AS p ON p.source = c.source
ORDER BY c.depense DESC NULLS LAST"""

DESCRIPTION = (
    "{label_cost} par plateforme sociale : ligne Facebook = dépenses Meta, ligne TikTok = "
    "dépenses TikTok Ads. Volumes HubSpot limités au levier Campagne sociale (paid), le "
    "social organique est exclu. Le filtre source acquisition s'applique aux volumes, pas "
    "aux dépenses (l'information n'existe pas côté plateformes). Issue Airtable #21639."
)


def connect():
    env = {}
    for line in open(Path(__file__).resolve().parent.parent / ".env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    return Metabase_API(domain=env["METABASE_DOMAIN"], email=env["METABASE_EMAIL"], password=env["METABASE_PASSWORD"])


def template_tags():
    return {
        name: {
            "id": str(uuid.uuid4()),
            "name": name,
            "display-name": DISPLAY[name],
            "type": "dimension",
            "dimension": ["field", FIELD[name], None],
            "widget-type": WIDGET[name],
            "default": None,
        }
        for name in FIELD
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()

    dash = mb.get(f"/api/dashboard/{DASHBOARD_ID}")
    existing_names = {(dc.get("card") or {}).get("name") for dc in dash["dashcards"]}
    for _, _, _, name in CARDS:
        if name in existing_names:
            print(f"STOP : la carte « {name} » est déjà sur le dashboard.")
            return

    viz = mb.get(f"/api/card/{VIZ_DONOR}")["visualization_settings"]

    # Cibles de mapping copiées sur la tuile Online Only de la carte 54643
    donor_targets = {}
    for dc in dash["dashcards"]:
        if (dc.get("card") or {}).get("id") == MAPPING_DONOR:
            for m in dc.get("parameter_mappings", []):
                if m["parameter_id"] in PARAM_TO_TAG:
                    donor_targets[m["parameter_id"]] = m["target"]
    missing = set(PARAM_TO_TAG) - set(donor_targets)
    if missing:
        print(f"STOP : cibles de mapping introuvables pour {missing}"); return

    # Modèle de tuile texte : le titre de section « # Par source » de l'onglet
    text_vs = None
    for dc in dash["dashcards"]:
        vs = dc.get("visualization_settings") or {}
        if dc.get("dashboard_tab_id") == TAB_LEVIERS and (vs.get("virtual_card") or {}).get("display") == "text":
            text_vs = copy.deepcopy(vs)
            break
    if not text_vs:
        print("STOP : aucune tuile texte modèle sur l'onglet."); return
    text_vs["text"] = SECTION_TITLE

    bottom = max(dc["row"] + dc["size_y"] for dc in dash["dashcards"] if dc.get("dashboard_tab_id") == TAB_LEVIERS)
    print(f"Bas de l'onglet Blended Leviers : row {bottom}")

    if not args.yes:
        print("\nDRY-RUN : 3 cartes + 1 titre seraient créés (lancer avec --yes).")
        for conv_type, label_vol, label_cost, name in CARDS:
            print(f"  - {name} (conversion_type={conv_type}, colonnes {label_vol}/{label_cost})")
        return

    # ── Création des 3 cartes ──────────────────────────────────────────────
    card_ids = []
    for conv_type, label_vol, label_cost, name in CARDS:
        payload = {
            "name": name,
            "description": DESCRIPTION.format(label_cost=label_cost),
            "collection_id": COLLECTION_ID,
            "display": "table",
            "visualization_settings": viz,
            "dataset_query": {
                "database": 144,
                "type": "native",
                "native": {
                    "query": SQL.format(conv_type=conv_type, label_vol=label_vol, label_cost=label_cost),
                    "template-tags": template_tags(),
                },
            },
        }
        r = requests.post(mb.domain + "/api/card", headers=mb.header, auth=mb.auth, json=payload, timeout=120)
        if r.status_code != 200:
            print(f"ERREUR création « {name} » : {r.status_code} {r.text[:400]}"); return
        cid = r.json()["id"]
        card_ids.append(cid)
        # Gotcha pMBQL : vérifier le SQL réellement stocké via stages[].native
        check = mb.get(f"/api/card/{cid}")
        stage = check["dataset_query"].get("stages", [{}])[0]
        native = stage.get("native") or (check["dataset_query"].get("native") or {}).get("query", "")
        ok = "CONVERSION_DAILY_METRICS" in str(native) and f"'{conv_type}'" in str(native)
        print(f"Carte {cid} créée : {name} | SQL stocké vérifié : {'OK' if ok else 'PROBLEME'}")
        if not ok:
            return

    # ── Pose sur le dashboard ──────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    mig = Path(__file__).resolve().parent.parent / "migration"
    mig.mkdir(exist_ok=True)
    backup = mig / f"social-detail-snapshot-{DASHBOARD_ID}-{ts}.json"
    backup.write_text(json.dumps({"dashboard": DASHBOARD_ID, "dashcards": dash["dashcards"], "tabs": dash["tabs"]},
                                 ensure_ascii=False, indent=2))
    print(f"Backup : {backup}")

    dcs = copy.deepcopy(dash["dashcards"])
    dcs.append({
        "id": -1, "card_id": None, "dashboard_tab_id": TAB_LEVIERS,
        "row": bottom, "col": 0, "size_x": 24, "size_y": 1,
        "visualization_settings": text_vs, "parameter_mappings": [],
    })
    for i, cid in enumerate(card_ids):
        mappings = [{"parameter_id": pid, "card_id": cid, "target": donor_targets[pid]} for pid in PARAM_TO_TAG]
        dcs.append({
            "id": -(i + 2), "card_id": cid, "dashboard_tab_id": TAB_LEVIERS,
            "row": bottom + 1 + i * 3, "col": 0, "size_x": 24, "size_y": 3,
            "visualization_settings": {}, "parameter_mappings": mappings,
        })

    r = requests.put(mb.domain + f"/api/dashboard/{DASHBOARD_ID}", headers=mb.header, auth=mb.auth,
                     json={"dashcards": dcs, "tabs": dash["tabs"]}, timeout=120)
    print("PUT dashboard :", r.status_code)
    r.raise_for_status()

    # ── Vérification ───────────────────────────────────────────────────────
    after = mb.get(f"/api/dashboard/{DASHBOARD_ID}")
    names_after = {(dc.get("card") or {}).get("name") for dc in after["dashcards"]}
    for _, _, _, name in CARDS:
        print(f"  {'OK' if name in names_after else 'ABSENTE'} : {name}")
    n_mapped = sum(len(dc.get("parameter_mappings", [])) for dc in after["dashcards"]
                   if (dc.get("card") or {}).get("id") in card_ids)
    print(f"  mappings de filtres posés : {n_mapped} (attendu {3 * len(PARAM_TO_TAG)})")


if __name__ == "__main__":
    main()
