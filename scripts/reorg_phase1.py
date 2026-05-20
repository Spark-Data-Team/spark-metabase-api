#!/usr/bin/env python3
"""CLI de migration Phase 1 de la collection Metabase « 2. Generic Questions ».

Sous-commandes : snapshot | plan | apply | verify | rollback.
Voir docs/superpowers/specs/2026-05-20-generic-questions-reorg-phase1-design.md
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402

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
    raise NotImplementedError


def cmd_plan(args):
    raise NotImplementedError


def cmd_apply(args):
    raise NotImplementedError


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
