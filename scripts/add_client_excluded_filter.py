#!/usr/bin/env python3
"""Ajoute le filtre « Client Excluded » aux dashboards benchmark Nanga qui ne l'ont pas.

Les cartes benchmark Nanga écrivent `AND client_id != {{client_excluded}}` hors doubles
crochets : la variable est donc obligatoire, et une tuile dont aucun filtre ne l'alimente
ne peut jamais s'exécuter. Le dashboard 11841 « Benchmark | Google Ads » porte la
convention maison : un filtre dédié `string/=` nommé « Client Excluded », câblé en
`["variable", ["template-tag", "client_excluded"]]`. Ce script la réplique.

    python scripts/add_client_excluded_filter.py --dash 11763            # dry-run
    python scripts/add_client_excluded_filter.py --dash 11763 --yes      # applique
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fix_dashboard_wiring import (  # noqa: E402
    BACKUP_DIR,
    card_tags,
    connect,
    target_tag,
)

TAG = "client_excluded"
# Copiée telle quelle du dashboard 11841, hors `id` qui doit être unique par dashboard.
PARAM_TEMPLATE = {
    "name": "Client Excluded",
    "slug": "client_excluded",
    "type": "string/=",
    "sectionId": "string",
    "values_query_type": "list",
}


def param_id_for(dash_id):
    """Identifiant stable à 8 hex, pour que deux passages ne créent pas deux filtres."""
    return hashlib.sha1(f"client_excluded-{dash_id}".encode()).hexdigest()[:8]


def cards_of(dashcard):
    ids = [dashcard.get("card_id")]
    ids += [s.get("id") or s.get("card_id") for s in (dashcard.get("series") or [])]
    return [c for c in ids if c]


def process(domain, s, dash_id, dry_run=True):
    d = s.get(f"{domain}/api/dashboard/{dash_id}", timeout=90).json()
    if d.get("archived"):
        print(f"  #{dash_id} archivé, ignoré")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"dashboard-{dash_id}-{stamp}.json"
    backup.write_text(json.dumps(d, ensure_ascii=False, indent=1))

    params = d.get("parameters") or []
    existing = next((p for p in params if p.get("slug") == TAG or p.get("name") == "Client Excluded"), None)
    if existing:
        pid = existing["id"]
        print(f"  filtre déjà présent (id {pid})")
    else:
        pid = param_id_for(dash_id)
        params = params + [dict(PARAM_TEMPLATE, id=pid)]
        print(f"  + filtre « Client Excluded » (id {pid})")

    tag_cache = {}
    added = 0
    for dc in d.get("dashcards") or []:
        already = {
            pm.get("card_id")
            for pm in (dc.get("parameter_mappings") or [])
            if target_tag(pm.get("target")) == TAG
        }
        for cid in cards_of(dc):
            if cid in already:
                continue
            if cid not in tag_cache:
                tag_cache[cid] = card_tags(s.get(f"{domain}/api/card/{cid}", timeout=60).json())
            if TAG not in tag_cache[cid]:
                continue
            dc.setdefault("parameter_mappings", []).append(
                {"parameter_id": pid, "card_id": cid, "target": ["variable", ["template-tag", TAG]]}
            )
            added += 1

    if dry_run:
        print(f"  DRY-RUN #{dash_id} : {added} tuiles seraient câblées (backup {backup.name})")
        return

    body = {"parameters": params, "dashcards": d["dashcards"]}
    if d.get("tabs"):
        # Un dashboard à onglets exige `tabs` dans le PUT, sinon 500 sur la contrainte FK.
        body["tabs"] = d["tabs"]
    r = s.put(f"{domain}/api/dashboard/{dash_id}", json=body, timeout=180)
    if r.status_code >= 300:
        print(f"  ÉCHEC #{dash_id} : HTTP {r.status_code} {r.text[:300]}")
        return
    print(f"  OK #{dash_id} : {added} tuiles câblées (backup {backup.name})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dash", type=int, action="append", required=True)
    ap.add_argument("--yes", action="store_true", help="applique réellement (sinon dry-run)")
    args = ap.parse_args()

    domain, s = connect()
    for did in args.dash:
        print(f"\nDASH #{did}")
        process(domain, s, did, dry_run=not args.yes)


if __name__ == "__main__":
    main()
