#!/usr/bin/env python3
"""Remplace une carte `old` par sa canonique `new` sur TOUS ses dashboards, en
recâblant les filtres, puis archive `old`. Réversible (snapshot des dashboards).

Sécurité :
- Découverte via GET /api/card/<old>/dashboards.
- Garde-fous (swap_lib.swap_safety_check) : `new` non archivée, même base, même
  empreinte fonctionnelle, et couvre TOUS les template-tags câblés vers `old`
  (sinon un filtre casserait) — sinon on REFUSE le swap.
- Avertit si `new` est déjà sur un dashboard de `old` (le repointage créerait une
  tuile en double : préférer retirer la tuile `old`).
- Snapshot des dashcards de chaque dashboard touché avant modification.
- Dry-run par défaut ; `--difftest` compare les résultats des 2 requêtes.

Usage :
  python3 scripts/swap_card_on_dashboards.py --old 35896 --new 35862            # dry-run
  python3 scripts/swap_card_on_dashboards.py --old 35896 --new 35862 --difftest
  python3 scripts/swap_card_on_dashboards.py --old 35896 --new 35862 --yes      # applique + archive old
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
import swap_lib  # noqa: E402

MIGRATION_DIR = REPO_ROOT / "migration"


def connect_resilient():
    env = _load_env()
    d, e, p = env.get("METABASE_DOMAIN"), env.get("METABASE_EMAIL"), env.get("METABASE_PASSWORD")
    if not (d and e and p):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env.")
    return Metabase_API(domain=d, email=e, password=p)


def _dashcards(dash):
    return dash.get("dashcards") or dash.get("ordered_cards") or []


def _difftest(mb, cid):
    """Exécute la carte et retourne (nb lignes, nb colonnes) ou None."""
    r = mb.post(f"/api/card/{cid}/query", json={})
    if not isinstance(r, dict):
        return None
    data = r.get("data", {}) or {}
    return (len(data.get("rows", []) or []), len(data.get("cols", []) or []))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", type=int, required=True, help="carte à retirer")
    ap.add_argument("--new", type=int, required=True, help="carte canonique à garder")
    ap.add_argument("--yes", action="store_true", help="applique (sinon dry-run)")
    ap.add_argument("--difftest", action="store_true", help="exécute et compare les 2 requêtes")
    args = ap.parse_args()

    mb = connect_resilient()
    old = mb.get(f"/api/card/{args.old}")
    new = mb.get(f"/api/card/{args.new}")
    if not isinstance(old, dict) or not isinstance(new, dict):
        sys.exit("Carte old/new introuvable.")
    dashboards = mb.get(f"/api/card/{args.old}/dashboards") or []
    print(f"old #{args.old} «{old.get('name')}» sur {len(dashboards)} dashboard(s)")
    print(f"new #{args.new} «{new.get('name')}»")

    # charge les dashboards + collecte les tags câblés vers old
    dash_full, ref_tags = {}, set()
    for d in dashboards:
        full = mb.get(f"/api/dashboard/{d['id']}")
        if isinstance(full, dict):
            dash_full[d["id"]] = full
            ref_tags |= swap_lib.referenced_template_tags(_dashcards(full), args.old)

    problems = swap_lib.swap_safety_check(old, new, ref_tags)
    if problems:
        print("\n⛔ SWAP REFUSÉ :")
        for p in problems:
            print(f"   - {p}")
        return
    print(f"\n✅ garde-fous OK (filtres câblés : {sorted(ref_tags) or '—'})")

    if args.difftest:
        o, n = _difftest(mb, args.old), _difftest(mb, args.new)
        verdict = "OK identique" if o == n and o is not None else "⚠️ DIFFÉRENT / échec"
        print(f"  difftest (lignes,colonnes) : old={o} new={n} -> {verdict}")

    # plan + détection tuile en double
    plan, warnings, prepared = [], [], {}
    for did, full in dash_full.items():
        dcs = _dashcards(full)
        new_dcs, nch = swap_lib.rewrite_dashcards(dcs, args.old, args.new)
        prepared[did] = new_dcs
        already = any(dc.get("card_id") == args.new for dc in dcs)
        plan.append((did, full.get("name"), nch, already))
        if already:
            warnings.append(did)

    print("\nPlan :")
    for did, name, nch, already in plan:
        flag = "  ⚠️ new déjà présent → tuile en double (préférer retirer la tuile old)" if already else ""
        print(f"  dashboard #{did} «{str(name)[:38]}» : {nch} dashcard(s) repointé(s){flag}")

    if not args.yes:
        print("\n(DRY-RUN — rien modifié. --yes pour appliquer + archiver old.)")
        return
    if warnings:
        print("\n⛔ Tuile en double détectée — j'arrête (résoudre manuellement / retirer la tuile old).")
        return

    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = MIGRATION_DIR / f"swap-snapshot-{args.old}-to-{args.new}-{ts}.json"
    snap.write_text(json.dumps({str(did): {"name": f.get("name"), "dashcards": _dashcards(f)}
                                for did, f in dash_full.items()}, ensure_ascii=False, indent=2))
    print(f"\nSnapshot rollback : {snap}")
    for did in dash_full:
        rc = mb.put(f"/api/dashboard/{did}", json={"dashcards": prepared[did]})
        chk = mb.get(f"/api/dashboard/{did}")
        still = any(dc.get("card_id") == args.old for dc in _dashcards(chk)) if isinstance(chk, dict) else True
        print(f"  dashboard #{did}: PUT={rc} | référence old restante ? {still}")
    remaining = mb.get(f"/api/card/{args.old}/dashboards") or []
    if not remaining:
        rc = mb.put(f"/api/card/{args.old}", json={"archived": True})
        print(f"  old #{args.old} archivée (HTTP {rc})")
    else:
        print(f"  ⚠️ old encore sur {len(remaining)} dashboard(s) — NON archivée")
    print(f"Rollback : restaurer les dashcards depuis {snap}, puis désarchiver old.")


if __name__ == "__main__":
    main()
