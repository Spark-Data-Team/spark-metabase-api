#!/usr/bin/env python3
"""Retire les cartes qui lisent des modèles dbt supprimés (campagne erreurs 2026-08-13).

Ces cartes ne sont pas réparables depuis Metabase : la table qu'elles interrogent n'existe
plus dans Snowflake. On retire d'abord leurs tuiles des dashboards vivants (sinon le
dashboard garde une tuile morte), puis on met la carte à la corbeille.

Chaque dashboard touché est sauvegardé en entier avant écriture.

    python scripts/purge_dead_model_cards.py                 # dry-run
    python scripts/purge_dead_model_cards.py --yes           # applique
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fix_dashboard_wiring import BACKUP_DIR, CAMPAIGN_DIR, connect  # noqa: E402

# carte -> table Snowflake disparue, pour la traçabilité du journal
CARDS = {
    16637: "FORECAST.MODEL_DAILY_METRICS",
    16531: "FORECAST.MODEL_DAILY_METRICS",
    16905: "FORECAST.MODEL_DAILY_METRICS",
    16906: "FORECAST.MODEL_DAILY_METRICS",
    27758: "ALERTS.CLIENT_ALERTS",
    33981: "META.META__ADSET_DAILY_METRICS_PER_PLACEMENT",
}


def live_dashboards(domain, s, card_id):
    r = s.get(f"{domain}/api/card/{card_id}/dashboards", timeout=60)
    out = []
    for x in r.json() if r.status_code == 200 else []:
        d = s.get(f'{domain}/api/dashboard/{x["id"]}', timeout=90).json()
        if d.get("archived"):
            continue  # /dashboards renvoie aussi les dashboards à la corbeille
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--yes", action="store_true", help="applique réellement (sinon dry-run)")
    args = ap.parse_args()
    domain, s = connect()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    journal = []

    for card_id, table in CARDS.items():
        card = s.get(f"{domain}/api/card/{card_id}", timeout=60).json()
        print(f'\n#{card_id} «{card.get("name")}» → {table}')
        for d in live_dashboards(domain, s, card_id):
            did = d["id"]
            tiles = [
                dc
                for dc in d["dashcards"]
                if dc.get("card_id") == card_id
                or any(x.get("card_id") == card_id for x in (dc.get("series") or []))
            ]
            print(f'   dash {did} «{d.get("name")}» : retire {len(tiles)} tuile(s)')
            if not args.yes:
                continue
            (BACKUP_DIR / f"dashboard-{did}-{stamp}.json").write_text(
                json.dumps(d, ensure_ascii=False, indent=1)
            )
            keep = [dc for dc in d["dashcards"] if dc not in tiles]
            body = {"dashcards": keep}
            if d.get("tabs"):
                body["tabs"] = d["tabs"]
            r = s.put(f"{domain}/api/dashboard/{did}", json=body, timeout=180)
            print(f"     PUT dashboard {did} → {r.status_code}")
            journal.append({"dash": did, "card": card_id, "tiles": [t["id"] for t in tiles]})

        if args.yes:
            (BACKUP_DIR / f"card-{card_id}-{stamp}.json").write_text(
                json.dumps(card, ensure_ascii=False, indent=1)
            )
            r = s.put(f"{domain}/api/card/{card_id}", json={"archived": True}, timeout=120)
            print(f"   corbeille carte {card_id} → {r.status_code}")
            journal.append({"card": card_id, "archived": r.status_code < 300, "table": table})

    if args.yes:
        out = CAMPAIGN_DIR / f"purge-dead-models-{stamp}.json"
        out.write_text(json.dumps(journal, ensure_ascii=False, indent=1))
        print(f"\njournal : {out}")


if __name__ == "__main__":
    main()
