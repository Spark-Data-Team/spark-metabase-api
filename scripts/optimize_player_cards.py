#!/usr/bin/env python3
"""Optimise les 2 cartes "joueurs" (29452, 46988) : remplace la boucle per-place
(SUM sur ~100 appels API) par UN SEUL appel passant LISTAGG(DISTINCT place).

Le préfixe d'origine (CTE dates/filtres/map_place_parameter) est conservé verbatim ;
seule la partie qui bouclait est réécrite. Garde-fou `pl.n > 0` : si le filtre ville
ne matche aucun slug -> 0 ligne (jamais "tous les centres" par erreur).

  python3 scripts/optimize_player_cards.py            # dry-run (diff)
  python3 scripts/optimize_player_cards.py --yes      # applique + backup
"""
import sys, json, copy, argparse, difflib
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
MIG = REPO / "migration"

TAIL_29452 = """places_list AS (

    SELECT
        LISTAGG(DISTINCT place, ',') AS places,
        COUNT(*) AS n

    FROM map_place_parameter

),

final AS (

    (
    SELECT
        current_max_date AS display_date,
        client_data.fetch_quiz_room_player_nb(
            current_min_date,
            current_max_date,
            pl.places
        ):player_count::INT AS player_count

    FROM places_list pl, get_current_dates

    WHERE pl.n > 0
    )

    UNION ALL

    (
    SELECT
        previous_max_date AS display_date,
        client_data.fetch_quiz_room_player_nb(
            previous_min_date,
            previous_max_date,
            pl.places
        ):player_count::INT AS player_count

    FROM places_list pl, get_previous_dates

    WHERE pl.n > 0
    )

)

SELECT * FROM final
ORDER BY display_date ASC"""

TAIL_46988 = """places_list AS (
    SELECT
        LISTAGG(DISTINCT place, ',') AS places,
        COUNT(*) AS n
    FROM map_place_parameter
),
current_year AS (
    SELECT
        m.month_label,
        m.month_start AS display_date,
        m.offset,
        'N' AS year_group,
        client_data.fetch_quiz_room_player_nb(
            m.month_start,
            m.month_end,
            pl.places
        ):player_count::INT AS player_count
    FROM months m, places_list pl
    WHERE pl.n > 0
),
previous_year AS (
    SELECT
        m.month_label,
        DATEADD(year, -1, m.month_start) AS display_date,
        m.offset,
        'N-1' AS year_group,
        client_data.fetch_quiz_room_player_nb(
            DATEADD(year, -1, m.month_start),
            DATEADD(year, -1, m.month_end),
            pl.places
        ):player_count::INT AS player_count
    FROM months m, places_list pl
    WHERE pl.n > 0
),
final AS (
    SELECT * FROM current_year
    UNION ALL
    SELECT * FROM previous_year
)
SELECT
    month_label,
    year_group,
    player_count
FROM final
ORDER BY offset DESC, year_group DESC"""

CARDS = {
    29452: {"split": "\n\nfinal AS (", "join": "\n\n", "tail": TAIL_29452},
    46988: {"split": "\ncurrent_year AS (", "join": "\n", "tail": TAIL_46988},
}


def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])


def native_stage(dq):
    for st in dq.get("stages") or []:
        if st.get("native"):
            return st
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    for cid, cfg in CARDS.items():
        c = mb.get(f"/api/card/{cid}")
        dq = copy.deepcopy(c["dataset_query"])
        st = native_stage(dq)
        old = st["native"]
        assert cfg["split"] in old, f"split marker not found in {cid}"
        prefix = old.split(cfg["split"])[0]
        new = prefix + cfg["join"] + cfg["tail"]
        # sanity: no more SUM( player calls, places_list present, n>0 guard present
        assert "SUM(" not in new, f"{cid}: SUM still present"
        assert "places_list" in new and "pl.n > 0" in new, f"{cid}: guard missing"
        print(f"========== card {cid} DIFF ==========")
        for line in difflib.unified_diff(old.splitlines(), new.splitlines(),
                                         lineterm="", n=2):
            print(line)
        print()
        if args.yes:
            (MIG / f"player-card-{cid}-snapshot-{ts}.json").write_text(
                json.dumps(c["dataset_query"], ensure_ascii=False, indent=2))
            st["native"] = new
            import requests
            r = requests.put(mb.domain + f"/api/card/{cid}", headers=mb.header,
                             auth=mb.auth, json={"dataset_query": dq}, timeout=120)
            print(f"PUT card {cid}: {r.status_code}")
            r.raise_for_status()


if __name__ == "__main__":
    main()
