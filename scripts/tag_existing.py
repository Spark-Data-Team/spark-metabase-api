#!/usr/bin/env python3
"""Applique l'ancre [conv-2026-06] au NOM des dashboards déjà migrés (tracker, tagged=false).

Idempotent (conv_tracker.apply_tag) et réversible (retirer le suffixe). Dry-run par défaut ;
--yes renomme réellement, met `tagged: true` dans le tracker + régénère le markdown.
PUT tolérant aux onglets (inclut `tabs` si présents, sinon 500).

Usage :
  python3 scripts/tag_existing.py          # dry-run : montre les renommages
  python3 scripts/tag_existing.py --yes      # applique
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
    ap.add_argument("--yes", action="store_true", help="renomme réellement (sinon dry-run)")
    args = ap.parse_args()

    tracker = T.load()
    todo = [e for e in tracker if not e.get("tagged")]
    if not todo:
        print("Toutes les copies du tracker sont déjà taggées.")
        return

    mb = connect_resilient()
    print(f"{len(todo)} copie(s) à taguer :\n")
    done = 0
    for e in tracker:
        if e.get("tagged"):
            continue
        cid = e["copy_id"]
        d = mb.get(f"/api/dashboard/{cid}")
        if not d:
            print(f"  ⛔ #{cid} introuvable — sauté"); continue
        old = d.get("name", "")
        new = T.apply_tag(old)
        if new == old:                       # déjà taggé côté Metabase
            print(f"  = #{cid} déjà taggé : «{old}»")
            e["tagged"] = True; done += 1; continue
        if not args.yes:
            print(f"  [dry-run] #{cid} «{old}»  →  + {T.TAG}")
            continue
        body = {"name": new}
        if d.get("tabs"):                    # dashboards à onglets : PUT doit inclure tabs
            body["tabs"] = d["tabs"]
        res = mb.put(f"/api/dashboard/{cid}", "raw", json=body)
        ok = res.ok and (mb.get(f"/api/dashboard/{cid}") or {}).get("name") == new
        if ok:
            e["tagged"] = True; done += 1
            print(f"  ✅ #{cid} → «{new}»")
        else:
            print(f"  ❌ #{cid} échec PUT {res.status_code} {res.text[:140]}")

    if args.yes and done:
        T.save(tracker); T.render_to_file(tracker)
        print(f"\n{done} copie(s) taguée(s). Tracker + markdown mis à jour. "
              f"Rollback : retirer le suffixe {T.TAG} du nom.")
    elif not args.yes:
        print(f"\n(DRY-RUN — rien renommé. --yes pour appliquer.)")


if __name__ == "__main__":
    main()
