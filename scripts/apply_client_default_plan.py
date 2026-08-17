#!/usr/bin/env python3
"""Applique séquentiellement un plan explicite de defaults Client/Account sur des copies.

Le plan est idempotent, utilise une seule session Metabase et délègue chaque écriture à
``ensure_client_default.put_verified`` (snapshot, relecture stricte, rollback local).
Dry-run par défaut.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from ensure_client_default import (  # noqa: E402
    build_parameters,
    client_defaults,
    default_issues,
    put_verified,
)
from migrate_dashboard_full import connect  # noqa: E402


def normalise_plan(payload) -> list[dict]:
    rows = payload.get("changes") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("le plan doit être une liste ou un objet avec 'changes'")
    output, seen = [], set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"plan[{index}] doit être un objet")
        try:
            copy_id = int(raw.get("copy_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"plan[{index}].copy_id invalide") from exc
        client = str(raw.get("client") or "").strip()
        if copy_id <= 0 or not client:
            raise ValueError(f"plan[{index}] copy_id/client invalide")
        if copy_id in seen:
            raise ValueError(f"copy_id {copy_id} dupliqué dans le plan")
        seen.add(copy_id)
        output.append({
            "copy_id": copy_id,
            "client": client,
            "clear_account_default": raw.get("clear_account_default") is True,
        })
    return output


def execute_plan(mb, rows: list[dict], *, yes: bool) -> tuple[int, list[dict]]:
    report = []
    for row in rows:
        copy_id = row["copy_id"]
        client = row["client"]
        clear_account = row["clear_account_default"]
        dashboard = mb.get(f"/api/dashboard/{copy_id}")
        if not isinstance(dashboard, dict):
            report.append({**row, "status": "FAILED", "reason": "dashboard inaccessible"})
            return 1, report
        if not client_defaults(dashboard):
            report.append({**row, "status": "FAILED", "reason": "paramètre Client absent"})
            return 1, report
        parameters, changes = build_parameters(
            dashboard,
            client,
            clear_account_default=clear_account,
        )
        if not changes:
            issues = default_issues(
                dashboard,
                client,
                require_account_default_cleared=clear_account,
            )
            if issues:
                report.append({**row, "status": "FAILED", "reason": "; ".join(issues)})
                return 1, report
            report.append({**row, "status": "ALREADY_EXACT", "changes": []})
            continue
        if not yes:
            report.append({**row, "status": "PLANNED", "changes": changes})
            continue
        try:
            snapshot = put_verified(
                mb,
                copy_id,
                dashboard,
                parameters,
                client,
                require_account_default_cleared=clear_account,
            )
        except RuntimeError as exc:
            report.append({**row, "status": "FAILED", "reason": str(exc)})
            return 1, report
        report.append({
            **row,
            "status": "APPLIED",
            "changes": changes,
            "snapshot": str(snapshot),
        })
    return 0, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    try:
        rows = normalise_plan(json.loads(args.plan.read_text()))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"⛔ plan invalide: {exc}", file=sys.stderr)
        return 1
    try:
        with redirect_stdout(io.StringIO()):
            mb = connect()
    except Exception as exc:
        print(
            f"⛔ connexion Metabase impossible ({type(exc).__name__}); aucune mutation",
            file=sys.stderr,
        )
        return 1
    code, report = execute_plan(mb, rows, yes=args.yes)
    for item in report:
        print(
            f"{item['copy_id']} {item['client']}: {item['status']}"
            + (f" — {item['reason']}" if item.get("reason") else "")
        )
    applied = sum(item["status"] == "APPLIED" for item in report)
    exact = sum(item["status"] == "ALREADY_EXACT" for item in report)
    planned = sum(item["status"] == "PLANNED" for item in report)
    print(f"Résumé: {applied} appliqué(s), {exact} déjà exact(s), {planned} planifié(s)")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
