#!/usr/bin/env python3
"""Garantit que la copie d'un dashboard s'ouvre sur le client canonique.

Le worklist/manifest porte le propriétaire canonique. Beaucoup de dashboards sources
sont des templates historiques dont le paramètre ``Client`` pointe encore vers un autre
compte. Cette étape ne touche que la COPIE, fait un snapshot complet, relit le résultat
et restaure le dashboard au moindre doute.

Usage :
  python3 scripts/ensure_client_default.py --copy 27745 --client "Chilowé"
  python3 scripts/ensure_client_default.py --copy 27745 --client "Chilowé" --yes
  python3 scripts/ensure_client_default.py --copy 27745 --client "Chilowé" \
      --clear-account-default --yes
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from conv_paths import reg_dir
from migrate_dashboard_full import _dcs, connect


def _clone(value):
    return json.loads(json.dumps(value))


def is_client_parameter(parameter: dict) -> bool:
    slug = str(parameter.get("slug") or "").strip().casefold()
    name = str(parameter.get("name") or "").strip().casefold()
    return slug in {"client", "clients"} or name in {"client", "clients"}


def is_account_parameter(parameter: dict) -> bool:
    slug = str(parameter.get("slug") or "").strip().casefold()
    name = str(parameter.get("name") or "").strip().casefold()
    return slug in {"account", "account_name"} or name in {"account", "account name"}


def client_defaults(dashboard: dict) -> list[dict]:
    return [
        {
            "id": parameter.get("id"),
            "name": parameter.get("name"),
            "slug": parameter.get("slug"),
            "default": _clone(parameter.get("default")),
        }
        for parameter in dashboard.get("parameters") or []
        if is_client_parameter(parameter)
    ]


def account_defaults(dashboard: dict) -> list[dict]:
    return [
        {
            "id": parameter.get("id"),
            "name": parameter.get("name"),
            "slug": parameter.get("slug"),
            "default": _clone(parameter.get("default")),
        }
        for parameter in dashboard.get("parameters") or []
        if is_account_parameter(parameter)
    ]


def build_parameters(
    dashboard: dict,
    client: str,
    *,
    clear_account_default: bool = False,
) -> tuple[list[dict], list[dict]]:
    parameters = _clone(dashboard.get("parameters") or [])
    changes = []
    expected = [client]
    for parameter in parameters:
        before = _clone(parameter.get("default"))
        if is_client_parameter(parameter) and before != expected:
            parameter["default"] = expected
            changes.append({
                "id": parameter.get("id"),
                "name": parameter.get("name"),
                "before": before,
                "after": expected,
            })
        elif clear_account_default and is_account_parameter(parameter) and before is not None:
            parameter["default"] = None
            changes.append({
                "id": parameter.get("id"),
                "name": parameter.get("name"),
                "before": before,
                "after": None,
            })
    return parameters, changes


def default_issues(
    dashboard: dict,
    client: str,
    *,
    require_account_default_cleared: bool = False,
) -> list[str]:
    expected = [client]
    issues = [
        f"paramètre {item.get('id') or item.get('name')}: "
        f"défaut attendu {expected!r}, relu {item.get('default')!r}"
        for item in client_defaults(dashboard)
        if item.get("default") != expected
    ]
    if require_account_default_cleared:
        issues.extend(
            f"paramètre {item.get('id') or item.get('name')}: "
            f"défaut Account attendu None, relu {item.get('default')!r}"
            for item in account_defaults(dashboard)
            if item.get("default") is not None
        )
    return issues


def dashboard_payload(dashboard: dict, parameters: list[dict] | None = None) -> dict:
    payload = {
        "parameters": _clone(
            dashboard.get("parameters") or [] if parameters is None else parameters
        ),
        "dashcards": _clone(_dcs(dashboard)),
    }
    if dashboard.get("tabs"):
        payload["tabs"] = _clone(dashboard["tabs"])
    return payload


def write_snapshot(dashboard_id: int, dashboard: dict) -> Path:
    directory = reg_dir() / "client-default-snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"dashboard-{dashboard_id}-{stamp}.json"
    path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n")
    return path


def _http_ok(response) -> bool:
    return getattr(response, "status_code", None) == 200


def rollback(
    mb,
    dashboard_id: int,
    before: dict,
    *,
    verify_account_default: bool = False,
) -> tuple[bool, str]:
    try:
        response = mb.put(
            f"/api/dashboard/{dashboard_id}", "raw", json=dashboard_payload(before)
        )
        if not _http_ok(response):
            return False, f"rollback HTTP {getattr(response, 'status_code', '?')}"
        reread = mb.get(f"/api/dashboard/{dashboard_id}")
        if client_defaults(reread) != client_defaults(before):
            return False, "rollback divergent sur le défaut Client"
        if verify_account_default and account_defaults(reread) != account_defaults(before):
            return False, "rollback divergent sur le défaut Account"
        return True, "rollback vérifié"
    except Exception as exc:
        return False, f"rollback impossible: {exc}"


def put_verified(
    mb,
    dashboard_id: int,
    before: dict,
    parameters: list[dict],
    client: str,
    *,
    require_account_default_cleared: bool = False,
) -> Path:
    snapshot = write_snapshot(dashboard_id, before)
    try:
        response = mb.put(
            f"/api/dashboard/{dashboard_id}",
            "raw",
            json=dashboard_payload(before, parameters),
        )
    except Exception as exc:
        _ok, note = rollback(
            mb,
            dashboard_id,
            before,
            verify_account_default=require_account_default_cleared,
        )
        raise RuntimeError(f"PUT a levé {exc}; {note}; snapshot {snapshot}") from exc
    if not _http_ok(response):
        _ok, note = rollback(
            mb,
            dashboard_id,
            before,
            verify_account_default=require_account_default_cleared,
        )
        body = str(getattr(response, "text", ""))[:300]
        raise RuntimeError(
            f"PUT HTTP {getattr(response, 'status_code', '?')}: {body}; "
            f"{note}; snapshot {snapshot}"
        )
    try:
        reread = mb.get(f"/api/dashboard/{dashboard_id}")
        issues = default_issues(
            reread,
            client,
            require_account_default_cleared=require_account_default_cleared,
        )
    except Exception as exc:
        _ok, note = rollback(
            mb,
            dashboard_id,
            before,
            verify_account_default=require_account_default_cleared,
        )
        raise RuntimeError(
            f"relecture post-PUT impossible: {exc}; {note}; snapshot {snapshot}"
        ) from exc
    if issues:
        _ok, note = rollback(
            mb,
            dashboard_id,
            before,
            verify_account_default=require_account_default_cleared,
        )
        raise RuntimeError("; ".join(issues) + f"; {note}; snapshot {snapshot}")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--copy", type=int, required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument(
        "--clear-account-default",
        action="store_true",
        help="vide explicitement les defaults Account sur la copie",
    )
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    # Le client historique affiche l'identifiant de session lors de l'authentification.
    # Cette étape est souvent exécutée en lot et ses logs sont conservés dans le tracker.
    try:
        with redirect_stdout(io.StringIO()):
            mb = connect()
    except Exception as exc:
        print(
            f"⛔ connexion Metabase impossible ({type(exc).__name__}); aucune mutation",
            file=sys.stderr,
        )
        return 1
    dashboard = mb.get(f"/api/dashboard/{args.copy}")
    if not isinstance(dashboard, dict):
        print("⛔ dashboard copie inaccessible", file=sys.stderr)
        return 1

    current = client_defaults(dashboard)
    if not current:
        print("Aucun paramètre Client sur ce dashboard — rien à corriger.")
        return 0

    parameters, changes = build_parameters(
        dashboard,
        args.client,
        clear_account_default=args.clear_account_default,
    )
    print(f"Dashboard {args.copy} — défaut Client canonique {args.client!r} :")
    if not changes:
        print("  déjà exact — aucun PUT nécessaire.")
        return 0
    for change in changes:
        print(
            f"  paramètre {change.get('id') or change.get('name')}: "
            f"{change['before']!r} -> {change['after']!r}"
        )
    if not args.yes:
        print("(DRY-RUN — rien modifié.)")
        return 0

    try:
        snapshot = put_verified(
            mb,
            args.copy,
            dashboard,
            parameters,
            args.client,
            require_account_default_cleared=args.clear_account_default,
        )
    except RuntimeError as exc:
        print(f"⛔ correction du défaut Client refusée/annulée : {exc}", file=sys.stderr)
        return 1
    print(f"PUT {args.copy}: 200 vérifié | snapshot: {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
