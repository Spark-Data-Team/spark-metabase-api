#!/usr/bin/env python3
"""CLI de migration Phase 1 de la collection Metabase « 2. Generic Questions ».

Sous-commandes : snapshot | plan | apply | verify | rollback.
Voir docs/superpowers/specs/2026-05-20-generic-questions-reorg-phase1-design.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_lib import (capture_state, ROOT_COLLECTION_ID,  # noqa: E402
                       load_plan, compute_lots, MetabaseState,
                       verify_invariant)

MIGRATION_DIR = REPO_ROOT / "migration"


def _load_env() -> dict:
    """Lit les paires KEY=VALUE de .env (sans dépendance externe)."""
    env = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def connect() -> Metabase_API:
    """Connexion Metabase depuis .env (session_id prioritaire)."""
    env = _load_env()
    domain = env.get("METABASE_DOMAIN") or os.environ.get("METABASE_DOMAIN")
    session_id = env.get("METABASE_SESSION_ID") or os.environ.get("METABASE_SESSION_ID")
    email = env.get("METABASE_EMAIL") or os.environ.get("METABASE_EMAIL")
    password = env.get("METABASE_PASSWORD") or os.environ.get("METABASE_PASSWORD")
    if not domain:
        sys.exit("METABASE_DOMAIN manquant (.env ou environnement).")
    if session_id:
        mb = Metabase_API(domain=domain, session_id=session_id)
        if mb.is_session_valid():
            return mb
        print("session_id expiré — bascule sur email/password.")
    if not (email and password):
        sys.exit("Aucune session valide et METABASE_EMAIL/PASSWORD manquants.")
    return Metabase_API(domain=domain, email=email, password=password)


def cmd_snapshot(args):
    mb = connect()
    print(f"Capture du sous-arbre de la collection {ROOT_COLLECTION_ID}...")
    state = capture_state(mb.get, root_id=ROOT_COLLECTION_ID)
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = MIGRATION_DIR / f"snapshot-{ts}.json"
    out.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False))
    print(f"  {len(state.collections)} collections, {len(state.cards)} cartes")
    print(f"Snapshot écrit : {out}")


def cmd_plan(args):
    state = MetabaseState.from_dict(json.loads(Path(args.snapshot).read_text()))
    plan = load_plan(args.plan)
    lots = compute_lots(state, plan)
    total = 0
    for lot_name in (f"lot-{i}" for i in range(1, 6)):
        ops = lots[lot_name]
        print(f"\n=== {lot_name} ({len(ops)} opérations) ===")
        for op in ops:
            print(f"  - {op.summary}")
        total += len(ops)
    print(f"\nTotal : {total} opérations. (DRY-RUN — rien n'a été modifié.)")


FAMILIES_FILE_NAME = "families.json"


def _families_path():
    return MIGRATION_DIR / FAMILIES_FILE_NAME


def _check(status, what):
    """`mb.put` renvoie un code HTTP — on échoue fort si non-2xx."""
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"{what} a échoué — HTTP {status}")


def _exec_op(mb, op, family_ids):
    if op.kind == "create_collection":
        coll = mb.create_collection(
            collection_name=op.payload["name"],
            parent_collection_id=ROOT_COLLECTION_ID,
            return_results=True)
        if not coll:
            raise RuntimeError(f"Échec création collection {op.payload['name']!r}")
        desc = op.payload.get("description", "")
        if desc:
            _check(mb.put(f"/api/collection/{coll['id']}",
                          json={"description": desc}), "MAJ description")
        family_ids[op.payload["key"]] = coll["id"]
        print(f"  créée : {op.payload['name']} (id {coll['id']})")
    elif op.kind == "move_collection":
        parent = family_ids[op.payload["new_parent_key"]]
        _check(mb.put(f"/api/collection/{op.payload['collection_id']}",
                      json={"parent_id": parent, "name": op.payload["new_name"]}),
               f"déplacement collection {op.payload['collection_id']}")
        print(f"  déplacée : collection {op.payload['collection_id']} "
              f"-> parent {parent}")
    elif op.kind == "move_card":
        _check(mb.put(f"/api/card/{op.payload['card_id']}",
                      json={"collection_id": op.payload["collection_id"]}),
               f"déplacement carte {op.payload['card_id']}")
        print(f"  carte {op.payload['card_id']} -> "
              f"collection {op.payload['collection_id']}")
    elif op.kind == "delete_collection":
        cid = op.payload["collection_id"]
        resp = mb.get(f"/api/collection/{cid}/items?limit=10")
        if resp is False:
            raise RuntimeError(f"impossible de lister la collection {cid}")
        items = resp.get("data", [])
        if items:
            print(f"  IGNORÉE : collection {cid} non vide "
                  f"({len(items)} éléments) — suppression annulée")
            return
        _check(mb.put(f"/api/collection/{cid}", json={"archived": True}),
               f"archivage collection {cid}")
        print(f"  collection {cid} archivée (vide)")
    else:
        raise ValueError(f"opération inconnue : {op.kind}")


def cmd_apply(args):
    baseline = MetabaseState.from_dict(json.loads(Path(args.snapshot).read_text()))
    plan = load_plan(args.plan)
    lots = compute_lots(baseline, plan)
    ops = lots[args.lot]
    if not ops:
        print(f"{args.lot} : aucune opération.")
        return

    print(f"\n=== {args.lot} : {len(ops)} opérations ===")
    for op in ops:
        print(f"  - {op.summary}")
    if not args.yes:
        if input(f"\nAppliquer {args.lot} ? [tape 'oui'] ").strip() != "oui":
            sys.exit("Annulé.")

    mb = connect()
    family_ids = {}
    if _families_path().exists():
        family_ids = json.loads(_families_path().read_text())

    for op in ops:
        _exec_op(mb, op, family_ids)

    if args.lot == "lot-1":
        _families_path().write_text(json.dumps(family_ids, indent=2))
        print(f"Familles enregistrées : {_families_path()}")

    print("\nVérification d'invariant post-lot...")
    current = capture_state(mb.get, root_id=ROOT_COLLECTION_ID)
    divergences = verify_invariant(baseline, current)
    if divergences:
        print("DIVERGENCES DÉTECTÉES — ARRÊT :")
        for d in divergences:
            print(f"  [{d.kind}] carte {d.card_id} : {d.detail}")
        sys.exit(1)
    print(f"OK — {len(current.cards)} cartes intactes, 0 divergence.")


def cmd_verify(args):
    raise NotImplementedError


def cmd_rollback(args):
    raise NotImplementedError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Migration Phase 1 collection 215")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="Capturer l'état du sous-arbre 215")

    p_plan = sub.add_parser("plan", help="Dry-run : afficher tous les déplacements")
    p_plan.add_argument("--snapshot", required=True)
    p_plan.add_argument("--plan", default=str(MIGRATION_DIR / "phase1-plan.yaml"))

    p_apply = sub.add_parser("apply", help="Exécuter un lot du plan")
    p_apply.add_argument("lot", choices=[f"lot-{i}" for i in range(1, 6)])
    p_apply.add_argument("--snapshot", required=True)
    p_apply.add_argument("--plan", default=str(MIGRATION_DIR / "phase1-plan.yaml"))
    p_apply.add_argument("--yes", action="store_true", help="Sans confirmation")

    p_verify = sub.add_parser("verify", help="Comparer l'état live au snapshot")
    p_verify.add_argument("--snapshot", required=True)

    p_rollback = sub.add_parser("rollback", help="Restaurer les positions du snapshot")
    p_rollback.add_argument("--snapshot", required=True)
    p_rollback.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    {"snapshot": cmd_snapshot, "plan": cmd_plan, "apply": cmd_apply,
     "verify": cmd_verify, "rollback": cmd_rollback}[args.command](args)


if __name__ == "__main__":
    main()
