#!/usr/bin/env python3
"""Applique les seuls ajouts ``new_type`` auto-sûrs du plan consultants.

La commande est un dry-run Supabase live par défaut. Une mutation production exige
``--yes``. Avant le premier PATCH, le script relit toutes les lignes, exige une
égalité stricte de ``type[]`` et ``new_type[]`` avec le plan, puis écrit un snapshot
local atomique. Chaque PATCH est limité par ``id`` et ``updated_at`` et ne contient
que ``new_type``. Toute erreur déclenche un rollback best-effort, suivi d'une
relecture stricte ; l'exécution reste alors en échec même si le rollback aboutit.

Ce script ne connaît pas Airtable et n'accepte que les credentials Supabase
explicitement suffixés ``_PROD`` via ``export_supabase_conversion_mapping``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import requests


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import export_supabase_conversion_mapping as exporter


SCHEMA_VERSION = 1
EXPECTED_AUTOMATIC_ROWS = 13
DEFAULT_PLAN = REPO / "migration" / "consultant-supabase-patch-plan.json"
DEFAULT_SNAPSHOT_DIR = REPO / "migration" / "snapshots"
POSTGREST_SCHEMA = "pipeline_manager"
POSTGREST_TABLE = "conversions"
SELECT_FIELDS = "id,type,new_type,updated_at"


class ApplyError(RuntimeError):
    """La mutation ne peut pas être poursuivie sans risque."""

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


@dataclass(frozen=True)
class Change:
    client: str
    slot: int
    target: str
    row_id: str
    before_type: tuple[str | None, ...] | None
    before_new_type: tuple[str | None, ...] | None
    after_type: tuple[str | None, ...] | None
    after_new_type: tuple[str | None, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_array(value: Any, *, label: str) -> tuple[str | None, ...]:
    if not isinstance(value, list) or any(
        item is not None and not isinstance(item, str) for item in value
    ):
        raise ApplyError(f"tableau JSON invalide: {label}")
    return tuple(value)


def _nullable_json_array(
    value: Any,
    *,
    label: str,
) -> tuple[str | None, ...] | None:
    if value is None:
        return None
    return _json_array(value, label=label)


def _canonical_uuid(value: Any, *, label: str) -> str:
    row_id = str(value or "").strip()
    try:
        parsed = UUID(row_id)
    except (ValueError, AttributeError) as exc:
        raise ApplyError(f"UUID invalide: {label}") from exc
    if str(parsed) != row_id:
        raise ApplyError(f"UUID non canonique: {label}")
    return row_id


def load_plan(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ApplyError(f"plan consultants introuvable ou illisible: {path}") from exc
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApplyError(f"plan consultants JSON invalide: {path}") from exc
    if not isinstance(document, dict):
        raise ApplyError("plan consultants: objet JSON attendu")
    return document, hashlib.sha256(raw).hexdigest()


def extract_changes(
    plan: dict,
    *,
    expected_count: int = EXPECTED_AUTOMATIC_ROWS,
) -> list[Change]:
    """Valide le plan entier et extrait exclusivement ses ajouts purs auto-sûrs."""
    if plan.get("schema_version") != 1 or plan.get("read_only") is not True:
        raise ApplyError("plan consultants READ-ONLY v1 attendu")
    source = plan.get("source") or {}
    if (
        source.get("system") != "supabase_snapshot"
        or source.get("environment") != "production"
    ):
        raise ApplyError("plan issu d'un snapshot Supabase production attendu")
    groups = plan.get("groups")
    if not isinstance(groups, list):
        raise ApplyError("plan consultants: groups[] manquant")

    changes: list[Change] = []
    seen_ids: set[str] = set()
    automatic_group_count = 0
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ApplyError(f"groupe invalide à la position {group_index}")
        disposition = group.get("disposition")
        operations = group.get("automatic_operations")
        if not isinstance(operations, list):
            raise ApplyError(f"automatic_operations[] invalide au groupe {group_index}")
        if operations and disposition != "automatic_add_new_type":
            raise ApplyError(
                f"opération automatique hors disposition autorisée au groupe {group_index}"
            )
        if disposition != "automatic_add_new_type":
            continue
        if not operations:
            raise ApplyError(f"groupe automatique vide à la position {group_index}")
        automatic_group_count += 1
        client = str(group.get("client") or "").strip()
        try:
            slot = int(group.get("slot"))
        except (TypeError, ValueError) as exc:
            raise ApplyError(f"slot invalide au groupe {group_index}") from exc
        if not client or not 0 <= slot <= 20:
            raise ApplyError(f"client/slot invalide au groupe {group_index}")

        for operation_index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                raise ApplyError(f"opération invalide au groupe {group_index}")
            if (
                operation.get("operation") != "add_new_type"
                or operation.get("automatic_safe") is not True
            ):
                raise ApplyError(
                    f"seuls les add_new_type automatic_safe sont exécutables "
                    f"(groupe {group_index}, opération {operation_index})"
                )
            target = str(operation.get("new_type") or "").strip()
            record_changes = operation.get("record_changes")
            operation_ids = operation.get("conversion_row_ids")
            if not target or not isinstance(record_changes, list) or not isinstance(operation_ids, list):
                raise ApplyError(f"payload automatique incomplet au groupe {group_index}")

            parsed_operation_ids = [
                _canonical_uuid(value, label=f"groupe {group_index} conversion_row_ids")
                for value in operation_ids
            ]
            if len(set(parsed_operation_ids)) != len(parsed_operation_ids):
                raise ApplyError(f"UUID dupliqué dans l'opération du groupe {group_index}")
            parsed_record_ids: list[str] = []
            for record_index, record in enumerate(record_changes):
                if not isinstance(record, dict):
                    raise ApplyError(f"record_change invalide au groupe {group_index}")
                row_id = _canonical_uuid(
                    record.get("conversion_row_id"),
                    label=f"groupe {group_index} record {record_index}",
                )
                if row_id in seen_ids:
                    raise ApplyError(f"conversion_row_id dupliqué dans le plan: {row_id}")
                seen_ids.add(row_id)
                before = record.get("before")
                after = record.get("after")
                if not isinstance(before, dict) or not isinstance(after, dict):
                    raise ApplyError(f"before/after absent pour {row_id}")
                if "type" not in before or "new_type" not in before:
                    raise ApplyError(f"before incomplet pour {row_id}")
                if "type" not in after or "new_type" not in after:
                    raise ApplyError(f"after incomplet pour {row_id}")
                before_type = _nullable_json_array(
                    before["type"], label=f"{row_id}.before.type"
                )
                before_new_type = _nullable_json_array(
                    before.get("new_type"), label=f"{row_id}.before.new_type"
                )
                after_type = _nullable_json_array(
                    after["type"], label=f"{row_id}.after.type"
                )
                after_new_type = _json_array(
                    after["new_type"], label=f"{row_id}.after.new_type"
                )
                if after_type != before_type:
                    raise ApplyError(f"mutation de type[] interdite pour {row_id}")
                if before_new_type is not None and target in before_new_type:
                    raise ApplyError(f"new_type déjà présent avant l'ajout pour {row_id}")
                normalized_before_new_type = before_new_type or ()
                if after_new_type != normalized_before_new_type + (target,):
                    raise ApplyError(f"la mutation n'est pas un append pur pour {row_id}")
                changes.append(
                    Change(
                        client=client,
                        slot=slot,
                        target=target,
                        row_id=row_id,
                        before_type=before_type,
                        before_new_type=before_new_type,
                        after_type=after_type,
                        after_new_type=after_new_type,
                    )
                )
                parsed_record_ids.append(row_id)
            if sorted(parsed_record_ids) != sorted(parsed_operation_ids):
                raise ApplyError(
                    f"conversion_row_ids et record_changes divergent au groupe {group_index}"
                )

    declared_count = (plan.get("stats") or {}).get("automatic_add_new_type_rows")
    if declared_count != len(changes):
        raise ApplyError(
            "le compteur automatic_add_new_type_rows ne correspond pas au payload exécutable"
        )
    if len(changes) != expected_count:
        raise ApplyError(
            f"refus d'exécuter {len(changes)} lignes: le lot attendu en contient {expected_count}"
        )
    if automatic_group_count != len({(change.client, change.slot) for change in changes}):
        raise ApplyError("les groupes automatiques client/slot ne sont pas uniques")
    return sorted(changes, key=lambda change: change.row_id)


class SupabaseConversionsClient:
    """Client PostgREST réduit aux GET et PATCH strictement nécessaires."""

    def __init__(
        self,
        url: str,
        service_key: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 45.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._service_key = service_key
        self._session = session or requests.Session()
        self._timeout = timeout

    def _headers(self, *, write: bool = False) -> dict[str, str]:
        headers = {
            "apikey": self._service_key,
            "Authorization": f"Bearer {self._service_key}",
            "Accept-Profile": POSTGREST_SCHEMA,
        }
        if write:
            headers.update(
                {
                    "Content-Profile": POSTGREST_SCHEMA,
                    "Prefer": "return=representation",
                }
            )
        return headers

    def fetch_rows(self, row_ids: list[str]) -> dict[str, dict]:
        if not row_ids:
            raise ApplyError("lecture Supabase refusée sans conversion_row_id")
        try:
            response = self._session.get(
                f"{self._url}/rest/v1/{POSTGREST_TABLE}",
                headers=self._headers(),
                params={
                    "select": SELECT_FIELDS,
                    "id": f"in.({','.join(row_ids)})",
                    "order": "id.asc",
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise ApplyError("lecture Supabase impossible (erreur réseau)") from exc
        if response.status_code != 200:
            raise ApplyError(
                f"lecture Supabase refusée (HTTP {response.status_code})"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApplyError("lecture Supabase: réponse JSON invalide") from exc
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ApplyError("lecture Supabase: liste JSON attendue")
        by_id: dict[str, dict] = {}
        for row in payload:
            row_id = str(row.get("id") or "")
            if not row_id or row_id in by_id:
                raise ApplyError("lecture Supabase: id absent ou dupliqué")
            by_id[row_id] = row
        if set(by_id) != set(row_ids):
            missing = sorted(set(row_ids) - set(by_id))
            extra = sorted(set(by_id) - set(row_ids))
            raise ApplyError(
                f"lecture Supabase incomplète: missing={len(missing)}, extra={len(extra)}"
            )
        return by_id

    def patch_new_type(
        self,
        row_id: str,
        expected_updated_at: str | None,
        new_type: list[str | None] | None,
    ) -> dict:
        concurrency_filter = (
            "is.null" if expected_updated_at is None else f"eq.{expected_updated_at}"
        )
        try:
            response = self._session.patch(
                f"{self._url}/rest/v1/{POSTGREST_TABLE}",
                headers=self._headers(write=True),
                params={
                    "select": SELECT_FIELDS,
                    "id": f"eq.{row_id}",
                    "updated_at": concurrency_filter,
                },
                json={"new_type": new_type},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise ApplyError(f"PATCH Supabase impossible pour {row_id} (erreur réseau)") from exc
        if not 200 <= response.status_code < 300:
            raise ApplyError(
                f"PATCH Supabase refusé pour {row_id} (HTTP {response.status_code})"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ApplyError(f"PATCH Supabase sans représentation JSON pour {row_id}") from exc
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise ApplyError(
                f"PATCH Supabase sans ligne unique pour {row_id}; concurrence possible"
            )
        if payload[0].get("id") != row_id:
            raise ApplyError(f"PATCH Supabase a retourné un autre id pour {row_id}")
        return payload[0]


def _validated_live_row(row: dict, change: Change, *, after: bool) -> str | None:
    if row.get("id") != change.row_id:
        raise ApplyError(f"relecture: id inattendu pour {change.row_id}")
    expected_type = change.after_type if after else change.before_type
    expected_new_type = change.after_new_type if after else change.before_new_type
    if "type" not in row or "new_type" not in row:
        raise ApplyError(f"relecture: type/new_type absent pour {change.row_id}")
    actual_type = _nullable_json_array(
        row["type"], label=f"live {change.row_id}.type"
    )
    actual_new_type = _nullable_json_array(
        row["new_type"], label=f"live {change.row_id}.new_type"
    )
    if actual_type != expected_type or actual_new_type != expected_new_type:
        state = "after" if after else "before"
        raise ApplyError(f"état live différent de {state} pour {change.row_id}")
    if "updated_at" not in row:
        raise ApplyError(f"updated_at absent pour {change.row_id}")
    updated_at = row.get("updated_at")
    if updated_at is not None and not isinstance(updated_at, str):
        raise ApplyError(f"updated_at invalide pour {change.row_id}")
    return updated_at


def preflight(
    client: SupabaseConversionsClient,
    changes: list[Change],
) -> dict[str, dict]:
    """GET unique de toutes les lignes, puis égalité stricte avec chaque ``before``."""
    row_ids = [change.row_id for change in changes]
    if len(row_ids) != len(set(row_ids)):
        raise ApplyError("conversion_row_id dupliqué avant le préflight")
    live = client.fetch_rows(row_ids)
    for change in changes:
        _validated_live_row(live[change.row_id], change, after=False)
    return live


def _atomic_write_json(document: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ApplyError(f"refus d'écraser le snapshot existant: {output}")
    data = (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor = -1
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".tmp", dir=str(output.parent)
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        temporary = None
    except OSError as exc:
        raise ApplyError(f"écriture atomique du snapshot impossible: {output}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def write_preapply_snapshot(
    output: Path,
    changes: list[Change],
    live: dict[str, dict],
    *,
    plan_path: Path,
    plan_sha256: str,
    captured_at: str,
) -> None:
    rows = []
    for change in changes:
        live_row = live[change.row_id]
        rows.append(
            {
                "client": change.client,
                "slot": change.slot,
                "new_type": change.target,
                "conversion_row_id": change.row_id,
                "before": {
                    "type": None if change.before_type is None else list(change.before_type),
                    "new_type": (
                        None
                        if change.before_new_type is None
                        else list(change.before_new_type)
                    ),
                    "updated_at": live_row.get("updated_at"),
                },
                "after": {
                    "type": None if change.after_type is None else list(change.after_type),
                    "new_type": list(change.after_new_type),
                },
            }
        )
    _atomic_write_json(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "consultant_supabase_preapply_snapshot",
            "source": {
                "system": "supabase",
                "environment": "production",
                "schema": POSTGREST_SCHEMA,
                "table": POSTGREST_TABLE,
            },
            "captured_at": captured_at,
            "plan": {
                "path": str(plan_path),
                "sha256": plan_sha256,
                "automatic_add_new_type_rows": len(changes),
            },
            "rows": rows,
        },
        output,
    )


def _state_matches(row: dict, change: Change, *, after: bool) -> bool:
    try:
        _validated_live_row(row, change, after=after)
        return True
    except ApplyError:
        return False


def _rollback(
    client: SupabaseConversionsClient,
    changes: list[Change],
    confirmed: dict[str, dict],
) -> dict:
    """Restaure uniquement ``new_type`` et vérifie toutes les lignes du lot."""
    row_ids = [change.row_id for change in changes]
    diagnostics: list[dict] = []
    try:
        current = client.fetch_rows(row_ids)
        scan_complete = True
    except ApplyError:
        current = dict(confirmed)
        scan_complete = False
        diagnostics.append({"kind": "rollback_initial_reread_failed"})

    rollback_candidates: dict[str, dict] = {}
    for change in changes:
        row = current.get(change.row_id)
        if row is None:
            diagnostics.append(
                {"kind": "rollback_state_unknown", "conversion_row_id": change.row_id}
            )
        elif _state_matches(row, change, after=False):
            continue
        elif _state_matches(row, change, after=True):
            rollback_candidates[change.row_id] = row
        else:
            diagnostics.append(
                {"kind": "rollback_unexpected_live_state", "conversion_row_id": change.row_id}
            )

    restored = 0
    for change in reversed(changes):
        row = rollback_candidates.get(change.row_id)
        if row is None:
            continue
        try:
            representation = client.patch_new_type(
                change.row_id,
                row.get("updated_at"),
                (
                    None
                    if change.before_new_type is None
                    else list(change.before_new_type)
                ),
            )
            _validated_live_row(representation, change, after=False)
            restored += 1
        except ApplyError:
            diagnostics.append(
                {"kind": "rollback_patch_failed", "conversion_row_id": change.row_id}
            )

    complete = False
    before_count = 0
    try:
        final = client.fetch_rows(row_ids)
        before_count = sum(
            _state_matches(final[change.row_id], change, after=False)
            for change in changes
        )
        complete = before_count == len(changes)
        if not complete:
            diagnostics.append(
                {
                    "kind": "rollback_final_state_mismatch",
                    "before_count": before_count,
                    "expected_count": len(changes),
                }
            )
    except ApplyError:
        diagnostics.append({"kind": "rollback_final_reread_failed"})

    return {
        "complete": complete,
        "scan_complete": scan_complete,
        "restored_rows": restored,
        "before_rows_after_rollback": before_count,
        "expected_rows": len(changes),
        "diagnostics": diagnostics,
    }


def execute(
    client: SupabaseConversionsClient,
    changes: list[Change],
    *,
    apply: bool,
    snapshot_output: Path,
    plan_path: Path,
    plan_sha256: str,
    captured_at: str | None = None,
) -> dict:
    """Préflight le lot puis l'applique transactionnellement au mieux côté client."""
    live = preflight(client, changes)
    clients_slots = sorted({(change.client, change.slot) for change in changes})
    if not apply:
        return {
            "status": "dry_run",
            "rows": len(changes),
            "groups": len(clients_slots),
            "snapshot": None,
        }

    captured_at = captured_at or _utc_now().isoformat()
    write_preapply_snapshot(
        snapshot_output,
        changes,
        live,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        captured_at=captured_at,
    )

    confirmed: dict[str, dict] = {}
    attempted = 0
    try:
        for change in changes:
            attempted += 1
            representation = client.patch_new_type(
                change.row_id,
                live[change.row_id].get("updated_at"),
                list(change.after_new_type),
            )
            _validated_live_row(representation, change, after=True)
            confirmed[change.row_id] = representation

        final = client.fetch_rows([change.row_id for change in changes])
        for change in changes:
            _validated_live_row(final[change.row_id], change, after=True)
    except Exception as exc:
        rollback = _rollback(client, changes, confirmed)
        rollback_label = "complet" if rollback["complete"] else "INCOMPLET"
        failure = str(exc) if isinstance(exc, ApplyError) else "erreur inattendue"
        raise ApplyError(
            f"application interrompue après {attempted}/{len(changes)} tentative(s): "
            f"{failure}; rollback {rollback_label}",
            details={
                "attempted_rows": attempted,
                "confirmed_rows": len(confirmed),
                "rollback": rollback,
                "snapshot": str(snapshot_output),
            },
        ) from exc

    return {
        "status": "applied",
        "rows": len(changes),
        "groups": len(clients_slots),
        "snapshot": str(snapshot_output),
    }


def _default_snapshot_path(now: datetime | None = None) -> Path:
    timestamp = (now or _utc_now()).strftime("%Y%m%dT%H%M%S%fZ")
    return DEFAULT_SNAPSHOT_DIR / f"consultant-supabase-before-{timestamp}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--env-file", type=Path, help="fichier contenant les credentials *_PROD")
    parser.add_argument(
        "--snapshot-output",
        type=Path,
        help="snapshot pré-écriture (par défaut migration/snapshots/<timestamp>.json)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="préflight live sans PATCH (défaut)")
    mode.add_argument("--yes", action="store_true", help="autorise explicitement les PATCH production")
    args = parser.parse_args(argv)

    try:
        plan, plan_sha256 = load_plan(args.plan)
        changes = extract_changes(plan)
        url, service_key = exporter.load_prod_credentials(args.env_file)
        client = SupabaseConversionsClient(url, service_key)
        result = execute(
            client,
            changes,
            apply=args.yes,
            snapshot_output=args.snapshot_output or _default_snapshot_path(),
            plan_path=args.plan,
            plan_sha256=plan_sha256,
        )
        if result["status"] == "dry_run":
            print(
                f"Préflight Supabase production validé: {result['rows']} lignes, "
                f"{result['groups']} groupes client/slot."
            )
            print("DRY-RUN — aucun PATCH Supabase; aucun snapshot local écrit.")
        else:
            print(
                f"Supabase production mis à jour et relu: {result['rows']} ajouts "
                f"new_type, {result['groups']} groupes client/slot."
            )
            print(f"Snapshot pré-écriture: {result['snapshot']}")
        return 0
    except (ApplyError, exporter.SnapshotError) as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        if isinstance(exc, ApplyError) and exc.details.get("rollback"):
            rollback = exc.details["rollback"]
            print(
                "Rollback: "
                f"complete={rollback['complete']}, "
                f"restored_rows={rollback['restored_rows']}, "
                f"before_rows={rollback['before_rows_after_rollback']}/"
                f"{rollback['expected_rows']}, "
                f"diagnostics={len(rollback['diagnostics'])}",
                file=sys.stderr,
            )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
