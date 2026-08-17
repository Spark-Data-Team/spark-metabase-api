#!/usr/bin/env python3
"""Exécute séquentiellement un plan explicite de bascule temps avec une seule session.

Chaque ligne utilise les garde-fous de ``bascule_time_filter``. Les échecs restent
fail-closed et n'empêchent pas l'audit des lignes suivantes. Dry-run par défaut.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import bascule_time_filter  # noqa: E402
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
        if copy_id <= 0 or not client or copy_id in seen:
            raise ValueError(f"plan[{index}] copy_id/client invalide ou dupliqué")
        seen.add(copy_id)
        output.append({"copy_id": copy_id, "client": client})
    return output


def execute_plan(mb, rows: list[dict], *, yes: bool) -> list[dict]:
    report = []
    for row in rows:
        argv = [
            "--copy", str(row["copy_id"]),
            "--client", row["client"],
            "--auto-prepare",
        ]
        if not yes:
            argv.append("--dry-prepare")
        else:
            argv.append("--yes")
        try:
            result = bascule_time_filter.main(argv, mb=mb)
            code = int(result or 0)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
        report.append({**row, "status": "APPLIED" if yes and code == 0 else "READY" if code == 0 else "BLOCKED"})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--report", type=Path)
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
    report = execute_plan(mb, rows, yes=args.yes)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"applied": args.yes, "results": report}, ensure_ascii=False, indent=2) + "\n")
    for item in report:
        print(f"{item['copy_id']} {item['client']}: {item['status']}")
    blocked = sum(item["status"] == "BLOCKED" for item in report)
    print(f"Résumé: {len(report) - blocked} réussi(s), {blocked} bloqué(s)")
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
