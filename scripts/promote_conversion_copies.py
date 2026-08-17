#!/usr/bin/env python3
"""Promeut transactionnellement les copies conversions validées.

Le mode par défaut construit un plan déterministe en lecture seule. Une ligne n'est
``READY`` que si le manifeste canonique, l'accounting au grain copie et les décisions
canonical/superseded concordent, puis si l'état Metabase live satisfait de nouveau les
garde-fous de fin de pipeline.

``--yes`` ne modifie que le nom et la collection de la copie canonique. Les originaux,
les copies superseded, les cartes et le tracker ne sont jamais mutés. Par défaut, un
snapshot est écrit avant le premier PUT et le lot entier est restauré en ordre inverse
au premier échec. ``--continue-on-error`` isole chaque copie : seule la copie dont la
mutation a été tentée est restaurée, les succès précédents sont conservés et le lot
continue. ``--rollback SNAPSHOT`` prépare le rollback; ajouter ``--yes`` pour
l'appliquer.

Usage :
  python3 scripts/promote_conversion_copies.py
  python3 scripts/promote_conversion_copies.py \
    --target-collection-override ORIGINAL_ID:TARGET_COLLECTION_ID
  python3 scripts/promote_conversion_copies.py --yes
  python3 scripts/promote_conversion_copies.py --yes --continue-on-error
  python3 scripts/promote_conversion_copies.py --yes --continue-on-error \
    --exclude-original ORIGINAL_ID
  python3 scripts/promote_conversion_copies.py --yes --only-original ORIGINAL_ID
  python3 scripts/promote_conversion_copies.py --rollback migration/promotion-snapshot-....json
  python3 scripts/promote_conversion_copies.py --rollback migration/promotion-snapshot-....json --yes
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable


REPO = Path(__file__).resolve().parent.parent
MIGRATION = REPO / "migration"
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

from archive_collections import connect_resilient  # noqa: E402
from migrate_client import verify_pipeline  # noqa: E402


SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 1
CARD_FINGERPRINT_VERSION = 2
STAGING_ROOT_ID = 14016
SHARED_GENERATED_CARDS_COLLECTION_ID = 14115
TARGET_TAG = "[conv-2026-06]"
READ_TIMEOUT_SECONDS = 60
WRITE_TIMEOUT_SECONDS = 60
DEFAULT_MANIFEST = MIGRATION / "conversion-manifest.json"
DEFAULT_ACCOUNTING = MIGRATION / "accounting-copies.json"
DEFAULT_DECISIONS = MIGRATION / "canonical-copy-decisions.json"
DEFAULT_PLAN = MIGRATION / "promotion-plan.json"

_CARD_SOURCE_RE = re.compile(r"card__(\d+)")
_SENSITIVE_OUTPUT_RE = re.compile(
    r"(?im)^.*(?:authenticated successfully.*session id|session id\s*(?:is)?\s*:).*$"
)


class PromotionError(RuntimeError):
    """Erreur de validation ou d'application fail-closed."""


class PromotionTransactionError(PromotionError):
    """Échec d'un lot; ``snapshot_path`` permet le diagnostic/rollback."""

    def __init__(self, message: str, snapshot_path: Path, rollback_ok: bool):
        super().__init__(message)
        self.snapshot_path = snapshot_path
        self.rollback_ok = rollback_ok


ProgressCallback = Callable[[dict[str, Any]], None]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise PromotionError(f"fichier introuvable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PromotionError(f"JSON invalide dans {path}: {exc}") from exc


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path.resolve())


def _atomic_write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    os.replace(temporary, path)
    return path


def redact_sensitive_output(value: str) -> str:
    return _SENSITIVE_OUTPUT_RE.sub(
        "[authentification Metabase réussie — session masquée]", value
    )


def connect_redacted():
    """Capture la sortie du client historique, qui affichait l'id de session."""
    try:
        with redirect_stdout(io.StringIO()):
            return connect_resilient()
    except (Exception, SystemExit) as exc:
        raise PromotionError("authentification Metabase impossible") from exc


def _direct_get(mb, endpoint: str, *, timeout: int = READ_TIMEOUT_SECONDS) -> Any:
    """GET borné sans le ``/api/user/current`` ajouté par le wrapper historique.

    Une réponse 401/403 repasse une seule fois par le client public afin qu'il puisse
    renouveler sa session. Sa sortie reste capturée car cette réauthentification peut
    afficher l'identifiant de session.
    """
    if all(hasattr(mb, attribute) for attribute in ("_http", "domain", "header")):
        response = mb._http.get(
            mb.domain + endpoint,
            headers=mb.header,
            timeout=timeout,
        )
        if response.status_code not in (401, 403):
            response.raise_for_status()
            return response.json()
    try:
        with redirect_stdout(io.StringIO()):
            return mb.get(endpoint, timeout=timeout)
    except TypeError:
        # Doubles de test ou anciens clients sans argument timeout. La production passe
        # toujours par la branche précédente ou par le wrapper avec timeout.
        with redirect_stdout(io.StringIO()):
            return mb.get(endpoint)


class CachedReadMetabase:
    """Façade GET-only avec cache de phase et timeout explicite.

    Une instance ne doit jamais traverser une mutation. ``apply_plan`` en recrée une
    avant chaque précondition et après chaque PUT.
    """

    def __init__(self, mb, *, timeout: int = READ_TIMEOUT_SECONDS):
        self._mb = mb
        self.timeout = timeout
        self._cache: dict[str, Any] = {}

    def get(self, endpoint: str, *args, **kwargs) -> Any:
        if args:
            raise PromotionError(f"GET cache: arguments positionnels non supportés pour {endpoint}")
        if endpoint not in self._cache:
            timeout = int(kwargs.pop("timeout", self.timeout))
            if kwargs:
                raise PromotionError(
                    f"GET cache: options non supportées pour {endpoint}: {sorted(kwargs)}"
                )
            self._cache[endpoint] = _clone(
                _direct_get(self._mb, endpoint, timeout=timeout)
            )
        return _clone(self._cache[endpoint])


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    phase: str,
    status: str,
    current: int,
    total: int,
    original_id: int | None = None,
    copy_id: int | None = None,
) -> None:
    if callback is None:
        return
    try:
        callback({
            "phase": phase,
            "status": status,
            "current": current,
            "total": total,
            "original_id": original_id,
            "copy_id": copy_id,
        })
    except Exception:
        # Le reporting ne participe jamais à la transaction métier.
        return


def _positive_id(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise PromotionError(f"{field} invalide: {value!r}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PromotionError(f"{field} invalide: {value!r}") from exc
    if result <= 0:
        raise PromotionError(f"{field} doit être un entier positif")
    return result


def _parse_target_collection_override(value: str) -> tuple[int, int]:
    """Parse un override CLI strict ``ORIGINAL_ID:TARGET_COLLECTION_ID``."""
    parts = value.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            "format attendu: ORIGINAL_ID:TARGET_COLLECTION_ID"
        )
    try:
        original_id = _positive_id(parts[0], "ORIGINAL_ID")
        target_collection_id = _positive_id(
            parts[1], "TARGET_COLLECTION_ID"
        )
    except PromotionError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return original_id, target_collection_id


def _parse_original_id(value: str) -> int:
    try:
        return _positive_id(value, "ORIGINAL_ID")
    except PromotionError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _target_collection_override_map(
    values: Iterable[tuple[int, int]],
) -> dict[int, int]:
    """Construit la table d'overrides et refuse toute ambiguïté par original."""
    result: dict[int, int] = {}
    for original_id, target_collection_id in values:
        original_id = _positive_id(original_id, "override.original_id")
        target_collection_id = _positive_id(
            target_collection_id, "override.target_collection_id"
        )
        if original_id in result:
            raise PromotionError(
                f"override collection cible dupliqué pour l'original #{original_id}"
            )
        result[original_id] = target_collection_id
    return result


def _reason(code: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code}
    if details:
        result["details"] = details
    return result


def _sorted_reasons(reasons: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {
        json.dumps(reason, ensure_ascii=False, sort_keys=True): reason
        for reason in reasons
    }
    return [unique[key] for key in sorted(unique)]


def _dashboard_cards(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    return list(dashboard.get("dashcards") or dashboard.get("ordered_cards") or [])


def _compact_series(series: Any) -> list[dict[str, Any]]:
    output = []
    for item in series or []:
        if not isinstance(item, dict):
            continue
        output.append({
            "id": item.get("id") or item.get("card_id"),
            "card_id": item.get("card_id") or item.get("id"),
        })
    return output


def dashboard_semantic_state(dashboard: dict[str, Any]) -> dict[str, Any]:
    """État stable couvrant les propriétés que la promotion doit préserver."""
    dashcards = []
    for dashcard in _dashboard_cards(dashboard):
        dashcards.append({
            "id": dashcard.get("id"),
            "card_id": dashcard.get("card_id")
            or (dashcard.get("card") or {}).get("id"),
            "dashboard_tab_id": dashcard.get("dashboard_tab_id"),
            "row": dashcard.get("row"),
            "col": dashcard.get("col"),
            "size_x": dashcard.get("size_x"),
            "size_y": dashcard.get("size_y"),
            "action_id": dashcard.get("action_id"),
            "inline_parameters": _clone(dashcard.get("inline_parameters")),
            "parameter_mappings": _clone(dashcard.get("parameter_mappings") or []),
            "series": _compact_series(dashcard.get("series")),
            "visualization_settings": _clone(
                dashcard.get("visualization_settings") or {}
            ),
        })
    return {
        "id": dashboard.get("id"),
        "name": dashboard.get("name"),
        "description": dashboard.get("description"),
        "collection_id": dashboard.get("collection_id"),
        "archived": bool(dashboard.get("archived")),
        "archived_directly": bool(dashboard.get("archived_directly")),
        "parameters": _clone(dashboard.get("parameters") or []),
        "tabs": _clone(dashboard.get("tabs") or []),
        "dashcards": dashcards,
        "width": dashboard.get("width"),
        "auto_apply_filters": dashboard.get("auto_apply_filters"),
    }


def dashboard_fingerprint(dashboard: dict[str, Any]) -> str:
    return stable_hash(dashboard_semantic_state(dashboard))


def _dataset_query_for_card_fingerprint(card: dict[str, Any]) -> Any:
    """Copie la requête et neutralise les UUIDs réhydratés par Metabase.

    Metabase peut réécrire les ``lib/uuid`` des requêtes converties encore doublées
    d'un ``legacy_query`` sans changer leur sémantique. Cette exception est donc
    volontairement limitée à cette forme historique; toutes les autres cartes restent
    comparées octet pour octet au niveau JSON canonique.
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


def card_semantic_state(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "collection_id": card.get("collection_id"),
        "archived": bool(card.get("archived")),
        "source_card_id": card.get("source_card_id"),
        "dataset_query": _dataset_query_for_card_fingerprint(card),
        "legacy_query": _clone(card.get("legacy_query")),
        "display": card.get("display"),
        "visualization_settings": _clone(card.get("visualization_settings") or {}),
    }


def card_fingerprint(card: dict[str, Any]) -> str:
    return stable_hash(card_semantic_state(card))


def card_fingerprint_parts(card: dict[str, Any]) -> dict[str, str]:
    """Empreintes par composant, sans donnée métier brute dans le plan."""
    state = card_semantic_state(card)
    return {key: stable_hash(state[key]) for key in sorted(state)}


def _dashboard_card_ids(dashboard: dict[str, Any]) -> list[int]:
    ids = set()
    for dashcard in _dashboard_cards(dashboard):
        card_id = dashcard.get("card_id") or (dashcard.get("card") or {}).get("id")
        if card_id:
            ids.add(_positive_id(card_id, "dashboard.card_id"))
        for series in dashcard.get("series") or []:
            series_id = series.get("id") or series.get("card_id")
            if series_id:
                ids.add(_positive_id(series_id, "dashboard.series.card_id"))
    return sorted(ids)


def _card_source_ids(card: dict[str, Any]) -> list[int]:
    ids = set()
    source_card_id = card.get("source_card_id")
    if source_card_id:
        ids.add(_positive_id(source_card_id, "card.source_card_id"))
    blobs = [card.get("dataset_query") or {}, card.get("legacy_query") or {}]
    for blob in blobs:
        text = blob if isinstance(blob, str) else json.dumps(blob, ensure_ascii=False)
        ids.update(int(value) for value in _CARD_SOURCE_RE.findall(text))
    ids.discard(int(card.get("id") or 0))
    return sorted(ids)


def _is_dict_with_id(value: Any, expected_id: int | None = None) -> bool:
    if not isinstance(value, dict) or value.get("id") is None:
        return False
    if expected_id is None:
        return True
    try:
        return int(value["id"]) == expected_id
    except (TypeError, ValueError):
        return False


class LiveCatalog:
    """Lectures fail-closed et caches limités à la construction d'un plan."""

    def __init__(self, mb):
        self.mb = mb
        self._collections: dict[int, dict[str, Any]] = {}
        self._cards: dict[int, dict[str, Any]] = {}

    def dashboard(self, dashboard_id: int) -> dict[str, Any]:
        try:
            value = self.mb.get(f"/api/dashboard/{dashboard_id}")
        except Exception as exc:
            raise PromotionError(f"dashboard #{dashboard_id} inaccessible") from exc
        if not _is_dict_with_id(value, dashboard_id):
            raise PromotionError(f"dashboard #{dashboard_id} inaccessible")
        return value

    def card(self, card_id: int) -> dict[str, Any]:
        if card_id not in self._cards:
            try:
                value = self.mb.get(f"/api/card/{card_id}")
            except Exception as exc:
                raise PromotionError(f"carte #{card_id} inaccessible") from exc
            if not _is_dict_with_id(value, card_id):
                raise PromotionError(f"carte #{card_id} inaccessible")
            self._cards[card_id] = value
        return self._cards[card_id]

    def collection(self, collection_id: int) -> dict[str, Any]:
        if collection_id not in self._collections:
            try:
                value = self.mb.get(f"/api/collection/{collection_id}")
            except Exception as exc:
                raise PromotionError(f"collection #{collection_id} inaccessible") from exc
            if not _is_dict_with_id(value, collection_id):
                raise PromotionError(f"collection #{collection_id} inaccessible")
            self._collections[collection_id] = value
        return self._collections[collection_id]

    def collection_items(self, collection_id: int | None) -> list[dict[str, Any]]:
        token = "root" if collection_id is None else str(collection_id)
        limit, offset, output = 2000, 0, []
        while True:
            endpoint = (
                f"/api/collection/{token}/items?models=dashboard"
                f"&limit={limit}&offset={offset}"
            )
            try:
                payload = self.mb.get(endpoint)
            except Exception as exc:
                raise PromotionError(
                    f"inventaire dashboards collection {token} inaccessible"
                ) from exc
            if isinstance(payload, dict):
                chunk = payload.get("data")
                total = payload.get("total")
            elif isinstance(payload, list):
                chunk, total = payload, len(payload)
            else:
                raise PromotionError(
                    f"inventaire dashboards collection {token} inaccessible"
                )
            if not isinstance(chunk, list):
                raise PromotionError(
                    f"inventaire dashboards collection {token} incomplet"
                )
            output.extend(item for item in chunk if isinstance(item, dict))
            offset += len(chunk)
            if not chunk or len(chunk) < limit:
                break
            if isinstance(total, int) and offset >= total:
                break
            if offset > 100_000:
                raise PromotionError(
                    f"inventaire dashboards collection {token} anormalement volumineux"
                )
        return output


def _collection_location_ids(collection: dict[str, Any]) -> set[int]:
    result = set()
    for value in str(collection.get("location") or "").strip("/").split("/"):
        if value.isdigit():
            result.add(int(value))
    if collection.get("id") is not None:
        result.add(int(collection["id"]))
    return result


def collection_is_in_tree(collection: dict[str, Any], root_id: int) -> bool:
    """Metabase expose les ancêtres dans ``location``; le nœud racine est inclus ici."""
    return root_id in _collection_location_ids(collection)


def collection_is_personal(collection: dict[str, Any]) -> bool:
    return bool(
        collection.get("is_personal")
        or collection.get("personal_owner_id") is not None
    )


def collection_is_archived(collection: dict[str, Any]) -> bool:
    return bool(collection.get("archived") or collection.get("archived_directly"))


def dashboard_is_archived_or_trash(
    dashboard: dict[str, Any], collection: dict[str, Any] | None
) -> bool:
    return bool(
        dashboard.get("archived")
        or dashboard.get("archived_directly")
        or (collection is not None and collection_is_archived(collection))
    )


def _accounting_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("copies"), list):
        rows = payload["copies"]
    else:
        raise PromotionError("accounting: liste ou objet avec 'copies' attendu")
    if any(not isinstance(row, dict) for row in rows):
        raise PromotionError("accounting: chaque copie doit être un objet")
    return rows


def _decision_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("decisions"), list):
        rows = payload["decisions"]
    else:
        raise PromotionError("décisions: liste ou objet avec 'decisions' attendu")
    if any(not isinstance(row, dict) for row in rows):
        raise PromotionError("décisions: chaque décision doit être un objet")
    return rows


def _index_unique(
    rows: Iterable[dict[str, Any]], field: str, source: str
) -> dict[int, dict[str, Any]]:
    output = {}
    for position, row in enumerate(rows):
        item_id = _positive_id(row.get(field), f"{source}[{position}].{field}")
        if item_id in output:
            raise PromotionError(f"{source}: {field} {item_id} dupliqué")
        output[item_id] = row
    return output


def _accounting_is_strictly_clean(row: dict[str, Any]) -> bool:
    status = str(row.get("iron_law_status", row.get("iron_law", ""))).casefold()
    if status not in {"clean", "complete"}:
        return False
    for field in (
        "causes",
        "consultant_slots",
        "coverage",
        "residual_cards",
        "unknown_cards",
    ):
        if row.get(field):
            return False
    return True


def select_local_entries(
    manifest: Any, accounting: Any, decisions: Any
) -> list[dict[str, Any]]:
    """Sélection pure et exhaustive; aucune ligne ambiguë ne devient candidate live."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("dashboards"), list):
        raise PromotionError("manifest: objet avec 'dashboards' attendu")
    accounting_by_copy = _index_unique(
        _accounting_rows(accounting), "copy_id", "accounting"
    )
    decisions_by_original = _index_unique(
        _decision_rows(decisions), "original_id", "decisions"
    )

    output = []
    seen_originals = set()
    for position, row in enumerate(manifest["dashboards"]):
        if not isinstance(row, dict):
            raise PromotionError(f"manifest.dashboards[{position}] doit être un objet")
        original_id = _positive_id(
            row.get("original_id"), f"manifest.dashboards[{position}].original_id"
        )
        if original_id in seen_originals:
            raise PromotionError(f"manifest: original {original_id} dupliqué")
        seen_originals.add(original_id)
        reasons = []
        scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
        if scope.get("in_worklist") is not True:
            reasons.append(_reason("OUT_OF_SCOPE"))
        if row.get("roadmap_status") != "complete":
            reasons.append(_reason("ROADMAP_NOT_COMPLETE", value=row.get("roadmap_status")))
        if row.get("iron_law_status") != "complete":
            reasons.append(_reason("MANIFEST_IRON_LAW_NOT_COMPLETE"))
        if row.get("copy_reconciliation_status") == "unresolved":
            reasons.append(_reason("COPY_RECONCILIATION_UNRESOLVED"))

        owner = row.get("owner_client") or row.get("client")
        if not isinstance(owner, str) or not owner.strip():
            reasons.append(_reason("OWNER_CLIENT_MISSING"))
            owner = None
        else:
            owner = owner.strip()

        canonical_copy_id = row.get("canonical_copy_id")
        if canonical_copy_id is None:
            reasons.append(_reason("CANONICAL_COPY_MISSING"))
            canonical_copy_id_int = None
        else:
            canonical_copy_id_int = _positive_id(
                canonical_copy_id, f"manifest original {original_id}.canonical_copy_id"
            )

        copies = row.get("copies") if isinstance(row.get("copies"), list) else []
        canonical_copies = [
            copy
            for copy in copies
            if isinstance(copy, dict) and copy.get("selection") == "canonical"
        ]
        if len(canonical_copies) != 1:
            reasons.append(
                _reason("CANONICAL_SELECTION_NOT_UNIQUE", count=len(canonical_copies))
            )
            canonical_copy = None
        else:
            canonical_copy = canonical_copies[0]
            if canonical_copy_id_int is not None and int(
                canonical_copy.get("copy_id") or 0
            ) != canonical_copy_id_int:
                reasons.append(_reason("CANONICAL_SELECTION_MISMATCH"))
            if canonical_copy.get("tagged") is not True:
                reasons.append(_reason("CANONICAL_COPY_NOT_TAGGED"))
            iron = canonical_copy.get("iron_law") or {}
            if iron.get("status") != "complete":
                reasons.append(_reason("CANONICAL_COPY_IRON_LAW_NOT_COMPLETE"))

        accounting_row = (
            accounting_by_copy.get(canonical_copy_id_int)
            if canonical_copy_id_int is not None
            else None
        )
        if accounting_row is None:
            reasons.append(_reason("ACCOUNTING_COPY_MISSING"))
        elif not _accounting_is_strictly_clean(accounting_row):
            reasons.append(_reason("ACCOUNTING_COPY_NOT_STRICTLY_CLEAN"))
        else:
            accounting_original = accounting_row.get("original_id")
            if accounting_original is not None and int(accounting_original) != original_id:
                reasons.append(_reason("ACCOUNTING_ORIGINAL_MISMATCH"))
            accounting_client = accounting_row.get("client")
            if owner and accounting_client and accounting_client != owner:
                reasons.append(_reason("ACCOUNTING_CLIENT_MISMATCH"))

        copy_status = row.get("copy_status")
        decision = decisions_by_original.get(original_id)
        if copy_status == "multiple_copies":
            if row.get("copy_reconciliation_status") != "resolved":
                reasons.append(_reason("MULTIPLE_COPIES_NOT_RESOLVED"))
            if decision is None:
                reasons.append(_reason("CANONICAL_DECISION_MISSING"))
            else:
                if int(decision.get("canonical_copy_id") or 0) != (
                    canonical_copy_id_int or 0
                ):
                    reasons.append(_reason("CANONICAL_DECISION_MISMATCH"))
                declared = sorted(int(value) for value in decision.get("superseded_copy_ids") or [])
                manifest_superseded = sorted(
                    int(value) for value in row.get("superseded_copy_ids") or []
                )
                if declared != manifest_superseded:
                    reasons.append(_reason("SUPERSEDED_DECISION_MISMATCH"))
                actual_copy_ids = sorted(
                    int(copy.get("copy_id"))
                    for copy in copies
                    if isinstance(copy, dict) and copy.get("copy_id")
                )
                manifest_decided_ids = (
                    sorted([canonical_copy_id_int, *manifest_superseded])
                    if canonical_copy_id_int is not None
                    else manifest_superseded
                )
                if manifest_decided_ids != actual_copy_ids:
                    reasons.append(_reason("CANONICAL_DECISION_NOT_EXHAUSTIVE"))
                wrongly_selected = sorted(
                    int(copy["copy_id"])
                    for copy in copies
                    if isinstance(copy, dict)
                    and int(copy.get("copy_id") or 0) in manifest_superseded
                    and copy.get("selection") != "superseded"
                )
                if wrongly_selected:
                    reasons.append(
                        _reason(
                            "SUPERSEDED_SELECTION_MISMATCH",
                            copy_ids=wrongly_selected,
                        )
                    )
        elif copy_status != "single_copy":
            reasons.append(_reason("COPY_TOPOLOGY_NOT_PROMOTABLE", value=copy_status))

        output.append({
            "original_id": original_id,
            "copy_id": canonical_copy_id_int,
            "client": owner,
            "dashboard": row.get("dashboard"),
            "superseded_copy_ids": sorted(
                int(value) for value in row.get("superseded_copy_ids") or []
            ),
            "local_status": "SELECTED" if not reasons else "EXCLUDED",
            "reasons": _sorted_reasons(reasons),
        })
    output.sort(key=lambda item: item["original_id"])
    return output


def _audit_dependencies(
    catalog: LiveCatalog, dashboard: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reasons = []
    direct_ids = set(_dashboard_card_ids(dashboard))
    pending = list(sorted(direct_ids))
    seen = set()
    dependencies = []
    while pending:
        card_id = pending.pop(0)
        if card_id in seen:
            continue
        seen.add(card_id)
        try:
            card = catalog.card(card_id)
        except PromotionError:
            reasons.append(_reason("DEPENDENCY_CARD_INACCESSIBLE", card_id=card_id))
            continue
        collection_id = card.get("collection_id")
        collection = None
        if collection_id is not None:
            try:
                collection = catalog.collection(int(collection_id))
            except PromotionError:
                reasons.append(
                    _reason(
                        "DEPENDENCY_COLLECTION_INACCESSIBLE",
                        card_id=card_id,
                        collection_id=collection_id,
                    )
                )
            else:
                if collection_is_personal(collection):
                    reasons.append(
                        _reason(
                            "DEPENDENCY_IN_PERSONAL_COLLECTION",
                            card_id=card_id,
                            collection_id=collection_id,
                        )
                    )
        if card.get("archived"):
            reasons.append(_reason("DEPENDENCY_CARD_ARCHIVED", card_id=card_id))
        source_ids = _card_source_ids(card)
        pending.extend(source_id for source_id in source_ids if source_id not in seen)
        pending.sort()
        dependencies.append({
            "card_id": card_id,
            "name": card.get("name"),
            "collection_id": collection_id,
            "direct_dashboard_reference": card_id in direct_ids,
            "source_card_ids": source_ids,
            "shared_generated_card": (
                collection_id == SHARED_GENERATED_CARDS_COLLECTION_ID
            ),
            "fingerprint": card_fingerprint(card),
            "fingerprint_parts": card_fingerprint_parts(card),
        })
    dependencies.sort(key=lambda item: item["card_id"])
    return dependencies, _sorted_reasons(reasons)


def _collision_reasons(
    catalog: LiveCatalog,
    collection_id: int | None,
    target_name: str,
    copy_id: int,
) -> list[dict[str, Any]]:
    try:
        items = catalog.collection_items(collection_id)
    except PromotionError:
        return [_reason("TARGET_COLLISION_AUDIT_INACCESSIBLE")]
    normalized = target_name.strip().casefold()
    collisions = []
    for item in items:
        if item.get("archived"):
            continue
        if str(item.get("name") or "").strip().casefold() != normalized:
            continue
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            item_id = None
        if item_id != copy_id:
            collisions.append(item_id)
    if collisions:
        return [_reason("TARGET_NAME_COLLISION", dashboard_ids=sorted(collisions, key=str))]
    return []


def _live_entry(
    catalog: LiveCatalog,
    local: dict[str, Any],
    *,
    verifier: Callable[..., tuple[bool, str]],
    target_collection_overrides: dict[int, int],
) -> dict[str, Any]:
    entry = deepcopy(local)
    reasons = list(entry.pop("reasons", []))
    original_id, copy_id = entry["original_id"], entry["copy_id"]
    if entry["local_status"] != "SELECTED" or copy_id is None:
        entry.update({"status": "BLOCKED", "reasons": _sorted_reasons(reasons)})
        return entry

    try:
        original = catalog.dashboard(original_id)
    except PromotionError:
        reasons.append(_reason("ORIGINAL_INACCESSIBLE"))
        original = None
    try:
        copy_dashboard = catalog.dashboard(copy_id)
    except PromotionError:
        reasons.append(_reason("COPY_INACCESSIBLE"))
        copy_dashboard = None
    if original is None or copy_dashboard is None:
        entry.update({"status": "BLOCKED", "reasons": _sorted_reasons(reasons)})
        return entry

    original_collection_id = original.get("collection_id")
    original_collection = None
    if original_collection_id is not None:
        try:
            original_collection = catalog.collection(int(original_collection_id))
        except PromotionError:
            reasons.append(_reason("ORIGINAL_COLLECTION_INACCESSIBLE"))

    archived_or_trash = dashboard_is_archived_or_trash(original, original_collection)
    target_collection_override = target_collection_overrides.get(original_id)
    target_collection_id = (
        target_collection_override
        if target_collection_override is not None
        else original_collection_id
    )
    overrides = []
    if archived_or_trash:
        if target_collection_override is None:
            reasons.append(_reason("ORIGINAL_ARCHIVED_OR_TRASH_REQUIRES_OVERRIDE"))
        else:
            overrides.append(f"target_collection:{target_collection_override}")
    elif target_collection_override is not None:
        reasons.append(_reason("TARGET_OVERRIDE_FOR_ACTIVE_ORIGINAL_FORBIDDEN"))

    target_collection = None
    if target_collection_id is not None:
        try:
            target_collection = catalog.collection(int(target_collection_id))
        except PromotionError:
            reasons.append(_reason("DESTINATION_COLLECTION_INACCESSIBLE"))
        else:
            if collection_is_personal(target_collection):
                reasons.append(_reason("DESTINATION_PERSONAL_COLLECTION"))
            if collection_is_archived(target_collection):
                reasons.append(_reason("DESTINATION_COLLECTION_ARCHIVED"))
            if collection_is_in_tree(target_collection, STAGING_ROOT_ID):
                reasons.append(_reason("DESTINATION_IS_STAGING"))

    copy_collection_id = copy_dashboard.get("collection_id")
    if copy_dashboard.get("archived") or copy_dashboard.get("archived_directly"):
        reasons.append(_reason("COPY_ARCHIVED_OR_TRASH"))
    if TARGET_TAG not in str(copy_dashboard.get("name") or ""):
        reasons.append(_reason("COPY_LIVE_TAG_MISSING"))
    if copy_dashboard.get("can_write") is False:
        reasons.append(_reason("COPY_NOT_WRITABLE"))
    if copy_collection_id is None:
        reasons.append(_reason("COPY_NOT_UNDER_STAGING"))
    else:
        try:
            copy_collection = catalog.collection(int(copy_collection_id))
        except PromotionError:
            reasons.append(_reason("COPY_COLLECTION_INACCESSIBLE"))
        else:
            if collection_is_personal(copy_collection):
                reasons.append(_reason("COPY_IN_PERSONAL_COLLECTION"))
            if collection_is_archived(copy_collection):
                reasons.append(_reason("COPY_COLLECTION_ARCHIVED"))
            if not collection_is_in_tree(copy_collection, STAGING_ROOT_ID):
                reasons.append(_reason("COPY_NOT_UNDER_STAGING"))

    name = str(original.get("name") or "").strip()
    if not name:
        reasons.append(_reason("ORIGINAL_NAME_MISSING"))
    target_name = f"{name} {TARGET_TAG}" if name else None
    if target_name:
        reasons.extend(
            _collision_reasons(
                catalog, target_collection_id, target_name, copy_id
            )
        )

    dependencies, dependency_reasons = _audit_dependencies(catalog, copy_dashboard)
    reasons.extend(dependency_reasons)
    try:
        verified, verify_note = verifier(
            catalog.mb, copy_id, entry["client"]
        )
    except Exception:
        verified, verify_note = False, "exception de revalidation live"
    if not verified:
        reasons.append(_reason("LIVE_PIPELINE_REVALIDATION_FAILED"))

    original_state = dashboard_semantic_state(original)
    copy_state = dashboard_semantic_state(copy_dashboard)
    expected_copy_state = deepcopy(copy_state)
    expected_copy_state["name"] = target_name
    expected_copy_state["collection_id"] = target_collection_id
    entry.update({
        "status": "READY" if not reasons else "BLOCKED",
        "reasons": _sorted_reasons(reasons),
        "overrides": sorted(overrides),
        "target_collection_override": target_collection_override,
        "target": {
            "name": target_name,
            "collection_id": target_collection_id,
        },
        "live_validation": {
            "verify_pipeline": "PASS" if verified else "FAIL",
            "note": verify_note,
        },
        "preconditions": {
            "original_state": original_state,
            "original_fingerprint": stable_hash(original_state),
            "copy_state": copy_state,
            "copy_fingerprint": stable_hash(copy_state),
            "expected_copy_fingerprint": stable_hash(expected_copy_state),
            "dependency_cards": dependencies,
            "copy_under_staging_root": STAGING_ROOT_ID,
        },
        "no_actions": {
            "original": "UNCHANGED",
            "superseded_copy_ids": entry["superseded_copy_ids"],
            "cards": "UNCHANGED",
            "shared_generated_collection_id": SHARED_GENERATED_CARDS_COLLECTION_ID,
        },
    })
    return entry


def build_promotion_plan(
    manifest: Any,
    accounting: Any,
    decisions: Any,
    mb,
    *,
    verifier: Callable[..., tuple[bool, str]] = verify_pipeline,
    target_collection_overrides: dict[int, int] | None = None,
    source_labels: dict[str, str] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Construit le plan déterministe sans aucune mutation distante."""
    target_collection_overrides = _target_collection_override_map(
        (target_collection_overrides or {}).items()
    )
    local_entries = select_local_entries(manifest, accounting, decisions)
    # Le build est une seule phase immuable : audit structurel et verify_pipeline
    # partagent donc le même cache. Une carte commune à plusieurs dashboards n'est lue
    # qu'une fois, sans perdre de fraîcheur puisqu'aucun PUT n'est possible ici.
    read_mb = CachedReadMetabase(mb)
    catalog = LiveCatalog(read_mb)
    selected_total = sum(
        local["local_status"] == "SELECTED" for local in local_entries
    )
    selected_current = 0
    entries = []
    for local in local_entries:
        selected = local["local_status"] == "SELECTED"
        if selected:
            selected_current += 1
            _emit_progress(
                progress,
                phase="plan",
                status="START",
                current=selected_current,
                total=selected_total,
                original_id=local["original_id"],
                copy_id=local["copy_id"],
            )
        entry = _live_entry(
            catalog,
            local,
            verifier=verifier,
            target_collection_overrides=target_collection_overrides,
        )
        entries.append(entry)
        if selected:
            _emit_progress(
                progress,
                phase="plan",
                status=entry["status"],
                current=selected_current,
                total=selected_total,
                original_id=entry["original_id"],
                copy_id=entry["copy_id"],
            )
    entries.sort(key=lambda item: item["original_id"])
    targets: dict[tuple[int | None, str], list[dict[str, Any]]] = {}
    for entry in entries:
        if entry.get("status") != "READY":
            continue
        target = entry.get("target") or {}
        key = (
            target.get("collection_id"),
            str(target.get("name") or "").strip().casefold(),
        )
        targets.setdefault(key, []).append(entry)
    for duplicates in targets.values():
        if len(duplicates) < 2:
            continue
        ids = sorted(entry["original_id"] for entry in duplicates)
        for entry in duplicates:
            entry["status"] = "BLOCKED"
            entry["reasons"] = _sorted_reasons([
                *entry.get("reasons", []),
                _reason("TARGET_NAME_COLLISION_IN_PLAN", original_ids=ids),
            ])
    summary = {
        "total": len(entries),
        "ready": sum(item["status"] == "READY" for item in entries),
        "blocked": sum(item["status"] == "BLOCKED" for item in entries),
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "operation": "promote_conversion_copies",
        "constants": {
            "card_fingerprint_version": CARD_FINGERPRINT_VERSION,
            "staging_root_id": STAGING_ROOT_ID,
            "shared_generated_cards_collection_id": SHARED_GENERATED_CARDS_COLLECTION_ID,
            "target_tag": TARGET_TAG,
        },
        "sources": {
            "manifest": {
                "label": (source_labels or {}).get("manifest", "provided"),
                "hash": stable_hash(manifest),
            },
            "accounting": {
                "label": (source_labels or {}).get("accounting", "provided"),
                "hash": stable_hash(accounting),
            },
            "canonical_decisions": {
                "label": (source_labels or {}).get("canonical_decisions", "provided"),
                "hash": stable_hash(decisions),
            },
        },
        "summary": summary,
        "entries": entries,
    }
    return {**body, "plan_hash": stable_hash(body)}


def validate_plan_hash(plan: dict[str, Any]) -> None:
    expected = plan.get("plan_hash")
    body = {key: value for key, value in plan.items() if key != "plan_hash"}
    actual = stable_hash(body)
    if expected != actual:
        raise PromotionError(
            f"hash du plan invalide: attendu {expected!r}, recalculé {actual!r}"
        )


def _response_ok(response: Any) -> bool:
    if isinstance(response, bool):
        return response
    if isinstance(response, int):
        return 200 <= response < 300
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return 200 <= status < 300
    return bool(getattr(response, "ok", False))


def _put_dashboard_identity(
    mb, dashboard_id: int, *, name: str, collection_id: int | None
) -> None:
    try:
        with redirect_stdout(io.StringIO()):
            response = mb.put(
                f"/api/dashboard/{dashboard_id}",
                "raw",
                json={"name": name, "collection_id": collection_id},
                timeout=WRITE_TIMEOUT_SECONDS,
            )
    except Exception as exc:
        raise PromotionError(f"PUT copie #{dashboard_id} a échoué") from exc
    if not _response_ok(response):
        raise PromotionError(f"PUT copie #{dashboard_id} a échoué")


def _fresh_card_fingerprint(mb, card_id: int) -> str:
    return card_fingerprint(LiveCatalog(mb).card(card_id))


def _assert_dependency_audit_unchanged(
    mb,
    entry: dict[str, Any],
    dashboard: dict[str, Any],
) -> None:
    dependencies, reasons = _audit_dependencies(LiveCatalog(mb), dashboard)
    if reasons:
        codes = ", ".join(reason["code"] for reason in reasons)
        raise PromotionError(f"audit dépendances divergent: {codes}")
    expected = entry["preconditions"].get("dependency_cards") or []
    if dependencies != expected:
        def by_card_id(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
            return {
                int(row["card_id"]): row
                for row in rows
                if isinstance(row, dict) and row.get("card_id") is not None
            }

        expected_by_id = by_card_id(expected)
        actual_by_id = by_card_id(dependencies)
        missing = sorted(set(expected_by_id) - set(actual_by_id))
        added = sorted(set(actual_by_id) - set(expected_by_id))
        changed = []
        for card_id in sorted(set(expected_by_id) & set(actual_by_id)):
            before, after = expected_by_id[card_id], actual_by_id[card_id]
            fields = []
            for key in sorted(set(before) | set(after)):
                if before.get(key) == after.get(key):
                    continue
                if key == "fingerprint_parts":
                    before_parts = before.get(key) or {}
                    after_parts = after.get(key) or {}
                    if isinstance(before_parts, dict) and isinstance(after_parts, dict):
                        fields.extend(
                            f"fingerprint_parts.{part}"
                            for part in sorted(set(before_parts) | set(after_parts))
                            if before_parts.get(part) != after_parts.get(part)
                        )
                        continue
                fields.append(key)
            if fields:
                changed.append(f"{card_id}[{','.join(fields)}]")
        details = []
        if missing:
            details.append(f"manquantes={missing}")
        if added:
            details.append(f"ajoutées={added}")
        if changed:
            details.append(f"modifiées={changed}")
        suffix = f" ({'; '.join(details)})" if details else ""
        raise PromotionError(
            "empreintes ou collections des dépendances ont changé" + suffix
        )


def _assert_original_and_dependencies_unchanged(mb, entry: dict[str, Any]) -> None:
    preconditions = entry["preconditions"]
    original = LiveCatalog(mb).dashboard(entry["original_id"])
    if dashboard_fingerprint(original) != preconditions["original_fingerprint"]:
        raise PromotionError(f"original #{entry['original_id']} a changé")
    copy_dashboard = LiveCatalog(mb).dashboard(entry["copy_id"])
    _assert_dependency_audit_unchanged(mb, entry, copy_dashboard)


def assert_entry_preconditions(
    mb,
    entry: dict[str, Any],
    *,
    verifier: Callable[..., tuple[bool, str]] = verify_pipeline,
) -> None:
    """Relit les préconditions juste avant le PUT; aucune confiance dans un vieux plan."""
    if entry.get("status") != "READY":
        raise PromotionError("une ligne non READY ne peut pas être appliquée")
    # Cache neuf et circonscrit à CETTE précondition. Il évite les doubles lectures du
    # verifier sans jamais survivre au PUT qui suit.
    read_mb = CachedReadMetabase(mb)
    catalog = LiveCatalog(read_mb)
    original = catalog.dashboard(entry["original_id"])
    copy_dashboard = catalog.dashboard(entry["copy_id"])
    preconditions = entry["preconditions"]
    if dashboard_fingerprint(original) != preconditions["original_fingerprint"]:
        raise PromotionError(f"précondition original #{entry['original_id']} divergente")
    if dashboard_fingerprint(copy_dashboard) != preconditions["copy_fingerprint"]:
        raise PromotionError(f"précondition copie #{entry['copy_id']} divergente")
    original_collection = None
    original_collection_id = original.get("collection_id")
    if original_collection_id is not None:
        original_collection = catalog.collection(int(original_collection_id))
    archived_or_trash = dashboard_is_archived_or_trash(
        original, original_collection
    )
    target_collection_override = entry.get("target_collection_override")
    if target_collection_override is not None:
        target_collection_override = _positive_id(
            target_collection_override, "target_collection_override"
        )
        if not archived_or_trash:
            raise PromotionError(
                f"override collection interdit pour l'original actif "
                f"#{entry['original_id']}"
            )
        expected_collection_id = target_collection_override
        expected_override_marker = f"target_collection:{target_collection_override}"
        if expected_override_marker not in entry.get("overrides", []):
            raise PromotionError(
                f"override collection de l'original #{entry['original_id']} divergent"
            )
    else:
        expected_collection_id = original_collection_id
        if archived_or_trash:
            raise PromotionError(
                f"original #{entry['original_id']} archivé sans collection cible "
                "explicite"
            )
    expected_target_name = f"{str(original.get('name') or '').strip()} {TARGET_TAG}"
    if entry["target"] != {
        "name": expected_target_name,
        "collection_id": expected_collection_id,
    }:
        raise PromotionError(f"cible copie #{entry['copy_id']} divergente de l'original")
    collection_id = copy_dashboard.get("collection_id")
    if collection_id is None:
        raise PromotionError(f"copie #{entry['copy_id']} hors staging")
    collection = catalog.collection(int(collection_id))
    if not collection_is_in_tree(collection, STAGING_ROOT_ID):
        raise PromotionError(f"copie #{entry['copy_id']} hors staging")
    if collection_is_personal(collection) or collection_is_archived(collection):
        raise PromotionError(f"collection staging copie #{entry['copy_id']} invalide")
    if copy_dashboard.get("archived") or copy_dashboard.get("archived_directly"):
        raise PromotionError(f"copie #{entry['copy_id']} archivée")
    if TARGET_TAG not in str(copy_dashboard.get("name") or ""):
        raise PromotionError(f"copie #{entry['copy_id']} sans tag live {TARGET_TAG}")
    if copy_dashboard.get("can_write") is False:
        raise PromotionError(f"copie #{entry['copy_id']} non modifiable")
    destination_id = entry["target"]["collection_id"]
    destination = None
    if destination_id is not None:
        destination = catalog.collection(int(destination_id))
        if collection_is_personal(destination) or collection_is_archived(destination):
            raise PromotionError(f"collection destination #{destination_id} invalide")
        if collection_is_in_tree(destination, STAGING_ROOT_ID):
            raise PromotionError(f"collection destination #{destination_id} dans le staging")
    verified, _note = verifier(read_mb, entry["copy_id"], entry["client"])
    if not verified:
        raise PromotionError(f"revalidation live copie #{entry['copy_id']} en échec")
    collision_reasons = _collision_reasons(
        LiveCatalog(read_mb),
        entry["target"]["collection_id"],
        entry["target"]["name"],
        entry["copy_id"],
    )
    if collision_reasons:
        raise PromotionError(f"collision cible copie #{entry['copy_id']}")
    _assert_dependency_audit_unchanged(read_mb, entry, copy_dashboard)


def _snapshot_body(
    plan: dict[str, Any],
    ready: list[dict[str, Any]],
    *,
    failure_mode: str = "atomic",
    excluded_original_ids: Iterable[int] = (),
) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "operation": "promote_conversion_copies",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plan_hash": plan["plan_hash"],
        "failure_mode": failure_mode,
        "selected_original_ids": [entry["original_id"] for entry in ready],
        "excluded_original_ids": list(excluded_original_ids),
        "status": "PREPARED",
        "applied_order": [],
        "successes": [],
        "failures": [],
        "entries": [
            {
                "original_id": entry["original_id"],
                "copy_id": entry["copy_id"],
                "before": {
                    "name": entry["preconditions"]["copy_state"]["name"],
                    "collection_id": entry["preconditions"]["copy_state"]["collection_id"],
                    "fingerprint": entry["preconditions"]["copy_fingerprint"],
                },
                "after": {
                    "name": entry["target"]["name"],
                    "collection_id": entry["target"]["collection_id"],
                    "fingerprint": entry["preconditions"]["expected_copy_fingerprint"],
                },
                "original_fingerprint": entry["preconditions"]["original_fingerprint"],
                "dependency_cards": deepcopy(
                    entry["preconditions"].get("dependency_cards") or []
                ),
            }
            for entry in ready
        ],
    }


def _with_snapshot_hash(snapshot: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    return {**body, "snapshot_hash": stable_hash(body)}


def validate_snapshot_hash(snapshot: dict[str, Any]) -> None:
    expected = snapshot.get("snapshot_hash")
    body = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    if expected != stable_hash(body):
        raise PromotionError("hash du snapshot invalide")


def _snapshot_entry_by_copy(snapshot: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(entry["copy_id"]): entry
        for entry in snapshot.get("entries") or []
        if isinstance(entry, dict) and entry.get("copy_id")
    }


def _restore_attempted(
    mb,
    snapshot: dict[str, Any],
    attempted_copy_ids: list[int],
    *,
    progress: ProgressCallback | None = None,
) -> tuple[bool, list[str]]:
    entries = _snapshot_entry_by_copy(snapshot)
    errors = []
    rollback_order = list(reversed(attempted_copy_ids))
    for current, copy_id in enumerate(rollback_order, 1):
        item = entries[copy_id]
        _emit_progress(
            progress,
            phase="rollback",
            status="START",
            current=current,
            total=len(rollback_order),
            original_id=item["original_id"],
            copy_id=copy_id,
        )
        try:
            _put_dashboard_identity(
                mb,
                copy_id,
                name=item["before"]["name"],
                collection_id=item["before"]["collection_id"],
            )
            # Cache créé après le PUT de rollback : aucune valeur pré-PUT ne fuit ici.
            reread = LiveCatalog(CachedReadMetabase(mb)).dashboard(copy_id)
            if dashboard_fingerprint(reread) != item["before"]["fingerprint"]:
                raise PromotionError(f"rollback copie #{copy_id} divergent")
            _emit_progress(
                progress,
                phase="rollback",
                status="RESTORED",
                current=current,
                total=len(rollback_order),
                original_id=item["original_id"],
                copy_id=copy_id,
            )
        except Exception as exc:
            errors.append(str(exc))
            _emit_progress(
                progress,
                phase="rollback",
                status="FAILED",
                current=current,
                total=len(rollback_order),
                original_id=item["original_id"],
                copy_id=copy_id,
            )
    return not errors, errors


def _isolated_failure(
    entry: dict[str, Any],
    *,
    stage: str,
    exc: Exception,
    mutation_attempted: bool,
    rollback_status: str,
    rollback_errors: list[str] | None = None,
) -> dict[str, Any]:
    """Résultat persistant et explicite d'une copie isolée en échec."""
    return {
        "original_id": entry["original_id"],
        "copy_id": entry["copy_id"],
        "stage": stage,
        "message": str(exc),
        "mutation_attempted": mutation_attempted,
        "rollback": {
            "status": rollback_status,
            "errors": list(rollback_errors or []),
        },
    }


def _apply_plan_isolated(
    mb,
    ready: list[dict[str, Any]],
    snapshot: dict[str, Any],
    snapshot_path: Path,
    *,
    verifier: Callable[..., tuple[bool, str]],
    progress: ProgressCallback | None,
) -> dict[str, Any]:
    """Applique chaque copie comme une mini-transaction indépendante.

    Une précondition en échec n'entraîne aucun PUT. Dès qu'un PUT a été tenté, tout
    échec de cette ligne restaure uniquement cette copie. Un rollback local incomplet
    arrête le lot fail-closed, sans toucher aux succès antérieurs.
    """
    successful_entries: list[dict[str, Any]] = []
    success_by_copy: dict[int, dict[str, Any]] = {}

    for current, entry in enumerate(ready, 1):
        _emit_progress(
            progress,
            phase="apply",
            status="PRECONDITION",
            current=current,
            total=len(ready),
            original_id=entry["original_id"],
            copy_id=entry["copy_id"],
        )
        stage = "precondition"
        mutation_attempted = False
        try:
            assert_entry_preconditions(mb, entry, verifier=verifier)
            stage = "put"
            mutation_attempted = True
            _put_dashboard_identity(
                mb,
                entry["copy_id"],
                name=entry["target"]["name"],
                collection_id=entry["target"]["collection_id"],
            )
            stage = "post_read"
            post_read_mb = CachedReadMetabase(mb)
            reread = LiveCatalog(post_read_mb).dashboard(entry["copy_id"])
            actual = dashboard_fingerprint(reread)
            expected = entry["preconditions"]["expected_copy_fingerprint"]
            if actual != expected:
                raise PromotionError(
                    f"empreinte post-PUT copie #{entry['copy_id']} divergente"
                )
            if reread.get("archived") or reread.get("archived_directly"):
                raise PromotionError(
                    f"copie #{entry['copy_id']} archivée après promotion"
                )
            stage = "post_invariants"
            _assert_original_and_dependencies_unchanged(post_read_mb, entry)
        except Exception as exc:
            rollback_ok, rollback_errors = True, []
            rollback_status = "NOT_REQUIRED"
            if mutation_attempted:
                rollback_ok, rollback_errors = _restore_attempted(
                    mb, snapshot, [entry["copy_id"]], progress=progress
                )
                rollback_status = "RESTORED" if rollback_ok else "FAILED"
            snapshot["failures"].append(
                _isolated_failure(
                    entry,
                    stage=stage,
                    exc=exc,
                    mutation_attempted=mutation_attempted,
                    rollback_status=rollback_status,
                    rollback_errors=rollback_errors,
                )
            )
            snapshot["status"] = (
                "APPLYING_WITH_FAILURES" if rollback_ok else "ROLLBACK_FAILED"
            )
            snapshot = _with_snapshot_hash(snapshot)
            _atomic_write_json(snapshot_path, snapshot)
            _emit_progress(
                progress,
                phase="apply",
                status="FAILED" if rollback_ok else "ROLLBACK_FAILED",
                current=current,
                total=len(ready),
                original_id=entry["original_id"],
                copy_id=entry["copy_id"],
            )
            if not rollback_ok:
                raise PromotionTransactionError(
                    "promotion isolée arrêtée; rollback local incomplet; "
                    "succès précédents conservés",
                    snapshot_path,
                    False,
                ) from exc
            continue

        snapshot["applied_order"].append(entry["copy_id"])
        outcome = {
            "original_id": entry["original_id"],
            "copy_id": entry["copy_id"],
            "status": "APPLIED",
        }
        snapshot["successes"].append(outcome)
        success_by_copy[entry["copy_id"]] = outcome
        successful_entries.append(entry)
        snapshot["status"] = (
            "APPLYING_WITH_FAILURES" if snapshot["failures"] else "APPLYING"
        )
        snapshot = _with_snapshot_hash(snapshot)
        _atomic_write_json(snapshot_path, snapshot)
        _emit_progress(
            progress,
            phase="apply",
            status="APPLIED",
            current=current,
            total=len(ready),
            original_id=entry["original_id"],
            copy_id=entry["copy_id"],
        )

    # Seules les lignes dont le post-read a réussi sont auditées. Une divergence
    # découverte ici est consignée mais n'est pas écrasée par un rollback aveugle :
    # elle peut précisément signaler une mutation externe postérieure au PUT.
    for current, entry in enumerate(successful_entries, 1):
        try:
            final_read_mb = CachedReadMetabase(mb)
            reread = LiveCatalog(final_read_mb).dashboard(entry["copy_id"])
            if (
                dashboard_fingerprint(reread)
                != entry["preconditions"]["expected_copy_fingerprint"]
            ):
                raise PromotionError(
                    f"empreinte finale copie #{entry['copy_id']} divergente"
                )
            _assert_original_and_dependencies_unchanged(final_read_mb, entry)
        except Exception as exc:
            success_by_copy[entry["copy_id"]]["status"] = "AUDIT_FAILED"
            snapshot["failures"].append(
                _isolated_failure(
                    entry,
                    stage="final_audit",
                    exc=exc,
                    mutation_attempted=True,
                    rollback_status="NOT_ATTEMPTED",
                )
            )
            audit_status = "FAILED"
        else:
            success_by_copy[entry["copy_id"]]["status"] = "VERIFIED"
            audit_status = "VERIFIED"
        snapshot["status"] = (
            "APPLYING_WITH_FAILURES" if snapshot["failures"] else "APPLYING"
        )
        snapshot = _with_snapshot_hash(snapshot)
        _atomic_write_json(snapshot_path, snapshot)
        _emit_progress(
            progress,
            phase="final_audit",
            status=audit_status,
            current=current,
            total=len(successful_entries),
            original_id=entry["original_id"],
            copy_id=entry["copy_id"],
        )

    verified = sum(
        outcome["status"] == "VERIFIED" for outcome in snapshot["successes"]
    )
    failed_copy_ids = {
        int(failure["copy_id"])
        for failure in snapshot["failures"]
        if failure.get("copy_id") is not None
    }
    if not snapshot["failures"]:
        status = "APPLIED"
    elif snapshot["applied_order"]:
        status = "PARTIAL"
    else:
        status = "FAILED"
    snapshot["status"] = status
    snapshot = _with_snapshot_hash(snapshot)
    _atomic_write_json(snapshot_path, snapshot)
    return {
        "status": status,
        "applied": len(snapshot["applied_order"]),
        "verified": verified,
        "failed": len(failed_copy_ids),
        "snapshot_path": str(snapshot_path),
    }


def apply_plan(
    mb,
    plan: dict[str, Any],
    snapshot_path: Path,
    *,
    verifier: Callable[..., tuple[bool, str]] = verify_pipeline,
    progress: ProgressCallback | None = None,
    continue_on_error: bool = False,
    selected_original_ids: Iterable[int] | None = None,
    excluded_original_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Applique les READY atomiquement, ou copie par copie en mode isolé."""
    validate_plan_hash(plan)
    entries = list(plan.get("entries") or [])
    ready = [entry for entry in entries if entry.get("status") == "READY"]
    selected_ids = list(selected_original_ids or [])
    excluded_ids = list(excluded_original_ids or [])
    if selected_ids and excluded_ids:
        raise PromotionError(
            "--only-original et --exclude-original sont mutuellement exclusifs"
        )
    excluded_ids = [
        _positive_id(value, "excluded_original_ids") for value in excluded_ids
    ]
    if len(set(excluded_ids)) != len(excluded_ids):
        raise PromotionError("sélection --exclude-original dupliquée")
    by_original: dict[int, list[dict[str, Any]]] = {}
    for entry in entries:
        original_id = _positive_id(entry.get("original_id"), "plan.original_id")
        by_original.setdefault(original_id, []).append(entry)
    if selected_ids:
        selected_ids = [
            _positive_id(value, "selected_original_ids") for value in selected_ids
        ]
        if len(set(selected_ids)) != len(selected_ids):
            raise PromotionError("sélection --only-original dupliquée")
        selected_ready = []
        for original_id in selected_ids:
            matches = by_original.get(original_id) or []
            if len(matches) != 1:
                raise PromotionError(
                    f"original sélectionné #{original_id} absent ou ambigu dans le plan"
                )
            entry = matches[0]
            if entry.get("status") != "READY":
                reason_codes = ", ".join(
                    str(reason.get("code"))
                    for reason in entry.get("reasons") or []
                    if isinstance(reason, dict) and reason.get("code")
                )
                suffix = f" ({reason_codes})" if reason_codes else ""
                raise PromotionError(
                    f"original sélectionné #{original_id} non READY{suffix}"
                )
            selected_ready.append(entry)
        ready = selected_ready
    elif excluded_ids:
        for original_id in excluded_ids:
            matches = by_original.get(original_id) or []
            if len(matches) != 1:
                raise PromotionError(
                    f"original exclu #{original_id} absent ou ambigu dans le plan"
                )
            if matches[0].get("status") != "READY":
                raise PromotionError(
                    f"original exclu #{original_id} non READY"
                )
        excluded_set = set(excluded_ids)
        ready = [
            entry for entry in ready if int(entry["original_id"]) not in excluded_set
        ]
    ready.sort(key=lambda item: item["original_id"])
    if not ready:
        return {"status": "NOTHING_TO_DO", "applied": 0, "snapshot_path": None}

    # Le snapshot doit exister avant la première mutation.
    failure_mode = "isolated" if continue_on_error else "atomic"
    snapshot = _with_snapshot_hash(
        _snapshot_body(
            plan,
            ready,
            failure_mode=failure_mode,
            excluded_original_ids=excluded_ids,
        )
    )
    _atomic_write_json(snapshot_path, snapshot)
    if continue_on_error:
        return _apply_plan_isolated(
            mb,
            ready,
            snapshot,
            snapshot_path,
            verifier=verifier,
            progress=progress,
        )
    attempted: list[int] = []
    try:
        for current, entry in enumerate(ready, 1):
            _emit_progress(
                progress,
                phase="apply",
                status="PRECONDITION",
                current=current,
                total=len(ready),
                original_id=entry["original_id"],
                copy_id=entry["copy_id"],
            )
            assert_entry_preconditions(mb, entry, verifier=verifier)
            attempted.append(entry["copy_id"])
            _put_dashboard_identity(
                mb,
                entry["copy_id"],
                name=entry["target"]["name"],
                collection_id=entry["target"]["collection_id"],
            )
            # Nouvelle phase de lecture après mutation : cache volontairement neuf.
            post_read_mb = CachedReadMetabase(mb)
            reread = LiveCatalog(post_read_mb).dashboard(entry["copy_id"])
            actual = dashboard_fingerprint(reread)
            expected = entry["preconditions"]["expected_copy_fingerprint"]
            if actual != expected:
                raise PromotionError(
                    f"empreinte post-PUT copie #{entry['copy_id']} divergente"
                )
            if reread.get("archived") or reread.get("archived_directly"):
                raise PromotionError(f"copie #{entry['copy_id']} archivée après promotion")
            _assert_original_and_dependencies_unchanged(post_read_mb, entry)
            snapshot["applied_order"].append(entry["copy_id"])
            snapshot["status"] = "APPLYING"
            snapshot = _with_snapshot_hash(snapshot)
            _atomic_write_json(snapshot_path, snapshot)
            _emit_progress(
                progress,
                phase="apply",
                status="APPLIED",
                current=current,
                total=len(ready),
                original_id=entry["original_id"],
                copy_id=entry["copy_id"],
            )
        # Audit de lot : une course externe après la première ligne ne doit pas être
        # masquée par le succès des lignes suivantes.
        for current, entry in enumerate(ready, 1):
            # Cache neuf par ligne d'audit final, donc postérieur à toutes les mutations.
            final_read_mb = CachedReadMetabase(mb)
            reread = LiveCatalog(final_read_mb).dashboard(entry["copy_id"])
            if dashboard_fingerprint(reread) != entry["preconditions"]["expected_copy_fingerprint"]:
                raise PromotionError(
                    f"empreinte finale copie #{entry['copy_id']} divergente"
                )
            _assert_original_and_dependencies_unchanged(final_read_mb, entry)
            _emit_progress(
                progress,
                phase="final_audit",
                status="VERIFIED",
                current=current,
                total=len(ready),
                original_id=entry["original_id"],
                copy_id=entry["copy_id"],
            )
    except Exception as exc:
        rollback_ok, rollback_errors = _restore_attempted(
            mb, snapshot, attempted, progress=progress
        )
        snapshot["status"] = "ROLLED_BACK" if rollback_ok else "ROLLBACK_FAILED"
        snapshot["failure"] = {
            "message": str(exc),
            "rollback_errors": rollback_errors,
        }
        snapshot = _with_snapshot_hash(snapshot)
        _atomic_write_json(snapshot_path, snapshot)
        raise PromotionTransactionError(
            f"promotion interrompue; rollback {'vérifié' if rollback_ok else 'incomplet'}",
            snapshot_path,
            rollback_ok,
        ) from exc

    snapshot["status"] = "APPLIED"
    snapshot = _with_snapshot_hash(snapshot)
    _atomic_write_json(snapshot_path, snapshot)
    return {
        "status": "APPLIED",
        "applied": len(ready),
        "snapshot_path": str(snapshot_path),
    }


def _assert_snapshot_rollback_preconditions(
    mb, item: dict[str, Any]
) -> str:
    read_mb = CachedReadMetabase(mb)
    current = LiveCatalog(read_mb).dashboard(int(item["copy_id"]))
    current_fingerprint = dashboard_fingerprint(current)
    if current_fingerprint == item["before"]["fingerprint"]:
        return "ALREADY_ROLLED_BACK"
    if current_fingerprint != item["after"]["fingerprint"]:
        raise PromotionError(
            f"copie #{item['copy_id']} a divergé depuis la promotion"
        )
    original = LiveCatalog(read_mb).dashboard(int(item["original_id"]))
    if dashboard_fingerprint(original) != item["original_fingerprint"]:
        raise PromotionError(f"original #{item['original_id']} a changé")
    for dependency in item.get("dependency_cards") or []:
        if _fresh_card_fingerprint(read_mb, int(dependency["card_id"])) != dependency["fingerprint"]:
            raise PromotionError(
                f"dépendance carte #{dependency['card_id']} a changé"
            )
    return "READY"


def rollback_snapshot(
    mb,
    snapshot: dict[str, Any],
    *,
    yes: bool = False,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Rollback explicite, lui-même transactionnel et dry-run par défaut."""
    validate_snapshot_hash(snapshot)
    entries = _snapshot_entry_by_copy(snapshot)
    order = [int(value) for value in snapshot.get("applied_order") or []]
    states = {
        copy_id: _assert_snapshot_rollback_preconditions(mb, entries[copy_id])
        for copy_id in reversed(order)
    }
    ready = [copy_id for copy_id in reversed(order) if states[copy_id] == "READY"]
    if not yes:
        return {
            "status": "DRY_RUN",
            "ready": len(ready),
            "already_rolled_back": len(order) - len(ready),
        }

    restored = []
    try:
        for current, copy_id in enumerate(ready, 1):
            item = entries[copy_id]
            _emit_progress(
                progress,
                phase="explicit_rollback",
                status="START",
                current=current,
                total=len(ready),
                original_id=item["original_id"],
                copy_id=copy_id,
            )
            _put_dashboard_identity(
                mb,
                copy_id,
                name=item["before"]["name"],
                collection_id=item["before"]["collection_id"],
            )
            reread = LiveCatalog(CachedReadMetabase(mb)).dashboard(copy_id)
            if dashboard_fingerprint(reread) != item["before"]["fingerprint"]:
                raise PromotionError(f"rollback copie #{copy_id} divergent")
            restored.append(copy_id)
            _emit_progress(
                progress,
                phase="explicit_rollback",
                status="RESTORED",
                current=current,
                total=len(ready),
                original_id=item["original_id"],
                copy_id=copy_id,
            )
    except Exception as exc:
        # Le rollback explicite est lui aussi atomique : remettre les lignes déjà
        # restaurées dans leur état promu si une suivante échoue.
        rollforward_errors = []
        for copy_id in reversed(restored):
            item = entries[copy_id]
            try:
                _put_dashboard_identity(
                    mb,
                    copy_id,
                    name=item["after"]["name"],
                    collection_id=item["after"]["collection_id"],
                )
                reread = LiveCatalog(CachedReadMetabase(mb)).dashboard(copy_id)
                if dashboard_fingerprint(reread) != item["after"]["fingerprint"]:
                    raise PromotionError(f"roll-forward copie #{copy_id} divergent")
            except Exception as rollback_exc:
                rollforward_errors.append(str(rollback_exc))
        suffix = "" if not rollforward_errors else "; roll-forward incomplet"
        raise PromotionError(f"rollback explicite interrompu{suffix}") from exc
    return {
        "status": "ROLLED_BACK",
        "restored": len(restored),
        "already_rolled_back": len(order) - len(restored),
    }


def _default_snapshot_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return MIGRATION / f"promotion-snapshot-{stamp}.json"


def cli_progress(event: dict[str, Any]) -> None:
    phase = str(event.get("phase") or "progress")
    status = str(event.get("status") or "")
    current = event.get("current")
    total = event.get("total")
    original_id = event.get("original_id")
    copy_id = event.get("copy_id")
    print(
        f"[{phase} {current}/{total}] {status} — "
        f"original #{original_id} / copie #{copy_id}",
        flush=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--accounting", type=Path, default=DEFAULT_ACCOUNTING)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--snapshot-output", type=Path)
    parser.add_argument(
        "--target-collection-override",
        action="append",
        type=_parse_target_collection_override,
        default=[],
        metavar="ORIGINAL_ID:TARGET_COLLECTION_ID",
        help=(
            "collection de destination explicite, répétable, requise pour un "
            "original archivé/dans la corbeille"
        ),
    )
    parser.add_argument(
        "--rollback",
        type=Path,
        help="snapshot d'une promotion à restaurer (dry-run sans --yes)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="applique les READY, ou le rollback demandé; sinon lecture seule",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help=(
            "mode isolé: conserve les succès, restaure seulement la copie en "
            "échec si son PUT a été tenté, puis continue"
        ),
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--only-original",
        action="append",
        type=_parse_original_id,
        default=[],
        metavar="ORIGINAL_ID",
        help=(
            "applique uniquement cet original READY; répétable et validé avant "
            "toute mutation"
        ),
    )
    selection.add_argument(
        "--exclude-original",
        action="append",
        type=_parse_original_id,
        default=[],
        metavar="ORIGINAL_ID",
        help=(
            "exclut cet original READY du lot; répétable et validé avant "
            "toute mutation"
        ),
    )
    return parser


def execute(args: argparse.Namespace) -> int:
    mb = connect_redacted()
    if args.rollback:
        if args.only_original or args.exclude_original:
            raise PromotionError(
                "la sélection d'originaux s'applique à une promotion, pas à --rollback"
            )
        snapshot = _read_json(args.rollback)
        result = rollback_snapshot(
            mb, snapshot, yes=args.yes, progress=cli_progress
        )
        print(
            f"{result['status']} — rollback: "
            f"{result.get('restored', result.get('ready', 0))} copie(s), "
            f"{result.get('already_rolled_back', 0)} déjà restaurée(s)."
        )
        return 0

    manifest = _read_json(args.manifest)
    accounting = _read_json(args.accounting)
    decisions = _read_json(args.decisions)
    plan = build_promotion_plan(
        manifest,
        accounting,
        decisions,
        mb,
        target_collection_overrides=_target_collection_override_map(
            args.target_collection_override
        ),
        source_labels={
            "manifest": _display_path(args.manifest),
            "accounting": _display_path(args.accounting),
            "canonical_decisions": _display_path(args.decisions),
        },
        progress=cli_progress,
    )
    _atomic_write_json(args.output, plan)
    print(
        f"PLAN {plan['plan_hash']} — {plan['summary']['ready']} READY / "
        f"{plan['summary']['blocked']} BLOCKED. JSON: {args.output}"
    )
    if not args.yes:
        print("DRY-RUN — aucune mutation Metabase.")
        return 0
    snapshot_path = args.snapshot_output or _default_snapshot_path()
    result = apply_plan(
        mb,
        plan,
        snapshot_path,
        progress=cli_progress,
        continue_on_error=args.continue_on_error,
        selected_original_ids=args.only_original,
        excluded_original_ids=args.exclude_original,
    )
    if result["status"] == "NOTHING_TO_DO":
        print("RIEN À FAIRE — aucune copie READY sélectionnée.")
        return 0
    if result["status"] == "APPLIED":
        print(
            f"APPLIQUÉ — {result['applied']} copie(s). Snapshot: "
            f"{result['snapshot_path']}"
        )
        return 0
    print(
        f"{result['status']} — {result['verified']} copie(s) vérifiée(s), "
        f"{result['failed']} en échec, {result['applied']} mutation(s) conservée(s). "
        f"Snapshot: {result['snapshot_path']}"
    )
    return 1


def main() -> int:
    try:
        return execute(build_parser().parse_args())
    except PromotionTransactionError as exc:
        print(
            redact_sensitive_output(
                f"⛔ {exc}. Snapshot: {exc.snapshot_path}"
            ),
            file=sys.stderr,
        )
        return 1
    except PromotionError as exc:
        print(redact_sensitive_output(f"⛔ {exc}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
