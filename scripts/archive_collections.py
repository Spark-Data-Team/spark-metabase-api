#!/usr/bin/env python3
"""Archive des collections par id (générique, réversible).

- Children-first (tri par profondeur de location) pour gérer les sous-arbres.
- Saute les collections système (type non nul : 'library'… — non archivables).
- Dry-run par défaut ; --yes pour archiver. Écrit la liste pour rollback.

Usage :
  python3 scripts/archive_collections.py --ids 11344,9330,12399          # dry-run
  python3 scripts/archive_collections.py --ids 11344,9330,12399 --yes    # archive
  Rollback : PUT /api/collection/<id> {archived:false} pour les ids du log.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env  # noqa: E402

MIGRATION_DIR = REPO_ROOT / "migration"


def connect_resilient():
    env = _load_env()
    d, e, p = env.get("METABASE_DOMAIN"), env.get("METABASE_EMAIL"), env.get("METABASE_PASSWORD")
    if not (d and e and p):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env.")
    return Metabase_API(domain=d, email=e, password=p)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ids", required=True, help="ids de collections, séparés par des virgules")
    ap.add_argument("--yes", action="store_true", help="archive réellement (sinon dry-run)")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip().isdigit()]

    mb = connect_resilient()
    cols = {c.get("id"): c for c in (mb.get("/api/collection/") or [])}

    def depth(cid):
        return len((cols.get(cid, {}).get("location") or "/").strip("/").split("/"))

    targets = []
    for cid in ids:
        c = cols.get(cid)
        if not c:
            print(f"  #{cid}: absente de l'actif (déjà archivée ?) — sautée")
            continue
        if c.get("type"):
            print(f"  #{cid} «{c.get('name')}» : système (type={c.get('type')}) — sautée")
            continue
        targets.append(cid)
    targets.sort(key=depth, reverse=True)  # enfants avant parents

    print("\nCible :")
    for cid in targets:
        print(f"  #{cid:>6}  «{cols[cid].get('name')}»  ({cols[cid].get('location')})")
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = MIGRATION_DIR / f"archive-collections-{ts}.json"
    log.write_text(json.dumps(targets, indent=2))
    print(f"\nListe / rollback : {log}")

    if not args.yes:
        print("\n(DRY-RUN — rien archivé. --yes pour archiver.)")
        return

    done, miss = [], []
    for cid in targets:
        rc = mb.put(f"/api/collection/{cid}", json={"archived": True})
        if rc == 200:
            done.append(cid)
            print(f"  archivée #{cid} «{cols[cid].get('name')}»")
        else:
            miss.append(cid)
            print(f"  ÉCHEC #{cid} «{cols[cid].get('name')}» (HTTP {rc})")
    print(f"\n=== {len(done)} archivée(s), {len(miss)} échec ===")
    print(f"Rollback : PUT /api/collection/<id> {{archived:false}} pour les ids de {log}")


if __name__ == "__main__":
    main()
