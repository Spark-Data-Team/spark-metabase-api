#!/usr/bin/env python3
"""Répare l'unique dépendance personnelle connue de la copie Inoui #26791.

L'opération est volontairement non paramétrable : elle clone la carte #14632 dans la
collection partagée #14115, puis repointe uniquement le dashcard #136040 du dashboard
#26791. Le dry-run est le mode par défaut. ``--yes`` est requis pour toute mutation.

Garde-fous d'application : snapshot complet avant le premier POST, payload carte
allowlisté, comparaison structure/SQL/tags/métadonnées du clone, comparaison de valeurs
source -> clone -> source dans le contexte du dashcard, diff dashboard limité à six
feuilles, PUT/relecture, ``verify_pipeline`` final et rollback automatique. Un clone créé
mais non utilisé est archivé au moindre échec dès que son caractère orphelin est prouvé.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable


REPO = Path(__file__).resolve().parent.parent
MIGRATION = REPO / "migration"
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from archive_collections import connect_resilient  # noqa: E402
import conv_lib  # noqa: E402
from migrate_client import verify_pipeline  # noqa: E402
import swap_lib  # noqa: E402


DASHBOARD_ID = 26791
ORIGINAL_DASHBOARD_ID = 20288
DASHCARD_ID = 136040
SOURCE_CARD_ID = 14632
SOURCE_COLLECTION_ID = 47
TARGET_COLLECTION_ID = 14115
EXPECTED_DATABASE_ID = 144
EXPECTED_MAPPING_COUNT = 5
EXPECTED_CLIENT = "Inoui Editions"
EXPECTED_WIRED_PARAMETER_SPECS = {
    "clients": {"parameter_id": "172d622a", "slug": "client"},
    "date": {"parameter_id": "3982dacd", "slug": "date"},
    "channel": {"parameter_id": "8d99ef62", "slug": "channel"},
    "campaign_type": {"parameter_id": "68480946", "slug": "type"},
    "campaign_category": {"parameter_id": "19c688f4", "slug": "category"},
}
EXPECTED_WIRED_TAGS = frozenset(EXPECTED_WIRED_PARAMETER_SPECS)
VALUE_TIME_TAG = "time_periods"
VALUE_WINDOW = "2026-05-01~2026-05-31"
READ_TIMEOUT_SECONDS = 60
WRITE_TIMEOUT_SECONDS = 60
QUERY_TIMEOUT_SECONDS = 300
SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_SNAPSHOT_DIR = MIGRATION / "personal-dependency-snapshots"
DEFAULT_LOCK_DIR = MIGRATION

# Champs fonctionnels acceptés par POST /api/card. Les ids, timestamps, permissions,
# moderation_reviews, embedding/public UUID et objets collection ne traversent jamais le
# payload. ``collection_id`` est fixé séparément, jamais copié depuis la source.
CARD_CREATE_REQUIRED = (
    "name",
    "dataset_query",
    "display",
    "visualization_settings",
    "result_metadata",
)
CARD_CREATE_OPTIONAL = (
    "description",
    "parameters",
    "parameter_mappings",
    "cache_ttl",
)
CARD_CREATE_FIELDS = CARD_CREATE_REQUIRED + CARD_CREATE_OPTIONAL

# Forme d'écriture minimale déjà utilisée par les migrations du dépôt. Les objets ``card``
# embarqués par GET, entity_id et timestamps ne sont jamais renvoyés à Metabase.
DASHCARD_WRITE_FIELDS = (
    "id",
    "card_id",
    "row",
    "col",
    "size_x",
    "size_y",
    "series",
    "parameter_mappings",
    "visualization_settings",
    "dashboard_tab_id",
    "inline_parameters",
    "action_id",
)

QUERY_COLUMN_FIELDS = (
    "name",
    "display_name",
    "base_type",
    "effective_type",
    "semantic_type",
    "source",
    "field_ref",
)


class RepairError(RuntimeError):
    """Précondition ou vérification fail-closed non satisfaite."""


class RepairTransactionError(RepairError):
    """Échec d'application avec état du rollback attaché."""

    def __init__(self, message: str, snapshot_path: Path, cleanup: dict[str, Any]):
        super().__init__(message)
        self.snapshot_path = snapshot_path
        self.cleanup = cleanup


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _dataset_query_for_guard(card: dict[str, Any]) -> Any:
    """Neutralise uniquement les UUIDs de la forme converted+legacy connue.

    Cette projection alimente notamment ``source_guard_state``. Elle reste volontairement
    inchangée par les tolérances de sérialisation propres au clone neuf.
    """
    dataset_query = _clone(card.get("dataset_query") or {})
    if not (
        card.get("legacy_query") is not None
        and isinstance(dataset_query, dict)
        and dataset_query.get("lib.convert/converted?") is True
    ):
        return dataset_query

    def without_lib_uuids(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: without_lib_uuids(child)
                for key, child in value.items()
                if key != "lib/uuid"
            }
        if isinstance(value, list):
            return [without_lib_uuids(child) for child in value]
        return value

    return without_lib_uuids(dataset_query)


def _positive_id(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise RepairError(f"{label} invalide: {value!r}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RepairError(f"{label} invalide: {value!r}") from exc
    if result <= 0:
        raise RepairError(f"{label} doit être un entier positif")
    return result


def _dashcards(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    return list(dashboard.get("dashcards") or dashboard.get("ordered_cards") or [])


def _dict_with_id(value: Any, expected_id: int) -> bool:
    if not isinstance(value, dict) or value.get("id") is None:
        return False
    try:
        return int(value["id"]) == expected_id
    except (TypeError, ValueError):
        return False


def _response_body(response: Any) -> dict[str, Any] | None:
    if isinstance(response, dict):
        return response
    try:
        body = response.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def _response_status(response: Any) -> int | None:
    return getattr(response, "status_code", None)


def _write_new_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def _replace_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    os.replace(temporary, path)
    return path


def connect_redacted():
    """Le client historique affiche parfois l'id de session; il ne doit pas fuiter."""
    try:
        with redirect_stdout(io.StringIO()):
            return connect_resilient()
    except (Exception, SystemExit) as exc:
        raise RepairError("authentification Metabase impossible") from exc


def _api_get(mb, endpoint: str, **kwargs):
    with redirect_stdout(io.StringIO()):
        return mb.get(endpoint, **kwargs)


def _api_post(mb, endpoint: str, *args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return mb.post(endpoint, *args, **kwargs)


def _api_put(mb, endpoint: str, *args, **kwargs):
    with redirect_stdout(io.StringIO()):
        return mb.put(endpoint, *args, **kwargs)


def collection_is_personal(collection: dict[str, Any]) -> bool:
    return bool(
        collection.get("is_personal")
        or collection.get("personal_owner_id") is not None
    )


def collection_is_archived(collection: dict[str, Any]) -> bool:
    return bool(collection.get("archived") or collection.get("archived_directly"))


def collection_card_ids(
    mb,
    collection_id: int,
    *,
    forbidden_active_name: str | None = None,
    allowed_active_name_id: int | None = None,
) -> set[int]:
    """Inventaire paginé et exhaustif des cartes d'une collection."""
    output: set[int] = set()
    limit, offset = 2000, 0
    while True:
        endpoint = (
            f"/api/collection/{collection_id}/items?models=card"
            f"&limit={limit}&offset={offset}"
        )
        try:
            payload = _api_get(mb, endpoint, timeout=READ_TIMEOUT_SECONDS)
        except TypeError:
            payload = _api_get(mb, endpoint)
        except Exception as exc:
            raise RepairError(
                f"inventaire cartes collection #{collection_id} inaccessible"
            ) from exc
        if isinstance(payload, dict):
            chunk, total = payload.get("data"), payload.get("total")
        elif isinstance(payload, list):
            chunk, total = payload, len(payload)
        else:
            raise RepairError(
                f"inventaire cartes collection #{collection_id} illisible"
            )
        if not isinstance(chunk, list):
            raise RepairError(
                f"inventaire cartes collection #{collection_id} incomplet"
            )
        for item in chunk:
            if not isinstance(item, dict) or item.get("id") is None:
                raise RepairError(
                    f"inventaire cartes collection #{collection_id} contient une ligne invalide"
                )
            output.add(_positive_id(item["id"], "collection.card_id"))
            if (
                forbidden_active_name is not None
                and not item.get("archived")
                and str(item.get("name") or "").strip().casefold()
                == forbidden_active_name.strip().casefold()
                and int(item["id"]) != int(allowed_active_name_id or 0)
            ):
                raise RepairError(
                    f"collection #{collection_id}: carte active de même nom déjà présente "
                    f"(#{item['id']})"
                )
        offset += len(chunk)
        if not chunk:
            break
        if isinstance(total, int):
            if offset >= total:
                break
        elif len(chunk) < limit:
            break
        if offset > 100_000:
            raise RepairError("inventaire collection anormalement volumineux")
    return output


@contextmanager
def operation_lock(directory: Path):
    """Verrou local exclusif : deux exécutions du chantier ne peuvent pas se croiser."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".fix-personal-dependency-26791.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RepairError(
            f"une autre réparation semble active (verrou {path})"
        ) from exc
    try:
        os.write(
            descriptor,
            (
                f"pid={os.getpid()}\n"
                f"created_at={datetime.now(timezone.utc).isoformat()}\n"
            ).encode("utf-8"),
        )
    finally:
        os.close(descriptor)
    try:
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def card_functional_state(card: dict[str, Any]) -> dict[str, Any]:
    """État que le clone doit préserver bit pour bit hors id/collection."""
    return {
        "name": card.get("name"),
        "description": card.get("description"),
        "dataset_query": _dataset_query_for_guard(card),
        "display": card.get("display"),
        "visualization_settings": _clone(card.get("visualization_settings") or {}),
        "result_metadata": _clone(card.get("result_metadata") or []),
        "parameters": _clone(card.get("parameters") or []),
        "parameter_mappings": _clone(card.get("parameter_mappings") or []),
        "cache_ttl": card.get("cache_ttl"),
    }


def source_guard_state(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "collection_id": card.get("collection_id"),
        "archived": bool(card.get("archived")),
        "archived_directly": bool(card.get("archived_directly")),
        "database_id": card_database_id(card),
        "source_card_id": card.get("source_card_id"),
        "legacy_query": _clone(card.get("legacy_query")),
        "functional": card_functional_state(card),
    }


def _normalize_clone_pair_query(value: Any, *, inside_dimension: bool = False) -> Any:
    """Projection des seules réécritures serveur observées sur le clone #14632.

    ``lib/uuid`` est une identité interne réhydratée. Le booléen
    ``lib/transformation-added-base-type=true`` est une annotation que Metabase peut
    ajouter ou retirer dans la métadonnée d'une ``dimension`` lors du POST. Une valeur
    différente de ``true`` et toute occurrence hors dimension restent significatives.
    """
    if isinstance(value, dict):
        output = {}
        for key, child in value.items():
            if key == "lib/uuid":
                continue
            if (
                inside_dimension
                and key == "lib/transformation-added-base-type"
                and child is True
            ):
                continue
            output[key] = _normalize_clone_pair_query(
                child,
                inside_dimension=inside_dimension or key == "dimension",
            )
        return output
    if isinstance(value, list):
        return [
            _normalize_clone_pair_query(
                child, inside_dimension=inside_dimension
            )
            for child in value
        ]
    return value


def clone_comparison_functional_states(
    source: dict[str, Any], clone: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """États comparables, exclusivement pour #14632 -> collection #14115.

    Le POST live a prouvé que Metabase peut supprimer le marqueur top-level
    ``lib.convert/converted?=true`` sur le clone. On accepte son absence (ou sa
    conservation à ``true``), jamais une autre valeur. Cette projection n'est utilisée
    ni par ``source_guard_state`` ni par les contrôles de dérive de la source.
    """
    if not _dict_with_id(source, SOURCE_CARD_ID):
        raise RepairError(f"source de comparaison doit être #{SOURCE_CARD_ID}")
    if source.get("collection_id") != SOURCE_COLLECTION_ID:
        raise RepairError(
            f"source de comparaison hors collection #{SOURCE_COLLECTION_ID}"
        )
    if source.get("legacy_query") is None:
        raise RepairError("source de comparaison sans legacy_query")
    if not isinstance(clone, dict) or clone.get("id") is None:
        raise RepairError("clone de comparaison sans id")
    clone_id = _positive_id(clone["id"], "clone.id")
    if clone_id == SOURCE_CARD_ID:
        raise RepairError("clone de comparaison identique à la source")
    if clone.get("collection_id") != TARGET_COLLECTION_ID:
        raise RepairError(
            f"clone de comparaison hors collection #{TARGET_COLLECTION_ID}"
        )

    source_query = _clone(source.get("dataset_query") or {})
    clone_query = _clone(clone.get("dataset_query") or {})
    if not isinstance(source_query, dict) or not isinstance(clone_query, dict):
        raise RepairError("dataset_query source/clone illisible")
    marker = "lib.convert/converted?"
    if source_query.get(marker) is not True:
        raise RepairError("source de comparaison sans marqueur converted=true")
    missing = object()
    clone_marker = clone_query.get(marker, missing)
    if clone_marker is not missing and clone_marker is not True:
        raise RepairError(
            f"clone de comparaison avec marqueur converted invalide: {clone_marker!r}"
        )
    source_query.pop(marker)
    clone_query.pop(marker, None)

    source_state = card_functional_state(source)
    clone_state = card_functional_state(clone)
    source_state["dataset_query"] = _normalize_clone_pair_query(source_query)
    clone_state["dataset_query"] = _normalize_clone_pair_query(clone_query)
    return source_state, clone_state


def _native_and_tags_with_query(
    card: dict[str, Any], dataset_query: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    view = deepcopy(card)
    view["dataset_query"] = _clone(dataset_query)
    return conv_lib.native_and_tags(view)


def card_database_id(card: dict[str, Any]) -> int | None:
    """Base exposée directement par GET, avec fallback sur le dataset_query."""
    value = card.get("database_id")
    if value is None:
        value = (card.get("dataset_query") or {}).get("database")
    if value is None:
        legacy = card.get("legacy_query")
        if isinstance(legacy, str):
            try:
                legacy = json.loads(legacy)
            except (TypeError, ValueError):
                legacy = None
        if isinstance(legacy, dict):
            value = legacy.get("database")
    if value is None:
        return None
    return _positive_id(value, "card.database_id")


def build_clone_payload(source: dict[str, Any]) -> dict[str, Any]:
    if not _dict_with_id(source, SOURCE_CARD_ID):
        raise RepairError(f"carte source #{SOURCE_CARD_ID} inaccessible")
    missing = [field for field in CARD_CREATE_REQUIRED if field not in source]
    if missing:
        raise RepairError(f"carte source incomplète: champs absents {missing}")
    if not isinstance(source.get("name"), str) or not source["name"].strip():
        raise RepairError("nom de carte source absent")
    if not isinstance(source.get("dataset_query"), dict) or not source["dataset_query"]:
        raise RepairError("dataset_query source absente ou illisible")
    if not isinstance(source.get("visualization_settings"), dict):
        raise RepairError("visualization_settings source illisible")
    if not isinstance(source.get("result_metadata"), list) or not source["result_metadata"]:
        raise RepairError("result_metadata source absente ou vide")

    sql, tags = conv_lib.native_and_tags(source)
    if not isinstance(sql, str) or not sql.strip():
        raise RepairError("SQL natif source introuvable; clone refusé")
    if not isinstance(tags, dict):
        raise RepairError("template-tags source illisibles")
    if source.get("source_card_id") is not None:
        raise RepairError("carte source non autonome: source_card_id présent")
    query_blob = json.dumps(
        {
            "dataset_query": source.get("dataset_query"),
            "legacy_query": source.get("legacy_query"),
        },
        ensure_ascii=False,
    )
    if re.search(r"\bcard__\d+\b", query_blob, flags=re.IGNORECASE):
        raise RepairError("carte source non autonome: référence card__ détectée")
    residuals = sorted(conv_lib.old_conversion_columns(sql))
    if residuals:
        raise RepairError(
            f"carte source encore positionnelle: {residuals}"
        )

    payload = {
        field: _clone(source[field])
        for field in CARD_CREATE_FIELDS
        if field in source
    }
    payload["collection_id"] = TARGET_COLLECTION_ID
    return payload


def _compact_series(series: Any) -> list[dict[str, Any]]:
    output = []
    for index, item in enumerate(series or []):
        card_id = _series_card_id(item, index=index)
        output.append({"id": card_id, "card_id": card_id})
    return output


def _series_card_id(item: Any, *, index: int) -> int:
    if not isinstance(item, dict):
        raise RepairError(f"series[{index}] doit être un objet")
    candidates = [
        item.get("id"),
        item.get("card_id"),
        (item.get("card") or {}).get("id")
        if isinstance(item.get("card"), dict)
        else None,
    ]
    ids = {
        _positive_id(candidate, f"series[{index}].card_id")
        for candidate in candidates
        if candidate is not None
    }
    if len(ids) != 1:
        raise RepairError(
            f"series[{index}]: id absent ou ambigu ({sorted(ids)})"
        )
    return next(iter(ids))


def _series_write_payload(series: Any) -> list[dict[str, int]]:
    """Schéma PUT minimal : un id de carte, aucun champ serveur expansé."""
    if series is None:
        return []
    if not isinstance(series, list):
        raise RepairError("series doit être une liste")
    return [
        {"id": _series_card_id(item, index=index)}
        for index, item in enumerate(series)
    ]


def dashboard_rewire_state(dashboard: dict[str, Any]) -> dict[str, Any]:
    """Projection stable utilisée pour prouver les six seules feuilles modifiées."""
    dashcards: dict[str, Any] = {}
    for dashcard in _dashcards(dashboard):
        dashcard_id = _positive_id(dashcard.get("id"), "dashcard.id")
        key = str(dashcard_id)
        if key in dashcards:
            raise RepairError(f"dashcard #{dashcard_id} dupliqué")
        dashcards[key] = {
            "id": dashcard_id,
            "card_id": dashcard.get("card_id")
            or (dashcard.get("card") or {}).get("id"),
            "dashboard_tab_id": dashcard.get("dashboard_tab_id"),
            "row": dashcard.get("row"),
            "col": dashcard.get("col"),
            "size_x": dashcard.get("size_x"),
            "size_y": dashcard.get("size_y"),
            "action_id": dashcard.get("action_id"),
            "inline_parameters": _clone(dashcard.get("inline_parameters") or []),
            "parameter_mappings": _clone(dashcard.get("parameter_mappings") or []),
            "series": _compact_series(dashcard.get("series")),
            "visualization_settings": _clone(
                dashcard.get("visualization_settings") or {}
            ),
        }
    return {
        "id": dashboard.get("id"),
        "name": dashboard.get("name"),
        "description": dashboard.get("description"),
        "collection_id": dashboard.get("collection_id"),
        "archived": bool(dashboard.get("archived")),
        "archived_directly": bool(dashboard.get("archived_directly")),
        "parameters": _clone(dashboard.get("parameters") or []),
        "tabs": _clone(dashboard.get("tabs") or []),
        "width": dashboard.get("width"),
        "auto_apply_filters": dashboard.get("auto_apply_filters"),
        "dashcards": dashcards,
    }


def _diff_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    if type(before) is not type(after):
        return [prefix or "$"]
    if isinstance(before, dict):
        paths = []
        for key in sorted(set(before) | set(after), key=str):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                paths.append(path)
            else:
                paths.extend(_diff_paths(before[key], after[key], path))
        return paths
    if isinstance(before, list):
        paths = []
        if len(before) != len(after):
            paths.append(f"{prefix}.length" if prefix else "length")
        for index, (left, right) in enumerate(zip(before, after)):
            path = f"{prefix}.{index}" if prefix else str(index)
            paths.extend(_diff_paths(left, right, path))
        return paths
    return [] if before == after else [prefix or "$"]


def expected_dashboard_diff_paths() -> list[str]:
    base = f"dashcards.{DASHCARD_ID}"
    return [
        f"{base}.card_id",
        *[
            f"{base}.parameter_mappings.{index}.card_id"
            for index in range(EXPECTED_MAPPING_COUNT)
        ],
    ]


def assert_exact_dashboard_diff(before: dict[str, Any], after: dict[str, Any]) -> None:
    actual = sorted(_diff_paths(
        dashboard_rewire_state(before), dashboard_rewire_state(after)
    ))
    expected = sorted(expected_dashboard_diff_paths())
    if actual != expected:
        raise RepairError(
            "diff dashboard hors allowlist: "
            f"attendu {expected}, obtenu {actual}"
        )


def _card_id_reference_paths(value: Any, prefix: str = "") -> list[str]:
    paths = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key == "card_id" and child == SOURCE_CARD_ID:
                paths.append(path)
            paths.extend(_card_id_reference_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            path = f"{prefix}.{index}" if prefix else str(index)
            paths.extend(_card_id_reference_paths(child, path))
    return paths


def validate_target_dashcard(dashboard: dict[str, Any], source: dict[str, Any]) -> None:
    if not _dict_with_id(dashboard, DASHBOARD_ID):
        raise RepairError(f"dashboard #{DASHBOARD_ID} inaccessible")
    if dashboard.get("archived") or dashboard.get("archived_directly"):
        raise RepairError(f"dashboard #{DASHBOARD_ID} archivé")
    matches = [dc for dc in _dashcards(dashboard) if dc.get("id") == DASHCARD_ID]
    if len(matches) != 1:
        raise RepairError(
            f"dashcard #{DASHCARD_ID}: attendu exactement une occurrence, obtenu {len(matches)}"
        )
    dashcard = matches[0]
    if dashcard.get("card_id") != SOURCE_CARD_ID:
        raise RepairError(
            f"dashcard #{DASHCARD_ID}: carte attendue #{SOURCE_CARD_ID}, "
            f"relue #{dashcard.get('card_id')}"
        )
    mappings = dashcard.get("parameter_mappings")
    if not isinstance(mappings, list) or len(mappings) != EXPECTED_MAPPING_COUNT:
        raise RepairError(
            f"dashcard #{DASHCARD_ID}: {EXPECTED_MAPPING_COUNT} mappings attendus"
        )
    _sql, tags = conv_lib.native_and_tags(source)
    wired_tags = set()
    wired_parameter_ids: dict[str, Any] = {}
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict) or mapping.get("card_id") != SOURCE_CARD_ID:
            raise RepairError(
                f"dashcard #{DASHCARD_ID}: mapping {index} ne cible pas #{SOURCE_CARD_ID}"
            )
        target = mapping.get("target")
        try:
            tag = target[1][1] if target[1][0] == "template-tag" else None
        except Exception:
            tag = None
        if not tag or tag not in tags:
            raise RepairError(
                f"dashcard #{DASHCARD_ID}: mapping {index} vers un tag absent/invalide"
            )
        if tag in wired_parameter_ids:
            raise RepairError(f"dashcard #{DASHCARD_ID}: tag {tag} câblé plusieurs fois")
        wired_tags.add(tag)
        wired_parameter_ids[tag] = mapping.get("parameter_id")
    if wired_tags != EXPECTED_WIRED_TAGS:
        raise RepairError(
            f"dashcard #{DASHCARD_ID}: tags câblés attendus "
            f"{sorted(EXPECTED_WIRED_TAGS)}, relus {sorted(wired_tags)}"
        )
    expected_parameter_ids = {
        tag: spec["parameter_id"]
        for tag, spec in EXPECTED_WIRED_PARAMETER_SPECS.items()
    }
    if wired_parameter_ids != expected_parameter_ids:
        raise RepairError(
            f"dashcard #{DASHCARD_ID}: ids de paramètres inattendus: "
            f"{wired_parameter_ids}; attendu {expected_parameter_ids}"
        )
    dashboard_parameters = dashboard.get("parameters") or []
    for tag, spec in EXPECTED_WIRED_PARAMETER_SPECS.items():
        matches = [
            parameter
            for parameter in dashboard_parameters
            if isinstance(parameter, dict)
            and parameter.get("id") == spec["parameter_id"]
        ]
        if len(matches) != 1:
            raise RepairError(
                f"dashboard #{DASHBOARD_ID}: paramètre {spec['parameter_id']} de {tag} "
                f"attendu exactement une fois"
            )
        if matches[0].get("slug") != spec["slug"]:
            raise RepairError(
                f"dashboard #{DASHBOARD_ID}: slug de {spec['parameter_id']} attendu "
                f"{spec['slug']!r}, relu {matches[0].get('slug')!r}"
            )

    reference_paths = sorted(
        _card_id_reference_paths(dashboard_rewire_state(dashboard))
    )
    expected = sorted(expected_dashboard_diff_paths())
    if reference_paths != expected:
        raise RepairError(
            f"références à #{SOURCE_CARD_ID} hors cible: {reference_paths}; "
            f"attendu {expected}"
        )


def prepare_dashboard(dashboard: dict[str, Any], clone_id: int) -> dict[str, Any]:
    clone_id = _positive_id(clone_id, "clone_id")
    if clone_id == SOURCE_CARD_ID:
        raise RepairError("le clone ne peut pas réutiliser l'id source")
    rewritten, changed_count = swap_lib.rewrite_dashcards(
        _dashcards(dashboard), SOURCE_CARD_ID, clone_id
    )
    if changed_count != 1:
        raise RepairError(
            f"swap_lib devait modifier un dashcard, résultat={changed_count}"
        )
    prepared = deepcopy(dashboard)
    if "dashcards" in prepared:
        prepared["dashcards"] = rewritten
    elif "ordered_cards" in prepared:
        prepared["ordered_cards"] = rewritten
    else:
        raise RepairError("dashboard sans collection de dashcards")
    assert_exact_dashboard_diff(dashboard, prepared)
    return prepared


def dashboard_write_payload(dashboard: dict[str, Any]) -> dict[str, Any]:
    dashcards = []
    for dashcard in _dashcards(dashboard):
        item = {
            field: _clone(dashcard[field])
            for field in DASHCARD_WRITE_FIELDS
            if field in dashcard and field != "series"
        }
        item["series"] = _series_write_payload(dashcard.get("series") or [])
        if item.get("id") is None:
            raise RepairError("dashcard sans id stable dans le payload")
        dashcards.append(item)
    payload: dict[str, Any] = {"dashcards": dashcards}
    if "tabs" in dashboard:
        payload["tabs"] = _clone(dashboard.get("tabs") or [])
    return payload


def _swap_safety_view(card: dict[str, Any]) -> dict[str, Any]:
    """Normalise les cartes MLv2 pour le garde-fou historique de ``swap_lib``."""
    view = deepcopy(card)
    database_id = card_database_id(card)
    if database_id is not None:
        view["database_id"] = database_id
    legacy = view.get("legacy_query")
    if not legacy:
        sql, tags = conv_lib.native_and_tags(card)
        if sql:
            view["legacy_query"] = {
                "database": database_id,
                "type": "native",
                "native": {"query": sql, "template-tags": _clone(tags)},
            }
    return view


def validate_clone(source: dict[str, Any], clone: dict[str, Any], clone_id: int) -> None:
    if not _dict_with_id(clone, clone_id):
        raise RepairError(f"clone #{clone_id} inaccessible")
    if clone_id == SOURCE_CARD_ID:
        raise RepairError("POST carte a renvoyé l'id source")
    if clone.get("collection_id") != TARGET_COLLECTION_ID:
        raise RepairError(
            f"clone #{clone_id}: collection attendue #{TARGET_COLLECTION_ID}, "
            f"relue #{clone.get('collection_id')}"
        )
    if clone.get("archived") or clone.get("archived_directly"):
        raise RepairError(f"clone #{clone_id} archivé")
    source_database_id = card_database_id(source)
    clone_database_id = card_database_id(clone)
    if source_database_id != EXPECTED_DATABASE_ID:
        raise RepairError(
            f"source: base attendue #{EXPECTED_DATABASE_ID}, relue #{source_database_id}"
        )
    if clone_database_id != EXPECTED_DATABASE_ID:
        raise RepairError(
            f"clone #{clone_id}: base attendue #{EXPECTED_DATABASE_ID}, "
            f"relue #{clone_database_id}"
        )
    source_state, clone_state = clone_comparison_functional_states(source, clone)
    if source_state != clone_state:
        paths = _diff_paths(source_state, clone_state)
        raise RepairError(f"clone #{clone_id}: structure/métadonnées divergentes: {paths}")
    source_sql, source_tags = _native_and_tags_with_query(
        source, source_state["dataset_query"]
    )
    clone_sql, clone_tags = _native_and_tags_with_query(
        clone, clone_state["dataset_query"]
    )
    if source_sql != clone_sql:
        raise RepairError(f"clone #{clone_id}: SQL divergent")
    if source_tags != clone_tags:
        raise RepairError(f"clone #{clone_id}: template-tags divergents")
    problems = swap_lib.swap_safety_check(
        _swap_safety_view(source),
        _swap_safety_view(clone),
        set(EXPECTED_WIRED_TAGS),
    )
    if problems:
        raise RepairError(
            f"clone #{clone_id}: swap_safety_check en échec: {problems}"
        )


def _query_result(response: Any, label: str) -> dict[str, Any]:
    status = _response_status(response)
    # Metabase 1.62 peut répondre HTTP 202 tout en livrant immédiatement un corps
    # terminal ``status=completed`` avec les lignes. Le statut métier du corps reste
    # donc le garde-fou décisif; tout autre HTTP ou état non terminal est refusé.
    if status is not None and status not in {200, 202}:
        raise RepairError(f"{label}: requête HTTP {status}")
    body = _response_body(response)
    if not isinstance(body, dict) or body.get("status") != "completed":
        error = body.get("error") if isinstance(body, dict) else None
        raise RepairError(f"{label}: requête non terminée ({error or 'réponse illisible'})")
    data = body.get("data")
    if not isinstance(data, dict):
        raise RepairError(f"{label}: données absentes")
    cols, rows = data.get("cols"), data.get("rows")
    if not isinstance(cols, list) or not cols:
        raise RepairError(f"{label}: colonnes absentes")
    if not isinstance(rows, list) or not rows:
        raise RepairError(f"{label}: résultat vide, équivalence non prouvée")
    normalized_cols = []
    for index, column in enumerate(cols):
        if not isinstance(column, dict) or not column.get("name"):
            raise RepairError(f"{label}: métadonnée colonne {index} invalide")
        normalized_cols.append({
            field: _clone(column.get(field)) for field in QUERY_COLUMN_FIELDS
        })
    return {"cols": normalized_cols, "rows": _clone(rows)}


def value_test_parameters(
    dashboard: dict[str, Any], source_card: dict[str, Any]
) -> list[dict[str, Any]]:
    """Construit des paramètres carte explicites, identiques pour source et clone.

    On n'utilise volontairement pas la route dashcard : avant le PUT, ses mappings
    contiennent encore ``card_id=14632`` et rien ne permettrait de prouver qu'ils sont
    appliqués à un clone passé dans l'URL. Ici chaque paramètre cible directement le
    template-tag de la carte exécutée.
    """
    dashcard = next(
        (item for item in _dashcards(dashboard) if item.get("id") == DASHCARD_ID),
        None,
    )
    if not dashcard:
        raise RepairError(f"dashcard #{DASHCARD_ID} absent du test de valeurs")
    dashboard_parameters = {
        parameter.get("id"): parameter
        for parameter in dashboard.get("parameters") or []
        if parameter.get("id") is not None
    }
    _sql, source_tags = conv_lib.native_and_tags(source_card)
    by_tag: dict[str, dict[str, Any]] = {}
    for mapping in dashcard.get("parameter_mappings") or []:
        target = mapping.get("target")
        try:
            tag = target[1][1] if target[1][0] == "template-tag" else None
        except Exception:
            tag = None
        if tag not in EXPECTED_WIRED_TAGS:
            continue
        if tag in by_tag:
            raise RepairError(f"mapping {tag} dupliqué pour le test de valeurs")
        parameter = dashboard_parameters.get(mapping.get("parameter_id"))
        if not isinstance(parameter, dict):
            raise RepairError(f"paramètre dashboard de {tag} introuvable")
        card_tag = source_tags.get(tag)
        if not isinstance(card_tag, dict):
            raise RepairError(f"template-tag source {tag} introuvable")
        if tag == "clients":
            value = [EXPECTED_CLIENT]
        elif tag == "date":
            value = VALUE_WINDOW
        else:
            value = _clone(parameter.get("default"))
        by_tag[tag] = {
            "type": card_tag.get("widget-type") or parameter.get("type") or "string/=",
            "value": value,
            "target": _clone(mapping.get("target")),
        }
    if set(by_tag) != EXPECTED_WIRED_TAGS:
        raise RepairError(
            f"mappings incomplets pour le test de valeurs: {sorted(by_tag)}"
        )
    parameters = [
        by_tag[tag]
        for tag in sorted(by_tag)
        # Les filtres optionnels sans défaut sont volontairement omis. Source et clone
        # partagent la même requête et reçoivent exactement le même tableau final.
        if by_tag[tag]["value"] is not None
    ]

    time_tag = source_tags.get(VALUE_TIME_TAG)
    if not isinstance(time_tag, dict) or time_tag.get("default") is None:
        raise RepairError(
            f"défaut source {VALUE_TIME_TAG} absent; test de valeurs refusé"
        )
    target_kind = (
        "dimension"
        if time_tag.get("dimension") is not None
        or time_tag.get("type") in {"dimension", "temporal-unit"}
        else "variable"
    )
    parameters.append({
        "type": (
            "temporal-unit"
            if time_tag.get("type") == "temporal-unit"
            else time_tag.get("widget-type") or time_tag.get("type") or "category"
        ),
        "value": _clone(time_tag["default"]),
        "target": [target_kind, ["template-tag", VALUE_TIME_TAG]],
    })
    return parameters


def query_card_with_parameters(
    mb,
    card_id: int,
    label: str,
    parameters: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint = f"/api/card/{card_id}/query"
    try:
        response = _api_post(
            mb,
            endpoint,
            "raw",
            json={"parameters": _clone(parameters)},
            timeout=QUERY_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise RepairError(f"{label}: exécution impossible") from exc
    return _query_result(response, label)


def verify_value_equivalence(
    mb,
    clone_id: int,
    dashboard: dict[str, Any],
    source_card: dict[str, Any],
) -> dict[str, Any]:
    """Triple lecture : refuse un résultat vide, changeant ou différent du clone."""
    parameters = value_test_parameters(dashboard, source_card)
    source_before = query_card_with_parameters(
        mb, SOURCE_CARD_ID, "source avant", parameters
    )
    clone = query_card_with_parameters(mb, clone_id, "clone", parameters)
    source_after = query_card_with_parameters(
        mb, SOURCE_CARD_ID, "source après", parameters
    )
    if source_before != source_after:
        raise RepairError("résultat source instable pendant le test de valeurs")
    if source_before != clone:
        raise RepairError("résultat clone différent de la source")
    return {
        "status": "IDENTICAL_STABLE_NON_EMPTY",
        "result_hash": stable_hash(source_before),
        "row_count": len(source_before["rows"]),
        "column_count": len(source_before["cols"]),
        "window": VALUE_WINDOW,
        "parameters": parameters,
    }


def build_preflight(mb) -> dict[str, Any]:
    try:
        dashboard = _api_get(mb, f"/api/dashboard/{DASHBOARD_ID}")
        original_dashboard = _api_get(
            mb, f"/api/dashboard/{ORIGINAL_DASHBOARD_ID}"
        )
        source = _api_get(mb, f"/api/card/{SOURCE_CARD_ID}")
        source_collection = _api_get(mb, f"/api/collection/{SOURCE_COLLECTION_ID}")
        target_collection = _api_get(mb, f"/api/collection/{TARGET_COLLECTION_ID}")
    except Exception as exc:
        raise RepairError("préflight live incomplet") from exc
    if not _dict_with_id(source_collection, SOURCE_COLLECTION_ID):
        raise RepairError(f"collection source #{SOURCE_COLLECTION_ID} inaccessible")
    if not collection_is_personal(source_collection):
        raise RepairError(f"collection source #{SOURCE_COLLECTION_ID} n'est plus personnelle")
    if collection_is_archived(source_collection):
        raise RepairError(f"collection source #{SOURCE_COLLECTION_ID} archivée")
    if not _dict_with_id(target_collection, TARGET_COLLECTION_ID):
        raise RepairError(f"collection cible #{TARGET_COLLECTION_ID} inaccessible")
    if collection_is_personal(target_collection):
        raise RepairError(f"collection cible #{TARGET_COLLECTION_ID} est personnelle")
    if collection_is_archived(target_collection):
        raise RepairError(f"collection cible #{TARGET_COLLECTION_ID} archivée")
    if not _dict_with_id(source, SOURCE_CARD_ID):
        raise RepairError(f"carte source #{SOURCE_CARD_ID} inaccessible")
    if not _dict_with_id(original_dashboard, ORIGINAL_DASHBOARD_ID):
        raise RepairError(f"dashboard original #{ORIGINAL_DASHBOARD_ID} inaccessible")
    if source.get("collection_id") != SOURCE_COLLECTION_ID:
        raise RepairError(
            f"carte source #{SOURCE_CARD_ID}: collection attendue #{SOURCE_COLLECTION_ID}, "
            f"relue #{source.get('collection_id')}"
        )
    if source.get("archived") or source.get("archived_directly"):
        raise RepairError(f"carte source #{SOURCE_CARD_ID} archivée")
    if card_database_id(source) != EXPECTED_DATABASE_ID:
        raise RepairError(
            f"carte source #{SOURCE_CARD_ID}: base attendue #{EXPECTED_DATABASE_ID}, "
            f"relue #{card_database_id(source)}"
        )
    payload = build_clone_payload(source)
    validate_target_dashcard(dashboard, source)
    # Ce contrôle doit échouer au préflight, avant création du moindre clone.
    value_test_parameters(dashboard, source)
    existing_target_card_ids = collection_card_ids(
        mb,
        TARGET_COLLECTION_ID,
        forbidden_active_name=str(source.get("name") or ""),
    )
    return {
        "dashboard": _clone(dashboard),
        "source_card": _clone(source),
        "clone_payload": payload,
        "existing_target_card_ids": sorted(existing_target_card_ids),
        "source_guard_hash": stable_hash(source_guard_state(source)),
        "original_dashboard_hash": stable_hash(
            dashboard_rewire_state(original_dashboard)
        ),
        "dashboard_hash": stable_hash(dashboard_rewire_state(dashboard)),
        "clone_payload_hash": stable_hash(payload),
        "expected_diff_paths": expected_dashboard_diff_paths(),
    }


def preflight_summary(preflight: dict[str, Any]) -> dict[str, Any]:
    source = preflight["source_card"]
    _sql, tags = conv_lib.native_and_tags(source)
    return {
        "status": "READY",
        "dashboard_id": DASHBOARD_ID,
        "original_dashboard_id": ORIGINAL_DASHBOARD_ID,
        "dashcard_id": DASHCARD_ID,
        "source_card_id": SOURCE_CARD_ID,
        "source_collection_id": SOURCE_COLLECTION_ID,
        "target_collection_id": TARGET_COLLECTION_ID,
        "database_id": EXPECTED_DATABASE_ID,
        "mapping_count": EXPECTED_MAPPING_COUNT,
        "template_tags": sorted(tags),
        "source_guard_hash": preflight["source_guard_hash"],
        "original_dashboard_hash": preflight["original_dashboard_hash"],
        "dashboard_hash": preflight["dashboard_hash"],
        "clone_payload_hash": preflight["clone_payload_hash"],
        "expected_diff_paths": preflight["expected_diff_paths"],
    }


def _snapshot_document(preflight: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "operation": "fix_personal_dependency_26791",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PREPARED",
        "ids": {
            "dashboard_id": DASHBOARD_ID,
            "original_dashboard_id": ORIGINAL_DASHBOARD_ID,
            "dashcard_id": DASHCARD_ID,
            "source_card_id": SOURCE_CARD_ID,
            "source_collection_id": SOURCE_COLLECTION_ID,
            "target_collection_id": TARGET_COLLECTION_ID,
        },
        "source_card": _clone(preflight["source_card"]),
        "dashboard": _clone(preflight["dashboard"]),
        "clone_payload": _clone(preflight["clone_payload"]),
        "existing_target_card_ids": list(preflight["existing_target_card_ids"]),
        "preconditions": preflight_summary(preflight),
        "clone_id": None,
        "value_guard": None,
        "cleanup": None,
    }


def write_snapshot(preflight: dict[str, Any], directory: Path) -> tuple[Path, dict[str, Any]]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"dashboard-{DASHBOARD_ID}-card-{SOURCE_CARD_ID}-{stamp}.json"
    document = _snapshot_document(preflight)
    _write_new_json(path, document)
    return path, document


def _create_card(mb, payload: dict[str, Any]) -> int:
    response = _api_post(
        mb,
        "/api/card",
        "raw",
        json=_clone(payload),
        timeout=WRITE_TIMEOUT_SECONDS,
    )
    status = _response_status(response)
    if status is not None and status not in (200, 201):
        raise RepairError(f"création clone HTTP {status}")
    body = _response_body(response)
    if not isinstance(body, dict) or body.get("id") is None:
        raise RepairError("création clone sans id relisible")
    clone_id = _positive_id(body["id"], "clone.id")
    if clone_id == SOURCE_CARD_ID:
        raise RepairError("création clone a renvoyé l'id source")
    return clone_id


def _read_card(mb, card_id: int) -> dict[str, Any]:
    try:
        card = _api_get(mb, f"/api/card/{card_id}")
    except Exception as exc:
        raise RepairError(f"carte #{card_id} inaccessible") from exc
    if not _dict_with_id(card, card_id):
        raise RepairError(f"carte #{card_id} inaccessible")
    return card


def discover_created_clone(mb, preflight: dict[str, Any]) -> tuple[int | None, str]:
    """Récupère un clone exact après une réponse POST ambiguë, sans deviner."""
    try:
        after = collection_card_ids(mb, TARGET_COLLECTION_ID)
    except RepairError as exc:
        return None, f"redécouverte impossible: {exc}"
    before = set(preflight["existing_target_card_ids"])
    candidates = []
    for card_id in sorted(after - before):
        try:
            card = _read_card(mb, card_id)
            source_state, clone_state = clone_comparison_functional_states(
                preflight["source_card"], card
            )
        except RepairError:
            continue
        if (
            card.get("collection_id") == TARGET_COLLECTION_ID
            and not card.get("archived")
            and clone_state == source_state
        ):
            candidates.append(card_id)
    if len(candidates) == 1:
        return candidates[0], "clone exact redécouvert après réponse ambiguë"
    return None, f"redécouverte non univoque: candidats={candidates}"


def _dashboard_ids(value: Any) -> list[int] | None:
    if isinstance(value, dict) and isinstance(value.get("data"), list):
        value = value["data"]
    if not isinstance(value, list):
        return None
    ids = []
    for item in value:
        if not isinstance(item, dict) or item.get("id") is None:
            return None
        ids.append(_positive_id(item["id"], "card.dashboard_id"))
    return sorted(set(ids))


def clone_dashboard_ids(mb, clone_id: int) -> list[int]:
    try:
        payload = _api_get(mb, f"/api/card/{clone_id}/dashboards")
    except Exception as exc:
        raise RepairError(f"usages du clone #{clone_id} inaccessibles") from exc
    ids = _dashboard_ids(payload)
    if ids is None:
        raise RepairError(f"usages du clone #{clone_id} illisibles")
    return ids


def archive_clone_if_orphan(mb, clone_id: int) -> dict[str, Any]:
    """Archive seulement après preuve live qu'aucun dashboard ne référence le clone."""
    try:
        dashboard_ids = clone_dashboard_ids(mb, clone_id)
    except RepairError as exc:
        return {"status": "ORPHAN_STATUS_UNKNOWN", "error": str(exc)}
    if dashboard_ids:
        return {"status": "NOT_ORPHAN", "dashboard_ids": dashboard_ids}
    try:
        response = _api_put(
            mb,
            f"/api/card/{clone_id}",
            "raw",
            json={"archived": True},
            timeout=WRITE_TIMEOUT_SECONDS,
        )
        status = _response_status(response)
        if status is not None and status != 200:
            return {"status": "ARCHIVE_FAILED", "http_status": status}
        reread = _read_card(mb, clone_id)
    except Exception as exc:
        return {"status": "ARCHIVE_FAILED", "error": str(exc)}
    if not reread.get("archived"):
        return {"status": "ARCHIVE_DIVERGENT"}
    return {"status": "ARCHIVED_ORPHAN", "clone_id": clone_id}


def rollback_dashboard(mb, before: dict[str, Any]) -> dict[str, Any]:
    try:
        response = _api_put(
            mb,
            f"/api/dashboard/{DASHBOARD_ID}",
            "raw",
            json=dashboard_write_payload(before),
            timeout=WRITE_TIMEOUT_SECONDS,
        )
        status = _response_status(response)
        if status is not None and status != 200:
            return {"status": "ROLLBACK_FAILED", "http_status": status}
        reread = _api_get(mb, f"/api/dashboard/{DASHBOARD_ID}")
        if dashboard_rewire_state(reread) != dashboard_rewire_state(before):
            return {
                "status": "ROLLBACK_DIVERGENT",
                "diff_paths": _diff_paths(
                    dashboard_rewire_state(before), dashboard_rewire_state(reread)
                ),
            }
    except Exception as exc:
        return {"status": "ROLLBACK_FAILED", "error": str(exc)}
    return {"status": "ROLLED_BACK_VERIFIED"}


def _put_dashboard(mb, prepared: dict[str, Any]) -> None:
    response = _api_put(
        mb,
        f"/api/dashboard/{DASHBOARD_ID}",
        "raw",
        json=dashboard_write_payload(prepared),
        timeout=WRITE_TIMEOUT_SECONDS,
    )
    status = _response_status(response)
    if status is not None and status != 200:
        raise RepairError(f"PUT dashboard HTTP {status}")


def _assert_source_unchanged(mb, preflight: dict[str, Any]) -> None:
    source = _read_card(mb, SOURCE_CARD_ID)
    if stable_hash(source_guard_state(source)) != preflight["source_guard_hash"]:
        raise RepairError(f"carte source #{SOURCE_CARD_ID} modifiée pendant l'opération")


def _assert_original_dashboard_unchanged(mb, preflight: dict[str, Any]) -> None:
    try:
        original = _api_get(mb, f"/api/dashboard/{ORIGINAL_DASHBOARD_ID}")
    except Exception as exc:
        raise RepairError(
            f"dashboard original #{ORIGINAL_DASHBOARD_ID} inaccessible"
        ) from exc
    if not _dict_with_id(original, ORIGINAL_DASHBOARD_ID):
        raise RepairError(f"dashboard original #{ORIGINAL_DASHBOARD_ID} inaccessible")
    if (
        stable_hash(dashboard_rewire_state(original))
        != preflight["original_dashboard_hash"]
    ):
        raise RepairError(
            f"dashboard original #{ORIGINAL_DASHBOARD_ID} modifié pendant l'opération"
        )


def _verify_post_dashboard(
    mb,
    before: dict[str, Any],
    prepared: dict[str, Any],
    clone_id: int,
    verifier: Callable[..., tuple[bool, str]],
) -> dict[str, Any]:
    reread = _api_get(mb, f"/api/dashboard/{DASHBOARD_ID}")
    if not _dict_with_id(reread, DASHBOARD_ID):
        raise RepairError("dashboard inaccessible après PUT")
    if dashboard_rewire_state(reread) != dashboard_rewire_state(prepared):
        paths = _diff_paths(
            dashboard_rewire_state(prepared), dashboard_rewire_state(reread)
        )
        raise RepairError(f"relecture dashboard divergente: {paths}")
    assert_exact_dashboard_diff(before, reread)
    usages = clone_dashboard_ids(mb, clone_id)
    if usages != [DASHBOARD_ID]:
        raise RepairError(
            f"clone #{clone_id}: usages attendus [{DASHBOARD_ID}], relus {usages}"
        )
    with redirect_stdout(io.StringIO()):
        ok, note = verifier(mb, DASHBOARD_ID, EXPECTED_CLIENT)
    if not ok:
        raise RepairError(f"verify_pipeline en échec: {note}")
    return {"verify_pipeline": note, "clone_dashboard_ids": usages}


def apply_repair(
    mb,
    preflight: dict[str, Any],
    *,
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    verifier: Callable[..., tuple[bool, str]] = verify_pipeline,
) -> dict[str, Any]:
    """Applique la transaction ciblée. Le snapshot précède toujours le premier POST."""
    snapshot_path, snapshot = write_snapshot(preflight, snapshot_dir)
    clone_id: int | None = None
    dashboard_put_attempted = False
    creation_note = None
    try:
        try:
            clone_id = _create_card(mb, preflight["clone_payload"])
        except Exception:
            clone_id, creation_note = discover_created_clone(mb, preflight)
            if clone_id is None:
                raise
        snapshot["clone_id"] = clone_id
        snapshot["status"] = "CLONE_CREATED"
        snapshot["creation_note"] = creation_note
        _replace_json(snapshot_path, snapshot)

        clone = _read_card(mb, clone_id)
        validate_clone(preflight["source_card"], clone, clone_id)
        collection_card_ids(
            mb,
            TARGET_COLLECTION_ID,
            forbidden_active_name=str(preflight["source_card"].get("name") or ""),
            allowed_active_name_id=clone_id,
        )
        _assert_source_unchanged(mb, preflight)
        _assert_original_dashboard_unchanged(mb, preflight)
        value_guard = verify_value_equivalence(
            mb,
            clone_id,
            preflight["dashboard"],
            preflight["source_card"],
        )
        snapshot["value_guard"] = value_guard
        snapshot["status"] = "VALUE_GUARD_PASSED"
        _replace_json(snapshot_path, snapshot)

        before = preflight["dashboard"]
        # Relecture juste avant mutation : le plan ne s'applique jamais sur un dashboard
        # changé depuis le préflight/snapshot.
        current = _api_get(mb, f"/api/dashboard/{DASHBOARD_ID}")
        if dashboard_rewire_state(current) != dashboard_rewire_state(before):
            raise RepairError("dashboard modifié depuis le préflight")
        prepared = prepare_dashboard(current, clone_id)
        dashboard_put_attempted = True
        _put_dashboard(mb, prepared)
        post = _verify_post_dashboard(mb, before, prepared, clone_id, verifier)
        _assert_source_unchanged(mb, preflight)
        _assert_original_dashboard_unchanged(mb, preflight)

        snapshot["status"] = "COMMITTED"
        snapshot["postconditions"] = post
        snapshot["committed_at"] = datetime.now(timezone.utc).isoformat()
        _replace_json(snapshot_path, snapshot)
        return {
            "status": "APPLIED",
            "clone_id": clone_id,
            "snapshot": str(snapshot_path),
            "value_guard": value_guard,
            **post,
        }
    except Exception as exc:
        if clone_id is None:
            clone_id, rediscovery = discover_created_clone(mb, preflight)
        else:
            rediscovery = None
        cleanup: dict[str, Any] = {"dashboard": {"status": "NOT_ATTEMPTED"}}
        if dashboard_put_attempted:
            cleanup["dashboard"] = rollback_dashboard(mb, preflight["dashboard"])
        rollback_verified = cleanup["dashboard"]["status"] in {
            "NOT_ATTEMPTED",
            "ROLLED_BACK_VERIFIED",
        }
        if clone_id is None:
            cleanup["clone"] = {
                "status": "CLONE_ID_UNKNOWN",
                "rediscovery": rediscovery,
            }
        elif not rollback_verified:
            # Même si /api/card/<id>/dashboards répondait vide, un rollback non vérifié
            # rendrait cette preuve insuffisante (latence d'index ou PUT ambigu). On laisse
            # alors le clone actif et on réclame une reprise humaine explicite.
            cleanup["clone"] = {
                "status": "ARCHIVE_SKIPPED_ROLLBACK_UNVERIFIED",
                "clone_id": clone_id,
            }
        else:
            cleanup["clone"] = archive_clone_if_orphan(mb, clone_id)
        snapshot["clone_id"] = clone_id
        snapshot["status"] = (
            "ROLLED_BACK"
            if rollback_verified
            and cleanup["clone"].get("status") == "ARCHIVED_ORPHAN"
            else "FAILED_CLEANUP_INCOMPLETE"
        )
        snapshot["failure"] = f"{type(exc).__name__}: {exc}"
        snapshot["cleanup"] = cleanup
        snapshot["failed_at"] = datetime.now(timezone.utc).isoformat()
        try:
            _replace_json(snapshot_path, snapshot)
        except Exception:
            pass
        raise RepairTransactionError(
            f"réparation interrompue: {exc}", snapshot_path, cleanup
        ) from exc


def execute(
    mb,
    *,
    yes: bool = False,
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    lock_directory: Path = DEFAULT_LOCK_DIR,
    verifier: Callable[..., tuple[bool, str]] = verify_pipeline,
) -> dict[str, Any]:
    if not yes:
        preflight = build_preflight(mb)
        return {"mode": "DRY_RUN", **preflight_summary(preflight)}
    # Le verrou est global au chantier, indépendamment d'un éventuel répertoire de
    # snapshot personnalisé : changer --snapshot-dir ne permet pas deux applies croisés.
    with operation_lock(lock_directory):
        # Le préflight est volontairement reconstruit sous verrou. Un dry-run effectué
        # plus tôt n'autorise jamais un apply sur un état devenu obsolète.
        preflight = build_preflight(mb)
        return apply_repair(
            mb, preflight, snapshot_dir=snapshot_dir, verifier=verifier
        )


def main(argv: list[str] | None = None, mb=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--yes",
        action="store_true",
        help="applique; sans ce drapeau le programme reste strictement en lecture seule",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=DEFAULT_SNAPSHOT_DIR,
        help="répertoire local des snapshots d'application",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="écrit aussi le rapport synthétique JSON à cet emplacement",
    )
    args = parser.parse_args(argv)
    client = mb or connect_redacted()
    try:
        report = execute(
            client,
            yes=args.yes,
            snapshot_dir=args.snapshot_dir,
        )
    except RepairTransactionError as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error": str(exc),
                    "snapshot": str(exc.snapshot_path),
                    "cleanup": exc.cleanup,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    except RepairError as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 1
    if args.output:
        _replace_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.yes:
        print("DRY-RUN — aucun POST/PUT métier exécuté.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
