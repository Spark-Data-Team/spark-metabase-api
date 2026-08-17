#!/usr/bin/env python3
"""Exporte le mapping de conversions depuis Supabase production, en lecture seule.

Le snapshot conserve chaque ligne ``pipeline_manager.conversions``, les deux tableaux
indépendants ``type[]`` / ``new_type[]`` et des marqueurs qui distinguent strictement
SQL ``NULL`` d'un tableau vide. Un slot n'est auto-mappé que si son ensemble exact de
lignes est égal à celui d'une unique cible ``new_type``.

Par défaut, la commande est un dry-run (lecture + validation, aucun fichier écrit) :

    python3 scripts/export_supabase_conversion_mapping.py \
      --env-file ../pipeline-manager/.env

L'écriture LOCALE du snapshot doit être demandée explicitement :

    python3 scripts/export_supabase_conversion_mapping.py \
      --env-file ../pipeline-manager/.env --write

Cette commande n'implémente aucune opération d'écriture Supabase.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import conv_lib


SCHEMA_VERSION = 1
DEFAULT_OUTPUT = REPO / "migration" / "conv-supabase-snapshot.json"
PROD_URL_KEY = "SUPABASE_URL_PROD"
PROD_SERVICE_KEY = "SUPABASE_SERVICE_KEY_PROD"
NON_POSITIONAL_TYPES = {"Add to cart", "App install"}


class SnapshotError(RuntimeError):
    """Le snapshot ne peut pas être construit ou consommé sans risque."""


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse le sous-ensemble simple d'un .env sans jamais journaliser ses valeurs."""
    if not path.is_file():
        raise SnapshotError(f"fichier de credentials introuvable: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise SnapshotError(f"ligne .env invalide ({path}:{line_number})")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def load_prod_credentials(
    env_file: Path | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Charge uniquement les variables explicitement suffixées ``_PROD``.

    Les variables du processus priment sur le fichier. La fonction ne renvoie ni
    n'affiche de diagnostic contenant l'URL complète ou la clé service.
    """
    values = _parse_env_file(env_file) if env_file else {}
    values.update(environ if environ is not None else os.environ)
    url = str(values.get(PROD_URL_KEY) or "").strip().rstrip("/")
    service_key = str(values.get(PROD_SERVICE_KEY) or "").strip()
    if not url or not service_key:
        missing = [k for k, value in ((PROD_URL_KEY, url), (PROD_SERVICE_KEY, service_key)) if not value]
        raise SnapshotError(f"credentials production manquants: {', '.join(missing)}")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/")
            or not str(parsed.hostname or "").endswith(".supabase.co")):
        raise SnapshotError(f"{PROD_URL_KEY} doit être une origine HTTPS Supabase")
    return url, service_key


class SupabaseReader:
    """Client PostgREST volontairement limité à des GET paginés."""

    def __init__(
        self,
        url: str,
        service_key: str,
        *,
        session: requests.Session | None = None,
        page_size: int = 1000,
        retries: int = 4,
        retry_delay: float = 1.0,
        timeout: float = 45.0,
    ) -> None:
        if page_size < 1 or retries < 1:
            raise ValueError("page_size et retries doivent être positifs")
        self._url = url.rstrip("/")
        self._service_key = service_key
        self._session = session or requests.Session()
        self._page_size = page_size
        self._retries = retries
        self._retry_delay = retry_delay
        self._timeout = timeout

    def fetch_all(self, schema: str, table: str, select: str) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        while True:
            page = self._get_page(schema, table, select, offset)
            rows.extend(page)
            if len(page) < self._page_size:
                return rows
            offset += self._page_size

    def _get_page(self, schema: str, table: str, select: str, offset: int) -> list[dict]:
        headers = {
            "apikey": self._service_key,
            "Authorization": f"Bearer {self._service_key}",
            "Accept-Profile": schema,
        }
        params = {
            "select": select,
            "order": "id.asc",
            "limit": str(self._page_size),
            "offset": str(offset),
        }
        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = self._session.get(
                    f"{self._url}/rest/v1/{table}",
                    headers=headers,
                    params=params,
                    timeout=self._timeout,
                )
                if response.status_code >= 400:
                    raise SnapshotError(
                        f"lecture Supabase refusée pour {schema}.{table} "
                        f"(HTTP {response.status_code})"
                    )
                payload = response.json()
                if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
                    raise SnapshotError(f"réponse invalide pour {schema}.{table}: liste JSON attendue")
                return payload
            except SnapshotError:
                raise
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self._retries:
                    time.sleep(self._retry_delay * (2**attempt))
        raise SnapshotError(
            f"lecture Supabase impossible pour {schema}.{table} après {self._retries} essais"
        ) from last_error


def fetch_source_rows(reader: SupabaseReader) -> tuple[list[dict], list[dict], list[dict]]:
    """Lit les trois tables nécessaires. L'ordre des appels ne change jamais la source."""
    companies = reader.fetch_all("public", "companies", "id,name")
    accounts = reader.fetch_all(
        "pipeline_manager",
        "accounts",
        "id,account_id,account_name,company_id",
    )
    conversions = reader.fetch_all(
        "pipeline_manager",
        "conversions",
        "id,account_id,conversion_id,conversion_name,type,new_type,updated_at",
    )
    return companies, accounts, conversions


def _index_unique(rows: list[dict], label: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            raise SnapshotError(f"{label}: ligne sans id")
        if row_id in index:
            raise SnapshotError(f"{label}: id dupliqué {row_id}")
        index[row_id] = row
    return index


def _array(value, field: str, row_id: str) -> list[str | None]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SnapshotError(f"conversion {row_id}: {field} n'est pas un tableau")
    out: list[str | None] = []
    for item in value:
        if item is None:
            out.append(None)
        elif isinstance(item, str):
            out.append(item.strip() or None)
        else:
            raise SnapshotError(f"conversion {row_id}: valeur non textuelle dans {field}")
    return out


def _valid_new_type(value: str | None) -> bool:
    return bool(value and conv_lib.new_type_columns(value)[0])


def diagnose_decision_row_sets(
    mapping: dict,
    decisions: list[dict],
    row_sets: dict,
    *,
    name_collisions: set[tuple[str, int]] | None = None,
) -> tuple[dict[str, dict[str, str]], list[dict]]:
    """Conserve les décisions comme candidates et diagnostique leur écart row-set.

    Deux slots peuvent légitimement partager un ``new_type`` lorsque leurs ensembles
    source sont identiques. Le nombre de slots et le simple overlap ne sont donc pas des
    critères de collision ; seule l'égalité exacte prouve la fidélité de substitution.
    """
    candidates = json.loads(json.dumps(mapping or {}))
    diagnostics: list[dict] = []
    source_sets = (row_sets or {}).get("source") or {}
    target_sets = (row_sets or {}).get("target") or {}
    collided_names = name_collisions or set()
    for decision in decisions or []:
        client = str(decision.get("client") or "").strip()
        slot = int(decision["slot"])
        new_type = str(decision.get("new_type") or "").strip()
        source = set(((source_sets.get(client) or {}).get(str(slot))) or [])
        target = set(((target_sets.get(client) or {}).get(new_type)) or [])
        if (client, slot) in collided_names:
            candidates.setdefault(client, {})[str(slot)] = conv_lib.CONFLICT
            diagnostics.append(
                {
                    "kind": "decision_client_name_collision",
                    "client": client,
                    "slot": slot,
                    "new_type": new_type,
                }
            )
            continue
        elif source and source == target:
            continue
        source_only = sorted(source - target)
        target_only = sorted(target - source)
        diagnostics.append(
            {
                "kind": "decision_row_set_mismatch",
                "client": client,
                "slot": slot,
                "new_type": new_type,
                "source_row_count": len(source),
                "target_row_count": len(target),
                "source_only_count": len(source_only),
                "target_only_count": len(target_only),
                "source_only_row_ids": source_only[:25],
                "target_only_row_ids": target_only[:25],
            }
        )
    return candidates, diagnostics


def block_effective_target_collisions(
    mapping: dict,
    row_sets: dict,
) -> tuple[dict[str, dict[str, str]], list[dict]]:
    """Bloque une cible assignée à plusieurs slots dont les row-sets diffèrent.

    Partager une cible reste sûr si les slots source couvrent exactement les mêmes
    conversion rows. Les collisions ne peuvent apparaître en pratique qu'après overlay
    de décisions sémantiques, puisque l'auto-mapping exige déjà l'égalité exacte.
    """
    safe = json.loads(json.dumps(mapping or {}))
    source_sets = (row_sets or {}).get("source") or {}
    diagnostics: list[dict] = []
    for client, client_mapping in sorted(safe.items()):
        by_target: dict[str, list[int]] = defaultdict(list)
        for raw_slot, new_type in client_mapping.items():
            if new_type not in (conv_lib.UNMAPPED, conv_lib.CONFLICT):
                by_target[new_type].append(int(raw_slot))
        for new_type, slots in sorted(by_target.items()):
            slots = sorted(set(slots))
            if len(slots) < 2:
                continue
            sets = [
                set(((source_sets.get(client) or {}).get(str(slot))) or [])
                for slot in slots
            ]
            if sets and sets[0] and all(rows == sets[0] for rows in sets[1:]):
                continue
            for slot in slots:
                client_mapping[str(slot)] = conv_lib.CONFLICT
            diagnostics.append(
                {
                    "kind": "effective_target_collision",
                    "client": client,
                    "new_type": new_type,
                    "slots": slots,
                    "source_row_counts": [len(rows) for rows in sets],
                }
            )
    return safe, diagnostics


def build_snapshot(
    companies: list[dict],
    accounts: list[dict],
    conversions: list[dict],
    *,
    exported_at: str | None = None,
) -> dict:
    """Construit un snapshot déterministe, sûr au niveau de chaque slot."""
    company_by_id = _index_unique(companies, "public.companies")
    account_by_id = _index_unique(accounts, "pipeline_manager.accounts")

    # Les noms restent la clé utilisée par les filtres Metabase. Une collision de nom
    # entre companies est explicitement bloquée, même si les cibles coïncident aujourd'hui.
    company_ids_by_name: dict[str, set[str]] = defaultdict(set)
    for company_id, company in company_by_id.items():
        name = str(company.get("name") or "").strip()
        if name:
            company_ids_by_name[name].add(company_id)

    records: list[dict] = []
    ambiguities: list[dict] = []
    seen_slots: dict[str, set[int]] = defaultdict(set)
    source_rows: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    target_rows: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    name_collision_slots: set[tuple[str, int]] = set()

    for conversion in conversions:
        conversion_row_id = str(conversion.get("id") or "").strip()
        if not conversion_row_id:
            raise SnapshotError("pipeline_manager.conversions: ligne sans id")
        account_row_id = str(conversion.get("account_id") or "").strip()
        account = account_by_id.get(account_row_id)
        company = company_by_id.get(str((account or {}).get("company_id") or ""))
        company_id = str((company or {}).get("id") or "") or None
        client = str((company or {}).get("name") or "").strip() or None
        raw_type = conversion.get("type")
        raw_new_type = conversion.get("new_type")
        types = _array(raw_type, "type", conversion_row_id)
        new_types = _array(raw_new_type, "new_type", conversion_row_id)

        if client:
            for type_name in types:
                slot = conv_lib.TYPE_TO_SLOT.get(type_name)
                if slot is not None:
                    seen_slots[client].add(slot)
                    source_rows[client][slot].add(conversion_row_id)
            for new_type in new_types:
                if _valid_new_type(new_type):
                    target_rows[client][new_type].add(conversion_row_id)

        positional_types = [type_name for type_name in types if type_name in conv_lib.TYPE_TO_SLOT]
        if positional_types and new_types and len(positional_types) != len(new_types):
            ambiguities.append(
                {
                    "kind": "independent_array_cardinality",
                    "client": client,
                    "conversion_row_id": conversion_row_id,
                    "type_count": len(positional_types),
                    "new_type_count": len(new_types),
                    "slots": sorted({conv_lib.TYPE_TO_SLOT[t] for t in positional_types}),
                }
            )
        for position, type_name in enumerate(types):
            if type_name in conv_lib.TYPE_TO_SLOT or type_name in NON_POSITIONAL_TYPES:
                continue
            ambiguities.append(
                {
                    "kind": "unsupported_type",
                    "client": client,
                    "conversion_row_id": conversion_row_id,
                    "position": position,
                    "type": type_name,
                }
            )
        for position, new_type in enumerate(new_types):
            if new_type is None or _valid_new_type(new_type):
                continue
            ambiguities.append(
                {
                    "kind": "unsupported_new_type",
                    "client": client,
                    "conversion_row_id": conversion_row_id,
                    "position": position,
                    "new_type": new_type,
                }
            )

        if account is None:
            ambiguities.append(
                {
                    "kind": "account_not_found",
                    "conversion_row_id": conversion_row_id,
                    "account_row_id": account_row_id or None,
                }
            )
        elif company is None:
            ambiguities.append(
                {
                    "kind": "account_without_company",
                    "conversion_row_id": conversion_row_id,
                    "account_row_id": account_row_id,
                    "company_id": account.get("company_id"),
                }
            )

        records.append(
            {
                "company_id": company_id,
                "client": client,
                "account_row_id": account_row_id or None,
                "account_external_id": (account or {}).get("account_id"),
                "account_name": (account or {}).get("account_name"),
                "conversion_row_id": conversion_row_id,
                "conversion_id": conversion.get("conversion_id"),
                "conversion_name": conversion.get("conversion_name"),
                "type": types,
                "new_type": new_types,
                # Les row-sets consomment les tableaux normalisés ci-dessus, mais un
                # plan de mutation doit pouvoir distinguer strictement SQL NULL de
                # l'array vide. Ces marqueurs préservent cette information brute.
                "type_is_null": raw_type is None,
                "new_type_is_null": raw_new_type is None,
                "updated_at": conversion.get("updated_at"),
            }
        )

    for client, company_ids in sorted(company_ids_by_name.items()):
        if len(company_ids) < 2:
            continue
        slots = sorted(seen_slots.get(client, set()))
        for slot in slots:
            name_collision_slots.add((client, slot))
        ambiguities.append(
            {
                "kind": "client_name_collision",
                "client": client,
                "company_ids": sorted(company_ids),
                "slots": slots,
            }
        )

    # Autorité de mapping : égalité d'ensembles au grain conversion_row_id. Les deux
    # arrays Supabase sont indépendants ; leur ordre et leur cardinalité n'établissent
    # donc jamais une relation type -> new_type.
    slot_mapping: dict[str, dict[str, str]] = {}
    for client in sorted(seen_slots):
        client_mapping: dict[str, str] = {}
        for slot in sorted(seen_slots[client]):
            source_set = source_rows[client][slot]
            matches = sorted(
                new_type for new_type, rows in target_rows[client].items()
                if rows == source_set
            )
            if (client, slot) in name_collision_slots:
                value = conv_lib.CONFLICT
            elif len(matches) == 1:
                value = matches[0]
            elif len(matches) > 1:
                value = conv_lib.CONFLICT
                ambiguities.append(
                    {
                        "kind": "multiple_row_set_matches",
                        "client": client,
                        "slot": slot,
                        "new_types": matches,
                        "row_count": len(source_set),
                    }
                )
            else:
                value = conv_lib.UNMAPPED
                ambiguities.append(
                    {
                        "kind": "no_row_set_match",
                        "client": client,
                        "slot": slot,
                        "source_row_count": len(source_set),
                    }
                )
            client_mapping[str(slot)] = value
        slot_mapping[client] = client_mapping

    row_sets = {
        "source": {
            client: {str(slot): sorted(rows) for slot, rows in sorted(client_slots.items())}
            for client, client_slots in sorted(source_rows.items())
        },
        "target": {
            client: {new_type: sorted(rows) for new_type, rows in sorted(client_targets.items())}
            for client, client_targets in sorted(target_rows.items())
        },
    }
    mapping = json.loads(json.dumps(slot_mapping))
    records.sort(
        key=lambda record: (
            record.get("client") or "",
            record.get("company_id") or "",
            record.get("account_row_id") or "",
            record.get("conversion_row_id") or "",
        )
    )
    ambiguities.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    values = [value for client_mapping in mapping.values() for value in client_mapping.values()]
    conflict_count = sum(value == conv_lib.CONFLICT for value in values)
    unmapped_count = sum(value == conv_lib.UNMAPPED for value in values)
    mapped_count = len(values) - conflict_count - unmapped_count
    blocked_count = conflict_count + unmapped_count
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "system": "supabase",
            "environment": "production",
            "tables": [
                "public.companies",
                "pipeline_manager.accounts",
                "pipeline_manager.conversions",
            ],
        },
        "exported_at": exported_at or datetime.now(timezone.utc).isoformat(),
        "status": "ready_with_blocked_slots" if blocked_count else "ready",
        # Mapping auto par égalité de row-sets, avant décisions consultants.
        "slot_mapping": slot_mapping,
        # Autorité de fidélité pour les décisions explicites et l'audit : sets exacts,
        # jamais simple overlap ni association positionnelle des arrays.
        "row_sets": row_sets,
        # Mapping directement consommable sans override (auto-mapping validé).
        "mapping": mapping,
        "records": records,
        "ambiguities": ambiguities,
        "stats": {
            "companies": len(companies),
            "accounts": len(accounts),
            "conversion_rows": len(conversions),
            "clients_with_mapping": len(mapping),
            "ambiguities": len(ambiguities),
            "blocked_slots": blocked_count,
            "mapped_slots": mapped_count,
            "unmapped_slots": unmapped_count,
            "conflict_slots": conflict_count,
        },
    }


def _validate_snapshot(document: dict) -> None:
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError(f"snapshot Supabase v{SCHEMA_VERSION} attendu")
    source = document.get("source") or {}
    if source.get("system") != "supabase" or source.get("environment") != "production":
        raise SnapshotError("le snapshot ne provient pas de Supabase production")
    if (not isinstance(document.get("slot_mapping"), dict)
            or not isinstance(document.get("mapping"), dict)
            or not isinstance(document.get("row_sets"), dict)):
        raise SnapshotError("snapshot incomplet: slot_mapping/mapping/row_sets manquant")
    if document["slot_mapping"] != document["mapping"]:
        raise SnapshotError("snapshot incohérent: mapping auto invalide")
    records = document.get("records")
    if not isinstance(records, list):
        raise SnapshotError("snapshot incomplet: records[] manquant")
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise SnapshotError(f"snapshot: record {position} invalide")
        row_id = str(record.get("conversion_row_id") or position)
        for field in ("type", "new_type"):
            values = record.get(field)
            marker = record.get(f"{field}_is_null")
            if not isinstance(values, list) or not isinstance(marker, bool):
                raise SnapshotError(
                    f"snapshot: {field}/{field}_is_null invalide pour {row_id}"
                )
            if marker and values:
                raise SnapshotError(
                    f"snapshot: {field}_is_null incohérent pour {row_id}"
                )
    sources = (document["row_sets"].get("source") or {})
    targets = (document["row_sets"].get("target") or {})
    for client, slots in document["mapping"].items():
        for raw_slot, new_type in slots.items():
            if new_type in (conv_lib.UNMAPPED, conv_lib.CONFLICT):
                continue
            if not _valid_new_type(new_type):
                raise SnapshotError(f"new_type auto invalide pour {client!r}, slot {raw_slot}")
            source = set(((sources.get(client) or {}).get(str(raw_slot))) or [])
            target = set(((targets.get(client) or {}).get(new_type)) or [])
            if not source or source != target:
                raise SnapshotError(f"mapping auto non fidèle pour {client!r}, slot {raw_slot}")


def load_effective_mapping(
    snapshot_path: Path,
    decisions: list[dict] | None = None,
    *,
    decisions_override_collisions: bool = False,
) -> tuple[dict, list[dict]]:
    """Charge le snapshot et expose les décisions comme candidates diagnostiquées.

    Un row-set différent reste testable par le garde-fou de valeur aval. Seule une cible
    effectivement assignée à plusieurs slots aux row-sets différents est bloquée ici.

    ``decisions_override_collisions`` : quand True, une DÉCISION consultant explicite l'emporte
    sur le blocage de collision (une même conversion peut légitimement occuper plusieurs positions
    positionnelles — règle métier validée par l'user). Les collisions AUTO (sans décision) restent
    bloquées. Utilisé par la migration dashboards (--accept-diffs) ; l'auto-mapping strict garde False.
    """
    try:
        document = json.loads(snapshot_path.read_text())
    except FileNotFoundError as exc:
        raise SnapshotError(f"snapshot Supabase introuvable: {snapshot_path}") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"snapshot Supabase JSON invalide: {snapshot_path}") from exc
    _validate_snapshot(document)
    decision_rows = decisions or []
    overlaid = conv_lib.merge_mapping_overrides(document["slot_mapping"], decision_rows)
    name_collisions = {
        (str(item.get("client") or ""), int(slot))
        for item in (document.get("ambiguities") or [])
        if isinstance(item, dict) and item.get("kind") == "client_name_collision"
        for slot in (item.get("slots") or [])
    }
    candidates, row_set_diagnostics = diagnose_decision_row_sets(
        overlaid,
        decision_rows,
        document["row_sets"],
        name_collisions=name_collisions,
    )
    safe, collision_diagnostics = block_effective_target_collisions(
        candidates,
        document["row_sets"],
    )
    if decisions_override_collisions and decision_rows:
        # Une décision consultant explicite reste autoritaire : elle est ré-appliquée APRÈS le
        # blocage de collision, donc un slot décidé sort du CONFLICT (même conversion à plusieurs
        # positions = voulu). Les collisions AUTO (aucune décision) restent en CONFLICT.
        safe = conv_lib.merge_mapping_overrides(safe, decision_rows)
    return safe, row_set_diagnostics + collision_diagnostics


def load_repository_mapping(migration_dir: Path) -> tuple[dict, list[dict]]:
    """Charge la source Supabase locale et les décisions consultants du dépôt."""
    decisions_path = migration_dir / "consultant-decisions.json"
    try:
        decisions = json.loads(decisions_path.read_text()) if decisions_path.exists() else []
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"décisions consultants JSON invalides: {decisions_path}") from exc
    if not isinstance(decisions, list):
        raise SnapshotError(f"liste de décisions consultants attendue: {decisions_path}")
    # Migration dashboards : les décisions consultants l'emportent sur le blocage de collision
    # (une conversion peut occuper plusieurs positions positionnelles — règle métier validée user).
    return load_effective_mapping(
        migration_dir / "conv-supabase-snapshot.json", decisions,
        decisions_override_collisions=True,
    )


def write_snapshot(snapshot: dict, output: Path) -> None:
    """Écriture locale atomique ; ne contacte jamais Supabase."""
    _validate_snapshot(snapshot)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="fichier contenant les credentials *_PROD")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="valide sans écrire (défaut)")
    mode.add_argument("--write", action="store_true", help="écrit explicitement le snapshot local")
    args = parser.parse_args(argv)

    try:
        url, service_key = load_prod_credentials(args.env_file)
        reader = SupabaseReader(url, service_key)
        snapshot = build_snapshot(*fetch_source_rows(reader))
        stats = snapshot["stats"]
        print(
            "Supabase production lu et validé: "
            f"{stats['conversion_rows']} conversions, "
            f"{stats['clients_with_mapping']} clients, "
            f"{stats['blocked_slots']} slots bloqués, "
            f"{stats['ambiguities']} diagnostics."
        )
        if args.write:
            write_snapshot(snapshot, args.output)
            print(f"Snapshot local écrit: {args.output}")
        else:
            print("DRY-RUN — aucun fichier écrit.")
        return 0
    except SnapshotError as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
