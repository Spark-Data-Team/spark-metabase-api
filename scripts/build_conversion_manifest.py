#!/usr/bin/env python3
"""Construit le manifeste canonique de la migration des dashboards conversions.

Le script ne contacte aucun service : il reconcilie exclusivement trois snapshots JSON locaux :

* la worklist (perimetre attendu, par client) ;
* le tracker (relations original -> copie) ;
* un etat Iron-Law optionnel, obligatoirement au grain ``copy_id`` ;
* des decisions optionnelles de copie canonique pour reconcilier les topologies multiples.

Une absence d'etat Iron-Law reste ``unknown``. En particulier, l'accounting agrege ne permet pas
d'inferer l'etat d'une copie et n'est volontairement pas accepte comme substitut.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent
MIGRATION = REPO / "migration"
DEFAULT_WORKLIST = MIGRATION / "worklist.json"
DEFAULT_TRACKER = MIGRATION / "conv-migration-tracker.json"
DEFAULT_OUTPUT = MIGRATION / "conversion-manifest.json"
IRON_CACHE_CANDIDATES = (
    MIGRATION / "iron-law-state.json",
    MIGRATION / "iron-law-cache.json",
)

SCHEMA_VERSION = 1
IRON_STATUSES = ("complete", "residual", "unknown")


def _positive_id(value: Any, field: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} invalide: {value!r}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} invalide: {value!r}") from exc
    if result <= 0:
        raise ValueError(f"{field} doit etre un entier positif: {value!r}")
    return result


def _token(value: Any, fallback: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or fallback


def structured_cause(
    code: str,
    category: str,
    source: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cause = {
        "code": _token(code, "unspecified"),
        "category": _token(category, "unknown"),
        "source": str(source),
    }
    if details:
        cause["details"] = details
    return cause


def _normalise_cause(raw: Any, source: str) -> dict[str, Any]:
    if isinstance(raw, str):
        return structured_cause(raw, "unknown", source, {"message": raw})
    if not isinstance(raw, dict):
        return structured_cause(
            "unspecified",
            "unknown",
            source,
            {"value": raw},
        )

    raw = dict(raw)
    explicit_details = raw.pop("details", None)
    details = dict(explicit_details) if isinstance(explicit_details, dict) else {}
    code_value = raw.pop("code", None)
    reason = raw.pop("reason", None)
    category = raw.pop("category", raw.pop("kind", "unknown"))
    cause_source = raw.pop("source", source)
    if code_value is None:
        code_value = reason if isinstance(reason, str) else "unspecified"
    if reason is not None and reason != code_value:
        details.setdefault("reason", reason)
    details.update(raw)
    return structured_cause(code_value, category, cause_source, details)


def _dedupe_causes(causes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output = []
    for cause in causes:
        key = json.dumps(cause, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            output.append(cause)
    return output


def _status_token(value: Any) -> str:
    token = _token(value, "unknown")
    aliases = {
        "complete": "complete",
        "completed": "complete",
        "clean": "complete",
        "finished": "complete",
        "fini": "complete",
        "true_100": "complete",
        "visible_100": "complete",
        "residual": "residual",
        "residu": "residual",
        "incomplete": "residual",
        "blocked": "residual",
        "bloque": "residual",
        "unknown": "unknown",
        "inconnu": "unknown",
        "unchecked": "unknown",
        "not_checked": "unknown",
    }
    return aliases.get(token, "unknown")


def _iron_rows(payload: Any) -> tuple[list[dict[str, Any]], str]:
    """Accepte les formes liste, {copies/items: liste} ou {by_copy: mapping}."""
    if payload is None:
        return [], "absent"
    if isinstance(payload, list):
        return payload, "provided"
    if not isinstance(payload, dict):
        raise ValueError("l'etat Iron-Law doit etre une liste ou un objet JSON")

    source = str(payload.get("source") or "provided")
    for key in ("copies", "items", "entries"):
        if key in payload:
            rows = payload[key]
            if not isinstance(rows, list):
                raise ValueError(f"iron_state.{key} doit etre une liste")
            return rows, source

    if "by_copy" in payload:
        mapping = payload["by_copy"]
        if not isinstance(mapping, dict):
            raise ValueError("iron_state.by_copy doit etre un objet")
        rows = []
        for copy_id, value in mapping.items():
            if isinstance(value, dict):
                rows.append({"copy_id": copy_id, **value})
            elif isinstance(value, bool):
                rows.append({"copy_id": copy_id, "complete": value})
            else:
                rows.append({"copy_id": copy_id, "status": value})
        return rows, source

    raise ValueError(
        "etat Iron-Law sans donnees par copie: fournir une liste, 'copies', 'items' "
        "ou 'by_copy' (accounting-final.json est trop agrege)"
    )


def _row_status(row: dict[str, Any]) -> str:
    nested = row.get("iron_law")
    nested = nested if isinstance(nested, dict) else {}
    for key in ("iron_law_status", "status"):
        if key in row:
            return _status_token(row[key])
        if key in nested:
            return _status_token(nested[key])

    for key in ("complete", "clean", "visible_100", "true_100", "finished"):
        value = row.get(key, nested.get(key))
        if isinstance(value, bool):
            return "complete" if value else "residual"

    on_old = row.get("on_old", nested.get("on_old"))
    if isinstance(on_old, bool):
        return "residual" if on_old else "complete"

    residual_flag = row.get("residual", nested.get("residual"))
    if isinstance(residual_flag, bool):
        return "residual" if residual_flag else "complete"

    for key in ("residual_count", "old_card_count", "residu", "residue"):
        value = row.get(key, nested.get(key))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return "complete" if value == 0 else "residual"
    return "unknown"


def _row_causes(row: dict[str, Any], source: str) -> list[dict[str, Any]]:
    nested = row.get("iron_law")
    nested = nested if isinstance(nested, dict) else {}
    raw: Any = None
    for key in ("causes", "blockers", "residuals"):
        if key in row:
            raw = row[key]
            break
        if key in nested:
            raw = nested[key]
            break
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [_normalise_cause(value, source) for value in values]


def normalise_iron_state(payload: Any) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    rows, source = _iron_rows(payload)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for position, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"etat Iron-Law ligne {position}: objet attendu")
        copy_id = _positive_id(
            raw.get("copy_id", raw.get("copy")),
            f"iron_state[{position}].copy_id",
        )
        grouped[copy_id].append(raw)

    states: dict[int, dict[str, Any]] = {}
    conflicting_copy_ids = []
    for copy_id, copy_rows in grouped.items():
        statuses = {_row_status(row) for row in copy_rows}
        causes = [
            cause
            for row in copy_rows
            for cause in _row_causes(row, source)
        ]
        if len(statuses) > 1:
            status = "unknown"
            conflicting_copy_ids.append(copy_id)
            causes.append(structured_cause(
                "iron_state_conflict",
                "validation",
                source,
                {"copy_id": copy_id, "statuses": sorted(statuses), "row_count": len(copy_rows)},
            ))
        else:
            status = next(iter(statuses))
        if status == "residual" and not causes:
            causes.append(structured_cause(
                "iron_law_residual_unspecified",
                "unknown",
                source,
                {"copy_id": copy_id},
            ))
        if status == "unknown" and not causes:
            causes.append(structured_cause(
                "iron_law_status_unknown",
                "validation",
                source,
                {"copy_id": copy_id},
            ))
        states[copy_id] = {
            "status": status,
            "source": source,
            "causes": _dedupe_causes(causes),
        }
        if len(copy_rows) > 1:
            states[copy_id]["source_rows"] = len(copy_rows)

    diagnostics = {
        "source": source,
        "rows": len(rows),
        "copies": len(states),
        "conflicting_copy_ids": sorted(conflicting_copy_ids),
    }
    return states, diagnostics


def _tracker_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("entries"), list):
        rows = payload["entries"]
    else:
        raise ValueError("le tracker doit etre une liste ou un objet avec 'entries'")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("chaque ligne du tracker doit etre un objet")
    return rows


def _worklist_index(payload: Any) -> dict[int, set[str]]:
    if not isinstance(payload, dict):
        raise ValueError("la worklist doit etre un objet {client: [original_id, ...]}")
    index: dict[int, set[str]] = defaultdict(set)
    for client, raw_ids in payload.items():
        if not isinstance(raw_ids, list):
            raise ValueError(f"worklist[{client!r}] doit etre une liste")
        clean_client = str(client).strip()
        if not clean_client:
            raise ValueError("un client de la worklist est vide")
        for position, raw_id in enumerate(raw_ids):
            original_id = _positive_id(raw_id, f"worklist[{client!r}][{position}]")
            index[original_id].add(clean_client)
    return dict(index)


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        raise ValueError(f"{field} doit etre une chaine ou une liste")
    result = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} contient une valeur client invalide: {item!r}")
        result.append(item.strip())
    return result


def _attribution_rows(payload: Any) -> tuple[list[dict[str, Any]], str]:
    if payload is None:
        return [], "absent"
    if isinstance(payload, list):
        return payload, "provided"
    if not isinstance(payload, dict):
        raise ValueError("client_attribution doit etre une liste ou un objet JSON")
    source = str(payload.get("source") or "provided")
    for key in ("items", "dashboards", "entries"):
        if key in payload:
            rows = payload[key]
            if not isinstance(rows, list):
                raise ValueError(f"client_attribution.{key} doit etre une liste")
            return rows, source
    if "by_original" in payload:
        mapping = payload["by_original"]
        if not isinstance(mapping, dict):
            raise ValueError("client_attribution.by_original doit etre un objet")
        rows = []
        for original_id, value in mapping.items():
            if not isinstance(value, dict):
                value = {"dashboard_default_clients": value}
            rows.append({"original_id": original_id, **value})
        return rows, source
    raise ValueError(
        "client_attribution doit fournir une liste, 'items', 'dashboards' ou 'by_original'"
    )


def normalise_client_attribution(
    payload: Any,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Normalise les observations sans jamais en deduire un nouveau proprietaire."""
    rows, source = _attribution_rows(payload)
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for position, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"client_attribution ligne {position}: objet attendu")
        original_id = _positive_id(
            raw.get("original_id", raw.get("dashboard_id", raw.get("dashboard"))),
            f"client_attribution[{position}].original_id",
        )
        grouped[original_id].append(raw)

    output = {}
    for original_id, original_rows in grouped.items():
        defaults, aliases, observed_owners, dashboard_names, flags = set(), set(), set(), set(), []
        defaults_observed = False
        evidence = []
        for row in original_rows:
            for key in ("dashboard_default_clients", "default_clients", "client_defaults"):
                if key in row:
                    defaults_observed = True
                    defaults.update(_string_list(
                        row[key],
                        f"client_attribution[{original_id}].{key}",
                    ))
                    break
            aliases.update(_string_list(
                row.get("accepted_owner_aliases", row.get("owner_aliases")),
                f"client_attribution[{original_id}].accepted_owner_aliases",
            ))
            if row.get("owner_client"):
                observed_owners.update(_string_list(
                    row["owner_client"],
                    f"client_attribution[{original_id}].owner_client",
                ))
            raw_flags = row.get("scope_flags") or []
            raw_flags = raw_flags if isinstance(raw_flags, list) else [raw_flags]
            flags.extend(_normalise_cause(flag, source) for flag in raw_flags)
            if row.get("evidence") is not None:
                item = row["evidence"]
                evidence.append(item)
                if isinstance(item, dict) and item.get("dashboard_name"):
                    dashboard_names.add(str(item["dashboard_name"]).strip())
            if row.get("dashboard_name"):
                dashboard_names.add(str(row["dashboard_name"]).strip())
        output[original_id] = {
            "source": source,
            "source_rows": len(original_rows),
            "defaults_observed": defaults_observed,
            "dashboard_default_clients": sorted(defaults),
            "accepted_owner_aliases": sorted(aliases),
            "observed_owner_clients": sorted(observed_owners),
            "dashboard_names": sorted(name for name in dashboard_names if name),
            "scope_flags": _dedupe_causes(flags),
            "evidence": evidence,
        }
    return output, {"source": source, "rows": len(rows), "originals": len(output)}


def _copy_decision_rows(payload: Any) -> tuple[list[dict[str, Any]], str]:
    if payload is None:
        return [], "absent"
    if isinstance(payload, list):
        return payload, "provided"
    if not isinstance(payload, dict):
        raise ValueError("copy_decisions doit etre une liste ou un objet JSON")
    source = str(payload.get("source") or "provided")
    for key in ("decisions", "items", "entries"):
        if key in payload:
            rows = payload[key]
            if not isinstance(rows, list):
                raise ValueError(f"copy_decisions.{key} doit etre une liste")
            return rows, source
    if "by_original" in payload:
        mapping = payload["by_original"]
        if not isinstance(mapping, dict):
            raise ValueError("copy_decisions.by_original doit etre un objet")
        rows = []
        for original_id, value in mapping.items():
            if not isinstance(value, dict):
                value = {"canonical_copy_id": value}
            rows.append({"original_id": original_id, **value})
        return rows, source
    raise ValueError(
        "copy_decisions doit fournir 'decisions', 'items', 'entries' ou 'by_original'"
    )


def normalise_copy_decisions(
    payload: Any,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Valide des choix exhaustifs canonical/superseded au grain original."""
    rows, source = _copy_decision_rows(payload)
    output: dict[int, dict[str, Any]] = {}
    for position, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ValueError(f"copy_decisions ligne {position}: objet attendu")
        original_id = _positive_id(
            raw.get("original_id", raw.get("dashboard_id")),
            f"copy_decisions[{position}].original_id",
        )
        if original_id in output:
            raise ValueError(f"copy_decisions: original {original_id} duplique")
        canonical_copy_id = _positive_id(
            raw.get("canonical_copy_id"),
            f"copy_decisions[{position}].canonical_copy_id",
        )
        raw_superseded = raw.get("superseded_copy_ids")
        if not isinstance(raw_superseded, list):
            raise ValueError(
                f"copy_decisions[{position}].superseded_copy_ids doit etre une liste exhaustive"
            )
        superseded = [
            _positive_id(value, f"copy_decisions[{position}].superseded_copy_ids[{index}]")
            for index, value in enumerate(raw_superseded)
        ]
        if len(superseded) != len(set(superseded)):
            raise ValueError(f"copy_decisions: copies superseded dupliquees pour {original_id}")
        if canonical_copy_id in superseded:
            raise ValueError(
                f"copy_decisions: la copie canonique {canonical_copy_id} est aussi superseded"
            )
        decision = {
            "source": source,
            "canonical_copy_id": canonical_copy_id,
            "superseded_copy_ids": sorted(superseded),
        }
        if raw.get("reason"):
            decision["reason"] = str(raw["reason"])
        if raw.get("evidence") is not None:
            decision["evidence"] = raw["evidence"]
        output[original_id] = decision
    return output, {"source": source, "rows": len(rows), "originals": len(output)}


def _client_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _client_attribution_for(
    original_id: int,
    owner_client: str | None,
    state_by_original: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    state = state_by_original.get(original_id)
    if state is None:
        return {
            "owner_client": owner_client,
            "dashboard_default_clients": [],
            "accepted_owner_aliases": [],
            "status": "not_provided",
            "scope_flags": [],
            "dashboard_names": [],
        }

    defaults = state["dashboard_default_clients"]
    aliases = state["accepted_owner_aliases"]
    flags = list(state["scope_flags"])
    observed_owners = state["observed_owner_clients"]
    accepted = {_client_key(value) for value in [owner_client, *aliases] if value}
    default_keys = {_client_key(value) for value in defaults}
    if observed_owners and (
        owner_client is None or {_client_key(value) for value in observed_owners} != {_client_key(owner_client)}
    ):
        flags.append(structured_cause(
            "attribution_owner_conflict",
            "scope",
            state["source"],
            {"worklist_owner": owner_client, "observed_owners": observed_owners},
        ))

    if not state["defaults_observed"]:
        status = "unknown"
    elif not defaults:
        status = "no_default"
        flags.append(structured_cause(
            "dashboard_default_client_missing",
            "scope",
            state["source"],
            {"original_id": original_id},
        ))
    elif owner_client is None:
        status = "owner_conflict"
    elif default_keys <= accepted:
        status = "match"
    else:
        status = "mismatch"
        flags.append(structured_cause(
            "dashboard_default_client_mismatch",
            "scope",
            state["source"],
            {
                "owner_client": owner_client,
                "dashboard_default_clients": defaults,
                "accepted_owner_aliases": aliases,
            },
        ))
    if len(defaults) > 1:
        flags.append(structured_cause(
            "multiple_dashboard_default_clients",
            "scope",
            state["source"],
            {"dashboard_default_clients": defaults},
        ))

    result = {
        "owner_client": owner_client,
        "dashboard_default_clients": defaults,
        "accepted_owner_aliases": aliases,
        "status": status,
        "scope_flags": _dedupe_causes(flags),
        "dashboard_names": state.get("dashboard_names", []),
    }
    if state["source_rows"] > 1:
        result["source_rows"] = state["source_rows"]
    if state["evidence"]:
        result["evidence"] = state["evidence"]
    return result


def _tracker_index(
    payload: Any,
) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    orphan_rows = []
    for position, raw in enumerate(_tracker_rows(payload)):
        row = dict(raw)
        if row.get("original_id") is None:
            orphan_rows.append({"position": position, "entry": row})
            continue
        original_id = _positive_id(row["original_id"], f"tracker[{position}].original_id")
        if row.get("copy_id") is not None:
            row["copy_id"] = _positive_id(row["copy_id"], f"tracker[{position}].copy_id")
        row["original_id"] = original_id
        index[original_id].append(row)
    return dict(index), orphan_rows


def _copy_summary(
    copy_id: int,
    rows: list[dict[str, Any]],
    iron_state: dict[int, dict[str, Any]],
    reused_by: list[int],
) -> dict[str, Any]:
    clients = sorted({str(row.get("client")) for row in rows if row.get("client")})
    names = sorted({str(row.get("dashboard")) for row in rows if row.get("dashboard")})
    statuses = sorted({str(row.get("status")) for row in rows if row.get("status")})
    state = iron_state.get(copy_id)
    if state is None:
        state = {
            "status": "unknown",
            "source": "absent",
            "causes": [structured_cause(
                "iron_law_state_missing",
                "validation",
                "manifest",
                {"copy_id": copy_id},
            )],
        }
    result = {
        "copy_id": copy_id,
        "tracker_entry_count": len(rows),
        "clients": clients,
        "dashboard_names": names,
        "tracker_statuses": statuses,
        "tagged": all(row.get("tagged") is True for row in rows),
        "iron_law": state,
    }
    if len(rows) > 1:
        result["tracker_duplicate_rows"] = True
    if len(reused_by) > 1:
        result["reused_by_original_ids"] = reused_by
    return result


def _aggregate_iron_status(copies: list[dict[str, Any]]) -> str:
    if not copies:
        return "not_applicable"
    statuses = {copy["iron_law"]["status"] for copy in copies}
    if "residual" in statuses:
        return "residual"
    if "unknown" in statuses:
        return "unknown"
    return "complete"


def build_manifest(
    worklist: Any,
    tracker: Any,
    iron_state: Any = None,
    *,
    client_attribution: Any = None,
    copy_decisions: Any = None,
    sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Reconcilie les trois sources sans I/O et renvoie un original unique par ``original_id``."""
    worklist_by_original = _worklist_index(worklist)
    tracker_by_original, orphan_tracker_rows = _tracker_index(tracker)
    iron_by_copy, iron_diagnostics = normalise_iron_state(iron_state)
    attribution_by_original, attribution_diagnostics = normalise_client_attribution(client_attribution)
    decisions_by_original, decision_diagnostics = normalise_copy_decisions(copy_decisions)

    copy_to_originals: dict[int, set[int]] = defaultdict(set)
    for original_id, rows in tracker_by_original.items():
        for row in rows:
            if row.get("copy_id") is not None:
                copy_to_originals[row["copy_id"]].add(original_id)

    all_original_ids = set(worklist_by_original) | set(tracker_by_original)
    dashboards = []
    tracker_copy_ids = set(copy_to_originals)
    for original_id in all_original_ids:
        tracker_rows = tracker_by_original.get(original_id, [])
        worklist_clients = sorted(worklist_by_original.get(original_id, set()))
        tracker_clients = sorted({
            str(row.get("client")) for row in tracker_rows if row.get("client")
        })
        tracker_names = sorted({
            str(row.get("dashboard")) for row in tracker_rows if row.get("dashboard")
        })
        in_scope = bool(worklist_clients)
        owner_client = worklist_clients[0] if len(worklist_clients) == 1 else None
        client_attribution_state = _client_attribution_for(
            original_id,
            owner_client,
            attribution_by_original,
        )
        observed_dashboard_names = client_attribution_state.get("dashboard_names", [])
        canonical_dashboard_name = (
            tracker_names[0] if len(tracker_names) == 1
            else observed_dashboard_names[0] if not tracker_names and len(observed_dashboard_names) == 1
            else None
        )

        rows_by_copy: dict[int, list[dict[str, Any]]] = defaultdict(list)
        without_copy = []
        for row in tracker_rows:
            if row.get("copy_id") is None:
                without_copy.append(row)
            else:
                rows_by_copy[row["copy_id"]].append(row)
        copies = [
            _copy_summary(
                copy_id,
                rows_by_copy[copy_id],
                iron_by_copy,
                sorted(copy_to_originals[copy_id]),
            )
            for copy_id in sorted(rows_by_copy)
        ]
        decision = decisions_by_original.get(original_id)
        if decision is not None:
            actual_copy_ids = {copy["copy_id"] for copy in copies}
            declared_copy_ids = {
                decision["canonical_copy_id"],
                *decision["superseded_copy_ids"],
            }
            if len(actual_copy_ids) < 2:
                raise ValueError(
                    f"copy_decisions: original {original_id} n'a pas de topologie multiple"
                )
            if actual_copy_ids != declared_copy_ids:
                raise ValueError(
                    f"copy_decisions: original {original_id}, copies declarees "
                    f"{sorted(declared_copy_ids)} != tracker {sorted(actual_copy_ids)}"
                )
        for copy in copies:
            if decision is None:
                copy["selection"] = "unresolved" if len(copies) > 1 else "canonical"
            elif copy["copy_id"] == decision["canonical_copy_id"]:
                copy["selection"] = "canonical"
            else:
                copy["selection"] = "superseded"
        selected_copies = (
            [copy for copy in copies if copy["selection"] == "canonical"]
            if decision is not None
            else copies
        )

        causes = []
        if not in_scope:
            causes.append(structured_cause(
                "out_of_scope",
                "scope",
                "worklist",
                {"tracker_clients": tracker_clients},
            ))
        if len(worklist_clients) > 1:
            causes.append(structured_cause(
                "worklist_owner_conflict",
                "scope",
                "worklist",
                {"clients": worklist_clients},
            ))
        if in_scope and tracker_clients and set(tracker_clients) != set(worklist_clients):
            causes.append(structured_cause(
                "tracker_client_mismatch",
                "reconciliation",
                "manifest",
                {"worklist_clients": worklist_clients, "tracker_clients": tracker_clients},
            ))
        if not copies:
            details: dict[str, Any] = {}
            pending_statuses = sorted({
                str(row.get("status")) for row in without_copy if row.get("status")
            })
            if pending_statuses:
                details["tracker_statuses"] = pending_statuses
            causes.append(structured_cause("never_copied", "migration", "tracker", details))
        elif len(copies) > 1:
            if decision is None:
                causes.append(structured_cause(
                    "multiple_copies",
                    "reconciliation",
                    "tracker",
                    {"copy_ids": [copy["copy_id"] for copy in copies]},
                ))
            else:
                details = {
                    "canonical_copy_id": decision["canonical_copy_id"],
                    "superseded_copy_ids": decision["superseded_copy_ids"],
                }
                if decision.get("reason"):
                    details["reason"] = decision["reason"]
                causes.append(structured_cause(
                    "multiple_copies_reconciled",
                    "reconciliation",
                    decision["source"],
                    details,
                ))
        if without_copy and copies:
            causes.append(structured_cause(
                "stale_uncopied_tracker_entry",
                "reconciliation",
                "tracker",
                {"entry_count": len(without_copy)},
            ))
        if len(tracker_names) > 1:
            causes.append(structured_cause(
                "tracker_dashboard_name_conflict",
                "reconciliation",
                "tracker",
                {"dashboard_names": tracker_names},
            ))
        causes.extend(client_attribution_state["scope_flags"])
        for copy in selected_copies:
            copy_id = copy["copy_id"]
            if len(copy_to_originals[copy_id]) > 1:
                causes.append(structured_cause(
                    "copy_reused_across_originals",
                    "reconciliation",
                    "tracker",
                    {"copy_id": copy_id, "original_ids": sorted(copy_to_originals[copy_id])},
                ))
            status = copy["iron_law"]["status"]
            if status in ("residual", "unknown"):
                causes.append(structured_cause(
                    f"iron_law_{status}",
                    "validation",
                    copy["iron_law"]["source"],
                    {
                        "copy_id": copy_id,
                        "cause_codes": [cause["code"] for cause in copy["iron_law"]["causes"]],
                    },
                ))

        iron_status = _aggregate_iron_status(selected_copies)
        if not in_scope:
            roadmap_status = "out_of_scope"
        elif not copies:
            roadmap_status = "never_copied"
        elif len(copies) > 1 and decision is None:
            roadmap_status = "multiple_copies"
        else:
            roadmap_status = iron_status

        dashboard = {
            "original_id": original_id,
            "client": owner_client,
            "owner_client": owner_client,
            "dashboard": canonical_dashboard_name,
            "scope": {
                "in_worklist": in_scope,
                "worklist_clients": worklist_clients,
            },
            "tracker_clients": tracker_clients,
            "client_attribution": client_attribution_state,
            "scope_flags": client_attribution_state["scope_flags"],
            "copy_status": (
                "never_copied" if not copies
                else "single_copy" if len(copies) == 1
                else "multiple_copies"
            ),
            "copy_reconciliation_status": (
                "not_applicable" if len(copies) < 2
                else "resolved" if decision is not None
                else "unresolved"
            ),
            "canonical_copy_id": (
                decision["canonical_copy_id"] if decision is not None
                else copies[0]["copy_id"] if len(copies) == 1
                else None
            ),
            "superseded_copy_ids": (
                decision["superseded_copy_ids"] if decision is not None else []
            ),
            "copy_ids": [copy["copy_id"] for copy in copies],
            "copies": copies,
            "tracker_entries_without_copy": without_copy,
            "iron_law_status": iron_status,
            "roadmap_status": roadmap_status,
            "causes": _dedupe_causes(causes),
        }
        dashboards.append(dashboard)

    dashboards.sort(key=lambda row: (
        not row["scope"]["in_worklist"],
        (row.get("client") or "").casefold(),
        row["original_id"],
    ))

    in_scope_rows = [row for row in dashboards if row["scope"]["in_worklist"]]
    in_scope_copies = [copy for row in in_scope_rows for copy in row["copies"]]
    topology = Counter(row["copy_status"] for row in in_scope_rows)
    roadmap = Counter(row["roadmap_status"] for row in in_scope_rows)
    iron_by_original = Counter(row["iron_law_status"] for row in in_scope_rows)
    iron_by_copy_count = Counter(copy["iron_law"]["status"] for copy in in_scope_copies)
    attribution_statuses = Counter(row["client_attribution"]["status"] for row in in_scope_rows)
    reconciliation_statuses = Counter(row["copy_reconciliation_status"] for row in in_scope_rows)
    orphan_iron_copy_ids = sorted(set(iron_by_copy) - tracker_copy_ids)
    orphan_attribution_original_ids = sorted(set(attribution_by_original) - all_original_ids)
    reused_copy_ids = {
        str(copy_id): sorted(original_ids)
        for copy_id, original_ids in sorted(copy_to_originals.items())
        if len(original_ids) > 1
    }

    summary = {
        "originals": {
            "total": len(dashboards),
            "in_scope": len(in_scope_rows),
            "out_of_scope": len(dashboards) - len(in_scope_rows),
        },
        "copy_topology_in_scope": {
            "never_copied": topology["never_copied"],
            "single_copy": topology["single_copy"],
            "multiple_copies": topology["multiple_copies"],
            "excess_copies": sum(max(0, len(row["copies"]) - 1) for row in in_scope_rows),
        },
        "copy_reconciliation_in_scope": {
            "resolved": reconciliation_statuses["resolved"],
            "unresolved": reconciliation_statuses["unresolved"],
            "not_applicable": reconciliation_statuses["not_applicable"],
            "superseded_copies": sum(
                len(row["superseded_copy_ids"]) for row in in_scope_rows
            ),
        },
        "copies": {
            "total": sum(len(row["copies"]) for row in dashboards),
            "in_scope": len(in_scope_copies),
            "out_of_scope": sum(len(row["copies"]) for row in dashboards if not row["scope"]["in_worklist"]),
        },
        "roadmap_in_scope": {
            key: roadmap[key]
            for key in ("complete", "residual", "unknown", "never_copied", "multiple_copies")
        },
        "iron_law_by_original_in_scope": {
            key: iron_by_original[key]
            for key in (*IRON_STATUSES, "not_applicable")
        },
        "iron_law_by_copy_in_scope": {
            key: iron_by_copy_count[key]
            for key in IRON_STATUSES
        },
        "client_attribution_in_scope": {
            key: attribution_statuses[key]
            for key in ("match", "mismatch", "no_default", "unknown", "owner_conflict", "not_provided")
        },
    }
    diagnostics = {
        "tracker_entries_without_original": orphan_tracker_rows,
        "copy_ids_reused_across_originals": reused_copy_ids,
        "iron_state": {
            **iron_diagnostics,
            "orphan_copy_ids": orphan_iron_copy_ids,
        },
        "client_attribution": {
            **attribution_diagnostics,
            "orphan_original_ids": orphan_attribution_original_ids,
        },
        "copy_decisions": {
            **decision_diagnostics,
            "orphan_original_ids": sorted(set(decisions_by_original) - all_original_ids),
            "unresolved_multiple_original_ids": sorted(
                row["original_id"]
                for row in in_scope_rows
                if row["copy_reconciliation_status"] == "unresolved"
            ),
        },
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "sources": sources or {
            "worklist": "provided",
            "tracker": "provided",
            "iron_state": iron_diagnostics["source"],
            "client_attribution": attribution_diagnostics["source"],
            "copy_decisions": decision_diagnostics["source"],
        },
        "summary": summary,
        "diagnostics": diagnostics,
        "dashboards": dashboards,
    }


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(f"fichier introuvable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON invalide dans {path}: {exc}") from exc


def _discover_iron_cache(explicit: Path | None) -> Path | None:
    if explicit is not None:
        if not explicit.exists():
            raise SystemExit(f"fichier Iron-Law introuvable: {explicit}")
        return explicit
    return next((path for path in IRON_CACHE_CANDIDATES if path.exists()), None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--worklist", type=Path, default=DEFAULT_WORKLIST)
    parser.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER)
    parser.add_argument(
        "--iron-state",
        type=Path,
        help="snapshot par copy_id ; sinon cherche iron-law-state.json / iron-law-cache.json",
    )
    parser.add_argument(
        "--client-attribution",
        type=Path,
        help=(
            "snapshot optionnel par original_id avec dashboard_default_clients, aliases explicites "
            "et scope_flags"
        ),
    )
    parser.add_argument(
        "--copy-decisions",
        type=Path,
        help="decisions exhaustives canonical/superseded pour les originaux multi-copies",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="fichier JSON local, ou '-' pour stdout")
    args = parser.parse_args(argv)

    iron_path = _discover_iron_cache(args.iron_state)
    iron_payload = _read_json(iron_path) if iron_path else None
    attribution_payload = _read_json(args.client_attribution) if args.client_attribution else None
    decisions_payload = _read_json(args.copy_decisions) if args.copy_decisions else None
    sources = {
        "worklist": str(args.worklist),
        "tracker": str(args.tracker),
        "iron_state": str(iron_path) if iron_path else "absent",
        "client_attribution": str(args.client_attribution) if args.client_attribution else "absent",
        "copy_decisions": str(args.copy_decisions) if args.copy_decisions else "absent",
    }
    manifest = build_manifest(
        _read_json(args.worklist),
        _read_json(args.tracker),
        iron_payload,
        client_attribution=attribution_payload,
        copy_decisions=decisions_payload,
        sources=sources,
    )
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        sys.stdout.write(rendered)
    else:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
        print(f"Manifeste ecrit: {output}")

    summary = manifest["summary"]
    topology = summary["copy_topology_in_scope"]
    reconciliation = summary["copy_reconciliation_in_scope"]
    iron = summary["iron_law_by_copy_in_scope"]
    report = (
        f"{summary['originals']['in_scope']} originaux dans le scope | "
        f"{topology['never_copied']} jamais copies | "
        f"{topology['multiple_copies']} avec copies multiples "
        f"({reconciliation['resolved']} resolus / {reconciliation['unresolved']} non resolus; "
        f"{topology['excess_copies']} copies en trop) | "
        f"Iron-Law copies: {iron['complete']} complete / {iron['residual']} residual / "
        f"{iron['unknown']} unknown"
    )
    print(report, file=sys.stderr if args.output == "-" else sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
