#!/usr/bin/env python3
"""Export read-only dashboard/client attribution evidence for the migration manifest.

The worklist owns scope and client attribution.  Dashboard ``Client`` defaults are
observations only: they are useful to detect reused templates, but they must never
replace the owner established by the worklist.

Live mode performs exactly one ``GET /api/dashboard/{id}`` per unique source id.
Fixture mode performs no network I/O and is intended for tests and reproducible audits.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable


REPO = Path(__file__).resolve().parent.parent
MIGRATION = REPO / "migration"
DEFAULT_WORKLIST = MIGRATION / "worklist.json"
DEFAULT_OUTPUT = MIGRATION / "dashboard-client-attribution.json"
SCHEMA_VERSION = 1


DashboardFetcher = Callable[[int], Any]


def _positive_id(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} invalide: {value!r}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} invalide: {value!r}") from exc
    if result <= 0:
        raise ValueError(f"{field} doit etre un entier positif: {value!r}")
    return result


def _client_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _sort_strings(values: set[str] | list[str]) -> list[str]:
    return sorted(set(values), key=lambda value: (_client_key(value), value))


def normalise_worklist(payload: Any) -> dict[int, list[str]]:
    """Return one sorted owner-candidate list per unique source dashboard id."""
    if not isinstance(payload, dict):
        raise ValueError("la worklist doit etre un objet {client: [original_id, ...]}")

    by_original: dict[int, set[str]] = defaultdict(set)
    for raw_client, raw_ids in payload.items():
        client = str(raw_client).strip()
        if not client:
            raise ValueError("la worklist contient un nom client vide")
        if not isinstance(raw_ids, list):
            raise ValueError(f"worklist[{raw_client!r}] doit etre une liste")
        for position, raw_id in enumerate(raw_ids):
            original_id = _positive_id(
                raw_id,
                f"worklist[{raw_client!r}][{position}]",
            )
            by_original[original_id].add(client)
    return {
        original_id: _sort_strings(owners)
        for original_id, owners in sorted(by_original.items())
    }


def _is_client_parameter(parameter: Any) -> bool:
    if not isinstance(parameter, dict):
        return False
    slug = str(parameter.get("slug") or "").strip().casefold()
    name = str(parameter.get("name") or "").strip().casefold()
    return slug == "client" or name == "client"


def _default_strings(value: Any) -> tuple[list[str], bool]:
    """Normalise a Metabase parameter default; bool reports malformed values."""
    if value is None:
        return [], False
    values = value if isinstance(value, (list, tuple)) else [value]
    output: set[str] = set()
    malformed = False
    for raw in values:
        if isinstance(raw, str):
            clean = raw.strip()
            if clean:
                output.add(clean)
            continue
        # Some Metabase versions serialise category values as {"value": "..."}.
        if isinstance(raw, dict) and isinstance(raw.get("value"), str):
            clean = raw["value"].strip()
            if clean:
                output.add(clean)
            continue
        malformed = True
    return _sort_strings(output), malformed


def extract_client_defaults(dashboard: dict[str, Any]) -> dict[str, Any]:
    """Extract Client defaults without making any ownership decision."""
    raw_parameters = dashboard.get("parameters")
    parameters = raw_parameters if isinstance(raw_parameters, list) else []
    matches = [parameter for parameter in parameters if _is_client_parameter(parameter)]

    defaults: set[str] = set()
    malformed = False
    evidence = []
    default_present = False
    for parameter in matches:
        has_default = "default" in parameter and parameter.get("default") is not None
        default_present = default_present or has_default
        values, invalid = _default_strings(parameter.get("default"))
        defaults.update(values)
        malformed = malformed or invalid
        evidence.append({
            "id": parameter.get("id"),
            "name": parameter.get("name"),
            "slug": parameter.get("slug"),
            "default_present": has_default,
        })

    return {
        "client_parameter_found": bool(matches),
        "client_default_observed": default_present and bool(defaults),
        "dashboard_default_clients": _sort_strings(defaults),
        "malformed_default": malformed,
        "parameters": evidence,
    }


def _cause(code: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "category": "scope",
        "source": "dashboard-client-attribution",
    }
    if details:
        result["details"] = details
    return result


def inspect_dashboard(
    original_id: int,
    owner_candidates: list[str],
    fetch_dashboard: DashboardFetcher,
) -> dict[str, Any]:
    """Inspect one source dashboard and keep worklist ownership immutable."""
    owner_client = owner_candidates[0] if len(owner_candidates) == 1 else None
    endpoint = f"/api/dashboard/{original_id}"
    flags: list[dict[str, Any]] = []
    unknown_reasons: list[str] = []

    if owner_client is None:
        unknown_reasons.append("worklist_owner_conflict")
        flags.append(_cause(
            "worklist_owner_conflict",
            {"worklist_owner_clients": owner_candidates},
        ))

    fetch_error_type = None
    try:
        dashboard = fetch_dashboard(original_id)
    except Exception as exc:  # the artifact records failure without leaking exception text
        dashboard = None
        fetch_error_type = type(exc).__name__
        unknown_reasons.append("dashboard_fetch_failed")
        flags.append(_cause(
            "dashboard_fetch_failed",
            {"original_id": original_id, "error_type": fetch_error_type},
        ))

    payload_valid = isinstance(dashboard, dict)
    if not payload_valid and fetch_error_type is None:
        unknown_reasons.append("dashboard_payload_invalid")
        flags.append(_cause(
            "dashboard_payload_invalid",
            {"original_id": original_id},
        ))

    extracted = extract_client_defaults(dashboard) if payload_valid else {
        "client_parameter_found": False,
        "client_default_observed": False,
        "dashboard_default_clients": [],
        "malformed_default": False,
        "parameters": [],
    }
    defaults = extracted["dashboard_default_clients"]

    if payload_valid and not extracted["client_parameter_found"]:
        unknown_reasons.append("dashboard_client_parameter_missing")
        flags.append(_cause(
            "dashboard_client_parameter_missing",
            {"original_id": original_id},
        ))
    elif payload_valid and not extracted["client_default_observed"]:
        unknown_reasons.append("dashboard_default_client_missing")
        flags.append(_cause(
            "dashboard_default_client_missing",
            {"original_id": original_id},
        ))

    if extracted["malformed_default"]:
        unknown_reasons.append("dashboard_default_client_invalid")
        flags.append(_cause(
            "dashboard_default_client_invalid",
            {"original_id": original_id},
        ))

    owner_keys = {_client_key(owner_client)} if owner_client else set()
    default_keys = {_client_key(value) for value in defaults}
    mismatch = bool(owner_client and defaults and default_keys != owner_keys)
    if mismatch:
        flags.append(_cause(
            "dashboard_default_client_mismatch",
            {
                "owner_client": owner_client,
                "dashboard_default_clients": defaults,
            },
        ))
    if len(defaults) > 1:
        flags.append(_cause(
            "multiple_dashboard_default_clients",
            {"dashboard_default_clients": defaults},
        ))

    # ``unknown`` is deliberately independent from ``mismatch``: a fetched, explicit
    # but different default is known evidence of a reused template, not missing data.
    unknown = bool(unknown_reasons)
    return {
        "original_id": original_id,
        "owner_client": owner_client,
        "worklist_owner_clients": owner_candidates,
        "dashboard_default_clients": defaults,
        "mismatch": mismatch,
        "unknown": unknown,
        "unknown_reasons": sorted(set(unknown_reasons)),
        "client_parameter_found": extracted["client_parameter_found"],
        "client_default_observed": extracted["client_default_observed"],
        "scope_flags": flags,
        "evidence": {
            "endpoint": endpoint,
            "dashboard_id": dashboard.get("id") if payload_valid else None,
            "dashboard_name": dashboard.get("name") if payload_valid else None,
            "client_parameters": extracted["parameters"],
        },
    }


def build_attribution(
    worklist: Any,
    fetch_dashboard: DashboardFetcher,
    *,
    source: str,
) -> dict[str, Any]:
    owners_by_original = normalise_worklist(worklist)
    dashboards = [
        inspect_dashboard(original_id, owner_candidates, fetch_dashboard)
        for original_id, owner_candidates in owners_by_original.items()
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "read_only": True,
        "summary": {
            "unique_originals": len(dashboards),
            "owner_conflicts": sum(row["owner_client"] is None for row in dashboards),
            "defaults_observed": sum(row["client_default_observed"] for row in dashboards),
            "mismatches": sum(row["mismatch"] for row in dashboards),
            "unknown": sum(row["unknown"] for row in dashboards),
        },
        "dashboards": dashboards,
    }


def _fixture_index(payload: Any) -> dict[int, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("dashboards"), list):
        payload = payload["dashboards"]
    if isinstance(payload, list):
        index = {}
        for position, dashboard in enumerate(payload):
            if not isinstance(dashboard, dict):
                raise ValueError(f"fixture[{position}] doit etre un dashboard")
            dashboard_id = _positive_id(
                dashboard.get("id"),
                f"fixture[{position}].id",
            )
            if dashboard_id in index:
                raise ValueError(f"fixture: dashboard {dashboard_id} duplique")
            index[dashboard_id] = dashboard
        return index
    if isinstance(payload, dict):
        return {
            _positive_id(raw_id, f"fixture[{raw_id!r}]"): dashboard
            for raw_id, dashboard in payload.items()
        }
    raise ValueError("la fixture doit etre une liste de dashboards ou un objet par id")


def fixture_fetcher(payload: Any) -> DashboardFetcher:
    index = _fixture_index(payload)

    def fetch(original_id: int) -> Any:
        return index.get(original_id)

    return fetch


def connect_metabase():
    sys.path.insert(0, str(REPO / "scripts"))
    sys.path.insert(0, str(REPO))
    from reorg_phase1 import _load_env  # noqa: PLC0415
    from spark_metabase_api import Metabase_API  # noqa: PLC0415

    env = _load_env()
    required = ("METABASE_DOMAIN", "METABASE_EMAIL", "METABASE_PASSWORD")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise ValueError(f"variables Metabase manquantes: {', '.join(missing)}")
    # The shared client logs the raw session id on authentication.  Suppress that
    # credential in an export whose stdout may be retained as migration evidence.
    with contextlib.redirect_stdout(io.StringIO()):
        return Metabase_API(
            domain=env["METABASE_DOMAIN"],
            email=env["METABASE_EMAIL"],
            password=env["METABASE_PASSWORD"],
        )


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write deterministic JSON through a same-directory atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Exporte les defaults du filtre Client sans jamais reattribuer le owner de la worklist."
        ),
    )
    parser.add_argument("--worklist", type=Path, default=DEFAULT_WORKLIST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--fixture",
        type=Path,
        help="snapshot dashboard local; interdit toute connexion Metabase",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)

    worklist = _read_json(args.worklist)
    if args.fixture:
        fetch = fixture_fetcher(_read_json(args.fixture))
        source = "metabase-dashboard-fixture"
    else:
        mb = connect_metabase()

        def fetch(original_id: int) -> Any:
            # ``validate_session`` may re-authenticate and log a fresh session id.
            with contextlib.redirect_stdout(io.StringIO()):
                return mb.get(f"/api/dashboard/{original_id}", timeout=args.timeout)

        source = "metabase-dashboard-get"

    result = build_attribution(worklist, fetch, source=source)
    atomic_write_json(args.output, result)
    summary = result["summary"]
    print(
        f"{summary['unique_originals']} sources uniques | "
        f"defaults={summary['defaults_observed']} | "
        f"mismatches={summary['mismatches']} | unknown={summary['unknown']}"
    )
    print(f"Attribution ecrite: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
