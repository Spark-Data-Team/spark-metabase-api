#!/usr/bin/env python3
"""Issue #21639, retour d'Angéline : fusionner les 3 tableaux détail campagne
sociale en un seul (même format que « Performance par levier » : dépenses,
volumes et coûts des 3 conversions avec évolutions, par source Facebook/TikTok).

Crée la carte fusionnée, remplace les 3 tuiles du dash 28899 par une seule,
archive les 3 cartes d'origine (54837/54838/54839).

Usage : python3 scripts/merge_social_detail_28899.py [--yes]
"""
import argparse
import copy
import json
from datetime import datetime
from pathlib import Path

import requests

from add_social_detail_28899 import (
    COLLECTION_ID, DASHBOARD_ID, MAPPING_DONOR, PARAM_TO_TAG, TAB_LEVIERS,
    VIZ_DONOR, connect, template_tags,
)

OLD_CARDS = [54837, 54838, 54839]
NEW_NAME = "Performance par source — campagne sociale (HubSpot)"

DESCRIPTION = (
    "Dépenses, volumes et coûts des 3 conversions par plateforme sociale : ligne Facebook = "
    "dépenses Meta, ligne TikTok = dépenses TikTok Ads. Volumes HubSpot limités au levier "
    "Campagne sociale (paid), le social organique est exclu. Le filtre source acquisition "
    "s'applique aux volumes, pas aux dépenses. Issue Airtable #21639."
)

SQL = """WITH cw AS (
    SELECT name AS comparison_window FROM metabase_filters.comparison_windows
    WHERE {{comparison_window}} LIMIT 1
),
get_current_dates AS (
    SELECT MIN(date) AS current_min_date, MAX(date) AS current_max_date, MAX(date) - MIN(date) + 1 AS days
    FROM utils.calendar WHERE {{date}}
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
    SELECT DISTINCT CLIENT_NAME FROM HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS WHERE TRUE [[AND {{client}}]]
),
perimetre_levier AS (
    SELECT DISTINCT LEVIER FROM HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS WHERE TRUE [[AND {{levier}}]]
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
    SELECT analytics_source_data_1 AS source,
           SUM(CASE WHEN conversion_type = 'lead'   THEN nb_conversions ELSE 0 END) AS leads,
           SUM(CASE WHEN conversion_type = 'mql'    THEN nb_conversions ELSE 0 END) AS mql,
           SUM(CASE WHEN conversion_type = 'client' THEN nb_conversions ELSE 0 END) AS clients
    FROM HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS, get_current_dates AS d
    WHERE conversion_type IN ('lead', 'mql', 'client')
      AND analytics_source_data_1 IN ('Facebook', 'TikTok')
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS.LEVIER = 'Campagne sociale'
      [[AND {{client}}]] [[AND {{levier}}]] [[AND {{source_acquisition}}]]
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS."DATE" >= d.current_min_date
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS."DATE" <= d.current_max_date
    GROUP BY 1
),
conv_precedent AS (
    SELECT analytics_source_data_1 AS source,
           SUM(CASE WHEN conversion_type = 'lead'   THEN nb_conversions ELSE 0 END) AS leads,
           SUM(CASE WHEN conversion_type = 'mql'    THEN nb_conversions ELSE 0 END) AS mql,
           SUM(CASE WHEN conversion_type = 'client' THEN nb_conversions ELSE 0 END) AS clients
    FROM HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS, get_previous_dates AS d
    WHERE conversion_type IN ('lead', 'mql', 'client')
      AND analytics_source_data_1 IN ('Facebook', 'TikTok')
      AND HUBSPOT.HUBSPOT__CONVERSION_DAILY_METRICS.LEVIER = 'Campagne sociale'
      [[AND {{client}}]] [[AND {{levier}}]] [[AND {{source_acquisition}}]]
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
    SELECT COALESCE(d.source, c.source) AS source, d.depense,
           COALESCE(c.leads, 0) AS leads, COALESCE(c.mql, 0) AS mql, COALESCE(c.clients, 0) AS clients,
           d.depense / NULLIF(c.leads, 0) AS cpl,
           d.depense / NULLIF(c.mql, 0) AS cp_mql,
           d.depense / NULLIF(c.clients, 0) AS cpa
    FROM dep_courant AS d FULL OUTER JOIN conv_courant AS c ON c.source = d.source
),
precedent AS (
    SELECT COALESCE(d.source, c.source) AS source, d.depense,
           COALESCE(c.leads, 0) AS leads, COALESCE(c.mql, 0) AS mql, COALESCE(c.clients, 0) AS clients,
           d.depense / NULLIF(c.leads, 0) AS cpl,
           d.depense / NULLIF(c.mql, 0) AS cp_mql,
           d.depense / NULLIF(c.clients, 0) AS cpa
    FROM dep_precedent AS d FULL OUTER JOIN conv_precedent AS c ON c.source = d.source
)
SELECT
    c.source  AS "Source",
    c.depense AS "Dépenses",  c.depense / NULLIF(p.depense, 0) - 1 AS "Dépenses (évol.)",
    c.leads   AS "Leads",     c.leads   / NULLIF(p.leads, 0)   - 1 AS "Leads (évol.)",
    c.cpl     AS "CPL",       c.cpl     / NULLIF(p.cpl, 0)     - 1 AS "CPL (évol.)",
    c.mql     AS "MQL",       c.mql     / NULLIF(p.mql, 0)     - 1 AS "MQL (évol.)",
    c.cp_mql  AS "CP MQL",    c.cp_mql  / NULLIF(p.cp_mql, 0)  - 1 AS "CP MQL (évol.)",
    c.clients AS "Clients",   c.clients / NULLIF(p.clients, 0) - 1 AS "Clients (évol.)",
    c.cpa     AS "CPA",       c.cpa     / NULLIF(p.cpa, 0)     - 1 AS "CPA (évol.)"
FROM courant AS c LEFT JOIN precedent AS p ON p.source = c.source
ORDER BY c.depense DESC NULLS LAST"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()

    dash = mb.get(f"/api/dashboard/{DASHBOARD_ID}")
    names = {(dc.get("card") or {}).get("name") for dc in dash["dashcards"]}
    if NEW_NAME in names:
        print(f"STOP : « {NEW_NAME} » est déjà sur le dashboard."); return

    old_tiles = [dc for dc in dash["dashcards"] if (dc.get("card") or {}).get("id") in OLD_CARDS]
    if len(old_tiles) != 3:
        print(f"STOP : {len(old_tiles)} tuiles à remplacer trouvées (attendu 3)."); return
    top_row = min(dc["row"] for dc in old_tiles)

    donor_targets = {}
    for dc in dash["dashcards"]:
        if (dc.get("card") or {}).get("id") == MAPPING_DONOR:
            for m in dc.get("parameter_mappings", []):
                if m["parameter_id"] in PARAM_TO_TAG:
                    donor_targets[m["parameter_id"]] = m["target"]
    if set(PARAM_TO_TAG) - set(donor_targets):
        print("STOP : cibles de mapping incomplètes."); return

    if not args.yes:
        print(f"DRY-RUN : créerait « {NEW_NAME} », remplacerait les tuiles "
              f"{[dc['id'] for dc in old_tiles]} (row {top_row}) et archiverait {OLD_CARDS}.")
        return

    viz = mb.get(f"/api/card/{VIZ_DONOR}")["visualization_settings"]
    payload = {
        "name": NEW_NAME,
        "description": DESCRIPTION,
        "collection_id": COLLECTION_ID,
        "display": "table",
        "visualization_settings": viz,
        "dataset_query": {
            "database": 144,
            "type": "native",
            "native": {"query": SQL, "template-tags": template_tags()},
        },
    }
    r = requests.post(mb.domain + "/api/card", headers=mb.header, auth=mb.auth, json=payload, timeout=120)
    if r.status_code != 200:
        print(f"ERREUR création : {r.status_code} {r.text[:400]}"); return
    new_id = r.json()["id"]
    check = mb.get(f"/api/card/{new_id}")
    native = str(check["dataset_query"].get("stages", [{}])[0].get("native", ""))
    if "conv_courant" not in native or "CP MQL" not in native:
        print(f"PROBLEME : SQL stocké inattendu sur la carte {new_id}."); return
    print(f"Carte {new_id} créée : {NEW_NAME} | SQL stocké vérifié : OK")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    mig = Path(__file__).resolve().parent.parent / "migration"
    backup = mig / f"social-detail-merge-snapshot-{DASHBOARD_ID}-{ts}.json"
    backup.write_text(json.dumps({"dashboard": DASHBOARD_ID, "dashcards": dash["dashcards"], "tabs": dash["tabs"]},
                                 ensure_ascii=False, indent=2))
    print(f"Backup : {backup}")

    dcs = [copy.deepcopy(dc) for dc in dash["dashcards"] if (dc.get("card") or {}).get("id") not in OLD_CARDS]
    dcs.append({
        "id": -1, "card_id": new_id, "dashboard_tab_id": TAB_LEVIERS,
        "row": top_row, "col": 0, "size_x": 24, "size_y": 3,
        "visualization_settings": {},
        "parameter_mappings": [{"parameter_id": pid, "card_id": new_id, "target": donor_targets[pid]}
                               for pid in PARAM_TO_TAG],
    })
    r = requests.put(mb.domain + f"/api/dashboard/{DASHBOARD_ID}", headers=mb.header, auth=mb.auth,
                     json={"dashcards": dcs, "tabs": dash["tabs"]}, timeout=120)
    print("PUT dashboard :", r.status_code)
    r.raise_for_status()

    for cid in OLD_CARDS:
        r = requests.put(mb.domain + f"/api/card/{cid}", headers=mb.header, auth=mb.auth,
                         json={"archived": True}, timeout=120)
        flag = mb.get(f"/api/card/{cid}").get("archived")
        print(f"Carte {cid} archivée : {r.status_code}, archived={flag}")

    after = mb.get(f"/api/dashboard/{DASHBOARD_ID}")
    tile = next((dc for dc in after["dashcards"] if (dc.get("card") or {}).get("id") == new_id), None)
    gone = [cid for cid in OLD_CARDS if any((dc.get("card") or {}).get("id") == cid for dc in after["dashcards"])]
    print(f"Tuile fusionnée présente : {'OUI' if tile else 'NON'} "
          f"({len(tile['parameter_mappings'])} mappings) | anciennes tuiles restantes : {gone or 'aucune'}")


if __name__ == "__main__":
    main()
