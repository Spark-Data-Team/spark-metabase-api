#!/usr/bin/env python3
"""Archive les cartes « périmées » (0 dashboard, dormantes ≥ seuil) issues de l'audit. Réversible.

Sécurité :
- Source = dernier audit-findings (unused_cards avec stale=True). Récence = last_used_at.
- Re-vérification LIVE avant chaque archivage : dashboard_count==0 ET non archivée
  (instance active — saute si la carte a été remise sur un dashboard depuis le scan).
- Exclut par défaut : template (collection sous /215/) et cartes en collection personnelle.
- Réversible (PUT archived:false). Écrit rollback JSON + CSV de relecture.

Usage :
  python3 scripts/archive_stale_cards.py                       # dry-run (catégorise)
  python3 scripts/archive_stale_cards.py --yes                 # archive le set "safe"
  python3 scripts/archive_stale_cards.py --min-days 365 --yes  # dormance ≥ 1 an
  python3 scripts/archive_stale_cards.py --include-template --include-personal --exclude 1,2
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env  # noqa: E402
import audit_lib  # noqa: E402

MIGRATION_DIR = REPO_ROOT / "migration"
CACHE_DIR = MIGRATION_DIR / "audit-cache"
TEMPLATE_ROOT_ID = 215


def connect_resilient():
    env = _load_env()
    d, e, p = env.get("METABASE_DOMAIN"), env.get("METABASE_EMAIL"), env.get("METABASE_PASSWORD")
    if not (d and e and p):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env.")
    return Metabase_API(domain=d, email=e, password=p)


def _latest_findings():
    fs = sorted(MIGRATION_DIR.glob("audit-findings-*.json"))
    if not fs:
        sys.exit("Aucun audit-findings : lancer `audit.py scan` puis `deep`.")
    return json.loads(fs[-1].read_text())


def _collection_id(card_id):
    f = CACHE_DIR / f"card-{card_id}.json"
    if f.exists():
        try:
            return json.loads(f.read_text()).get("collection_id")
        except Exception:
            return None
    return None


# marqueur humain explicite « ne pas toucher » sur un nom de collection
_FROZEN_RE = re.compile(r"do not modify|do not touch|ne pas (?:modifier|toucher)|☠", re.I)


def _zone(coll_id, cols):
    """frozen (marqueur 'ne pas toucher'), template (/215/), personal, ou other."""
    if coll_id is None:
        return "other"
    col = cols.get(coll_id) or {}
    loc = col.get("location") or ""
    anc_ids = [coll_id] + [int(p) for p in loc.strip("/").split("/") if p.isdigit()]
    for i in anc_ids:
        if _FROZEN_RE.search((cols.get(i) or {}).get("name") or ""):
            return "frozen"
    for i in anc_ids:
        if (cols.get(i) or {}).get("personal_owner_id"):
            return "personal"
    if coll_id == TEMPLATE_ROOT_ID or f"/{TEMPLATE_ROOT_ID}/" in loc:
        return "template"
    return "other"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--yes", action="store_true", help="archive réellement (sinon dry-run)")
    ap.add_argument("--min-days", type=int, default=audit_lib.STALE_DAYS,
                    help=f"seuil de dormance en jours (défaut {audit_lib.STALE_DAYS})")
    ap.add_argument("--include-template", action="store_true")
    ap.add_argument("--include-personal", action="store_true")
    ap.add_argument("--exclude", default="", help="ids de cartes à retirer, séparés par des virgules")
    ap.add_argument("--exclude-collection", default="",
                    help="ids de collections à exclure entièrement, séparés par des virgules")
    args = ap.parse_args()
    exclude = {int(x) for x in args.exclude.split(",") if x.strip().isdigit()}
    exclude_cols = {int(x) for x in args.exclude_collection.split(",") if x.strip().isdigit()}

    blob = _latest_findings()
    items = blob["findings"]["unused_cards"]["items"]
    stale = [c for c in items if c.get("stale") and (c.get("days_since_used") or 0) >= args.min_days]

    mb = connect_resilient()
    cols = {c.get("id"): c for c in (mb.get("/api/collection/") or [])}

    buckets = {"other": [], "template": [], "personal": [], "frozen": []}
    for c in stale:
        coll = _collection_id(c["id"])
        z = _zone(coll, cols)
        buckets[z].append({**c, "collection_id": coll, "collection": (cols.get(coll) or {}).get("name")})

    print(f"Cartes périmées ≥{args.min_days}j : {len(stale)}")
    for z in ("other", "template", "personal", "frozen"):
        print(f"  {z:9}: {len(buckets[z])}")

    target = list(buckets["other"])
    if args.include_template:
        target += buckets["template"]
    if args.include_personal:
        target += buckets["personal"]
    target = [c for c in target if c["id"] not in exclude and c.get("collection_id") not in exclude_cols]
    target.sort(key=lambda x: -(x.get("days_since_used") or 0))

    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    review = MIGRATION_DIR / f"stale-cards-review-{ts}.csv"
    with review.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["zone", "id", "nom", "collection", "jours_inactif", "vues", "last_used_at"])
        for z in ("other", "template", "personal"):
            for c in sorted(buckets[z], key=lambda x: -(x.get("days_since_used") or 0)):
                w.writerow([z, c["id"], c.get("name"), c.get("collection"),
                            c.get("days_since_used"), c.get("view_count"), c.get("last_used_at")])
    log = MIGRATION_DIR / f"archive-stale-cards-{ts}.json"
    log.write_text(json.dumps([c["id"] for c in target], indent=2))
    print(f"\nCible (safe, ≥{args.min_days}j, hors template/perso) : {len(target)} cartes")
    print(f"CSV de relecture : {review}")
    print(f"Rollback : {log}")
    print("\nTop 12 plus dormantes de la cible :")
    for c in target[:12]:
        print(f"  #{c['id']:>6} {str(c.get('name'))[:36]:36} {c.get('days_since_used')}j, "
              f"{c.get('view_count')} vues  [{str(c.get('collection'))[:24]}]")

    if not args.yes:
        print("\n(DRY-RUN — rien archivé. --yes pour archiver.)")
        return

    print(f"\n=== Archivage de {len(target)} cartes (re-vérif live)... ===")
    done, skip = [], []
    for c in target:
        cid = c["id"]
        live = mb.get(f"/api/card/{cid}")
        if not isinstance(live, dict):
            print(f"  SAUTÉ #{cid} : lecture KO")
            skip.append(cid)
            continue
        if live.get("archived"):
            skip.append(cid)
            continue
        if live.get("dashboard_count", 0) != 0:
            print(f"  SAUTÉ #{cid} «{c.get('name')}» : {live['dashboard_count']} dashboard(s) maintenant")
            skip.append(cid)
            continue
        rc = mb.put(f"/api/card/{cid}", json={"archived": True})
        if rc == 200:
            done.append(cid)
        else:
            print(f"  ÉCHEC #{cid} (HTTP {rc})")
            skip.append(cid)
    print(f"\n=== {len(done)} archivée(s), {len(skip)} sautée(s) ===")
    print(f"Rollback : PUT /api/card/<id> {{archived:false}} pour les ids de {log}")


if __name__ == "__main__":
    main()
