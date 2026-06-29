#!/usr/bin/env python3
"""Range les COPIES de validation (collection 14016, à plat) en SOUS-COLLECTIONS par client, pour
s'y retrouver. Ne touche ni aux originaux ni aux cartes : déplace seulement les dashboards-copies
(leur collection_id) ; les copy_id du tracker ne changent pas.

Usage : python3 scripts/reorg_14016.py            # dry-run (liste les déplacements)
        python3 scripts/reorg_14016.py --yes      # applique
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_collections import connect_resilient
REPO = Path(__file__).resolve().parent.parent
PARENT = 14016


def main():
    yes = "--yes" in sys.argv
    mb = connect_resilient()
    tracker = json.loads((REPO / "migration" / "conv-migration-tracker.json").read_text())
    # sous-collections existantes sous 14016
    existing = {}
    items = mb.get(f"/api/collection/{PARENT}/items?models=collection&limit=500")
    for it in (items.get("data", items) if isinstance(items, dict) else items):
        existing[it.get("name")] = it.get("id")

    def subcoll(client):
        if client in existing:
            return existing[client]
        if not yes:
            return f"(à créer: {client})"
        r = mb.post("/api/collection", json={"name": client, "parent_id": PARENT})
        cid = r.get("id") if isinstance(r, dict) else None
        existing[client] = cid
        return cid

    moves = 0
    for e in tracker:
        client, copy = e.get("client"), e.get("copy_id")
        if not copy: continue
        target = subcoll(client)
        if yes and isinstance(target, int):
            mb.put(f"/api/dashboard/{copy}", "raw", json={"collection_id": target})
        moves += 1
    print(f"{'APPLIQUÉ' if yes else 'DRY-RUN'} : {moves} copies → sous-collections par client sous {PARENT} "
          f"({len(set(e['client'] for e in tracker if e.get('copy_id')))} clients)")


if __name__ == "__main__":
    main()
