#!/usr/bin/env python3
"""Archive les ANCIENS dashboards remplacés par une copie migrée (delete-by-presence, réversible).

Pilote = migration/conv-migration-tracker.json. N'archive QUE les lignes avec `archive_old: true`
(OPT-IN explicite), dont l'original est connu et pas déjà archivé. Garde-fou : refuse d'archiver un
dashboard qui porte l'ancre [conv-2026-06] (= jamais une copie neuve).

⚠️ On n'archive JAMAIS « tout ce qui n'a pas le tag » (delete-by-absence) : on cible UNIQUEMENT les
anciens explicitement marqués dans le tracker. Archivage Metabase = réversible (PUT archived:false).

Dry-run par défaut. --yes archive réellement.

Usage :
  python3 scripts/archive_superseded.py          # dry-run : liste ce qui serait archivé
  python3 scripts/archive_superseded.py --yes     # archive + marque old_archived dans le tracker
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import conv_tracker as T  # noqa: E402
from archive_collections import connect_resilient  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--yes", action="store_true", help="archive réellement (sinon dry-run)")
    args = ap.parse_args()

    tracker = T.load()
    ids = set(T.archivable_originals(tracker))
    if not ids:
        print("Rien à archiver : aucune ligne `archive_old: true` (original connu, non archivé).")
        print("→ Pose `archive_old: true` sur les lignes validées du tracker pour activer l'archivage.")
        return

    mb = connect_resilient()
    print(f"{len(ids)} ancien(s) candidat(s) à l'archivage :\n")
    done = 0
    for e in tracker:
        if e.get("original_id") not in ids or e.get("old_archived"):
            continue
        oid = e["original_id"]
        d = mb.get(f"/api/dashboard/{oid}")
        name = d.get("name") if d else None
        if name is None:
            print(f"  ⛔ #{oid} introuvable — sauté"); continue
        if T.is_tagged(name):
            print(f"  🛡️  #{oid} «{name}» porte l'ancre {T.TAG} → REFUSÉ (c'est une copie neuve)")
            continue
        if not args.yes:
            print(f"  [dry-run] archiverait #{oid} «{name[:48]}» "
                  f"(remplacé par copie {e.get('copy_id')}, {e.get('client')})")
            continue
        res = mb.put(f"/api/dashboard/{oid}", "raw", json={"archived": True})
        ok = res.ok and (mb.get(f"/api/dashboard/{oid}") or {}).get("archived") is True
        if ok:
            e["old_archived"] = True; done += 1
            print(f"  ✅ #{oid} «{name[:48]}» archivé (réversible)")
        else:
            print(f"  ❌ #{oid} échec PUT {res.status_code} {res.text[:160]}")

    if args.yes and done:
        T.save(tracker); T.render_to_file(tracker)
        print(f"\n{done} ancien(s) archivé(s). Tracker + markdown mis à jour. Rollback : PUT archived:false.")
    elif not args.yes:
        print("\n(DRY-RUN — rien archivé. --yes pour archiver.)")


if __name__ == "__main__":
    main()
