#!/usr/bin/env python3
"""Archive les cartes non utilisées (0 dashboard) de la collection 215.

Sécurité :
- Scan complet des requêtes pour repérer les cartes utilisées comme SOURCE d'une
  autre carte (`card__<id>`) — on ne les archive jamais (casserait la dépendante).
- Re-vérification live du `dashboard_count` juste avant chaque archivage ; saute
  si la carte a été ajoutée à un dashboard entre-temps (instance active).
- Connexion email/password (résiste à l'expiration de session sur ce run long).
- L'archivage est réversible (désarchivage possible).

Usage :
  python3 scripts/prune_unused.py            # dry-run : liste les candidates
  python3 scripts/prune_unused.py --yes      # archive réellement
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env, _check  # noqa: E402

ROOT_COLLECTION_ID = 215
EXCLUDE_COLLECTION_ID = 11673
MIGRATION_DIR = REPO_ROOT / "migration"
_CARD_SRC_RE = re.compile(r"card__(\d+)")


def connect_resilient() -> Metabase_API:
    """Connexion email/password (l'objet peut se ré-authentifier si la session expire)."""
    env = _load_env()
    domain = env.get("METABASE_DOMAIN")
    email = env.get("METABASE_EMAIL")
    password = env.get("METABASE_PASSWORD")
    if not (domain and email and password):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env pour ce run long.")
    return Metabase_API(domain=domain, email=email, password=password)


def scan(mb):
    """Parcourt 215 (hors Conversions). Retourne (cards, source_ids).

    cards : list de dicts {id, name, dashboard_count, archived}
    source_ids : set des id de cartes référencées comme source par une autre carte
    """
    cards = []
    source_ids = set()

    def walk(cid):
        items = mb.get(f"/api/collection/{cid}/items?limit=2000").get("data", [])
        for it in items:
            if it["model"] == "collection":
                if it["id"] != EXCLUDE_COLLECTION_ID:
                    walk(it["id"])
            elif it["model"] in ("card", "dataset"):
                detail = mb.get(f"/api/card/{it['id']}")
                cards.append({
                    "id": detail["id"],
                    "name": detail["name"],
                    "dashboard_count": detail.get("dashboard_count", 0),
                    "archived": bool(detail.get("archived", False)),
                })
                qs = json.dumps(detail.get("dataset_query", {}))
                for m in _CARD_SRC_RE.findall(qs):
                    source_ids.add(int(m))

    walk(ROOT_COLLECTION_ID)
    return cards, source_ids


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    mb = connect_resilient()
    print(f"Scan complet de la collection {ROOT_COLLECTION_ID} (hors Conversions)...")
    cards, source_ids = scan(mb)
    print(f"  {len(cards)} cartes scannées ; "
          f"{len(source_ids)} cartes utilisées comme source par une autre")

    # Candidates : 0 dashboard, non archivées, non utilisées comme source
    candidates = [c for c in cards
                  if c["dashboard_count"] == 0
                  and not c["archived"]
                  and c["id"] not in source_ids]
    protected = [c for c in cards
                 if c["dashboard_count"] == 0
                 and not c["archived"]
                 and c["id"] in source_ids]

    print(f"\n=== {len(candidates)} candidates à archiver (0 dashboard, pas source) ===")
    for c in sorted(candidates, key=lambda x: x["name"]):
        print(f"  #{c['id']:>6}  {c['name']}")
    if protected:
        print(f"\n=== {len(protected)} protégées (0 dashboard MAIS source d'une autre carte) ===")
        for c in protected:
            print(f"  #{c['id']:>6}  {c['name']}")

    # Sauvegarde de la liste pour rollback (désarchivage)
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = MIGRATION_DIR / f"prune-candidates-{ts}.json"
    log.write_text(json.dumps([c["id"] for c in candidates], indent=2))
    print(f"\nListe candidates : {log}")

    if not args.yes:
        print("\n(DRY-RUN — rien archivé. Relancer avec --yes pour archiver.)")
        return

    print(f"\n=== Archivage (re-vérification live de chaque carte)... ===")
    archived, skipped = [], []
    for c in candidates:
        cid = c["id"]
        live = mb.get(f"/api/card/{cid}")
        if live is False:
            print(f"  SAUTÉ #{cid} : lecture échouée"); skipped.append(cid); continue
        if live.get("dashboard_count", 0) != 0:
            print(f"  SAUTÉ #{cid} «{c['name']}» : maintenant "
                  f"{live['dashboard_count']} dashboard(s)"); skipped.append(cid); continue
        if live.get("archived"):
            skipped.append(cid); continue
        _check(mb.put(f"/api/card/{cid}", json={"archived": True}),
               f"archivage carte {cid}")
        archived.append(cid)
        print(f"  archivée #{cid} «{c['name']}»")

    print(f"\n=== {len(archived)} archivée(s), {len(skipped)} sautée(s) ===")
    print(f"Rollback : désarchiver les ids de {log} "
          f"(PUT /api/card/<id> {{archived:false}}).")


if __name__ == "__main__":
    main()
