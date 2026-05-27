#!/usr/bin/env python3
"""CLI de normalisation des noms de cartes — collection Metabase 215.

Sous-commandes : snapshot | propose | apply | verify | rollback.
Voir docs/superpowers/specs/2026-05-21-card-naming-normalization-phase1.5-design.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from rename_lib import (  # noqa: E402
    capture_snapshot, propose_renames, verify_invariant,
    CardRecord, ROOT_COLLECTION_ID,
)

MIGRATION_DIR = REPO_ROOT / "migration"


def _load_env() -> dict:
    env = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def connect() -> Metabase_API:
    env = _load_env()
    domain = env.get("METABASE_DOMAIN") or os.environ.get("METABASE_DOMAIN")
    session_id = env.get("METABASE_SESSION_ID") or os.environ.get("METABASE_SESSION_ID")
    email = env.get("METABASE_EMAIL") or os.environ.get("METABASE_EMAIL")
    password = env.get("METABASE_PASSWORD") or os.environ.get("METABASE_PASSWORD")
    if not domain:
        sys.exit("METABASE_DOMAIN manquant.")
    if session_id:
        mb = Metabase_API(domain=domain, session_id=session_id)
        if mb.is_session_valid():
            return mb
        print("session_id expiré — bascule sur email/password.")
    if not (email and password):
        sys.exit("Aucune session valide et METABASE_EMAIL/PASSWORD manquants.")
    return Metabase_API(domain=domain, email=email, password=password)


def _snapshot_to_dict(snap: dict[int, CardRecord]) -> dict:
    return {"cards": [asdict(r) for r in snap.values()]}


def _snapshot_from_dict(data: dict) -> dict[int, CardRecord]:
    return {c["id"]: CardRecord(**c) for c in data["cards"]}


def cmd_snapshot(args):
    mb = connect()
    print(f"Capture du sous-arbre de la collection {ROOT_COLLECTION_ID} "
          f"(hors Nouvelles Conversions)...")
    snap = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = MIGRATION_DIR / f"rename-snapshot-{ts}.json"
    out.write_text(json.dumps(_snapshot_to_dict(snap), indent=2, ensure_ascii=False))
    print(f"  {len(snap)} cartes capturées")
    print(f"Snapshot écrit : {out}")


def cmd_propose(args):
    raise NotImplementedError


def cmd_apply(args):
    raise NotImplementedError


def cmd_verify(args):
    raise NotImplementedError


def cmd_rollback(args):
    raise NotImplementedError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Normalisation des noms — Phase 1.5")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="Capturer l'état des cartes du sous-arbre 215")

    p_prop = sub.add_parser("propose", help="Générer rename-proposal.csv")
    p_prop.add_argument("--snapshot", required=True)
    p_prop.add_argument("--out", default=str(MIGRATION_DIR / "rename-proposal.csv"))

    p_apply = sub.add_parser("apply", help="Appliquer le CSV de renommage")
    p_apply.add_argument("--snapshot", required=True)
    p_apply.add_argument("--proposal", default=str(MIGRATION_DIR / "rename-proposal.csv"))
    p_apply.add_argument("--yes", action="store_true")

    p_verify = sub.add_parser("verify", help="Comparer l'état live au snapshot")
    p_verify.add_argument("--snapshot", required=True)

    p_rb = sub.add_parser("rollback", help="Restaurer les noms d'origine")
    p_rb.add_argument("--snapshot", required=True)
    p_rb.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    {"snapshot": cmd_snapshot, "propose": cmd_propose, "apply": cmd_apply,
     "verify": cmd_verify, "rollback": cmd_rollback}[args.command](args)


if __name__ == "__main__":
    main()
