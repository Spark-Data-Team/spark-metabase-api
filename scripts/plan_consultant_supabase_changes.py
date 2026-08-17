#!/usr/bin/env python3
"""Planifie, sans réseau ni écriture Supabase, les corrections consultants.

La source est le snapshot local produit par ``export_supabase_conversion_mapping.py``.
Les tableaux Supabase ``type[]`` et ``new_type[]`` sont indépendants : ce script les
compare uniquement au grain immuable ``conversion_row_id`` et ne les associe jamais
par position.

Par défaut la commande est un dry-run. ``--write`` écrit seulement un artefact JSON
local, de manière atomique. Ce module ne contient volontairement aucun client HTTP et
ne sait exécuter aucun PATCH/POST Supabase.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import conv_lib


SCHEMA_VERSION = 1
DEFAULT_SNAPSHOT = REPO / "migration" / "conv-supabase-snapshot.json"
DEFAULT_NORMALIZATION = REPO / "migration" / "consultant-normalization.json"
DEFAULT_OUTPUT = REPO / "migration" / "consultant-supabase-patch-plan.json"

KNOWN_CLASSES = {
    "canonicalisable_safe",
    "composite",
    "row_level",
    "incomplete_missing",
    "non_actionable",
}
SLOT_TO_TYPE = {slot: type_name for type_name, slot in conv_lib.TYPE_TO_SLOT.items()}


class PlanningError(RuntimeError):
    """Les artefacts locaux ne permettent pas de produire un plan fiable."""


def _load_json(path: Path, label: str) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanningError(f"{label} introuvable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PlanningError(f"{label} JSON invalide: {path}") from exc
    if not isinstance(document, dict):
        raise PlanningError(f"{label}: objet JSON attendu")
    return document


def _validate_snapshot(snapshot: dict) -> list[dict]:
    if snapshot.get("schema_version") != 1:
        raise PlanningError("snapshot Supabase v1 attendu")
    source = snapshot.get("source") or {}
    if source.get("system") != "supabase" or source.get("environment") != "production":
        raise PlanningError("snapshot Supabase production attendu")
    records = snapshot.get("records")
    if not isinstance(records, list):
        raise PlanningError("snapshot Supabase: records[] manquant")
    if not isinstance(snapshot.get("slot_mapping"), dict):
        raise PlanningError("snapshot Supabase: slot_mapping manquant")

    seen_ids: set[str] = set()
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise PlanningError(f"snapshot Supabase: record {position} invalide")
        row_id = str(record.get("conversion_row_id") or "").strip()
        if not row_id or row_id in seen_ids:
            raise PlanningError(f"snapshot Supabase: conversion_row_id absent ou dupliqué: {row_id!r}")
        seen_ids.add(row_id)
        for field in ("type", "new_type"):
            values = record.get(field)
            is_null = record.get(f"{field}_is_null")
            if not isinstance(values, list) or any(
                value is not None and not isinstance(value, str) for value in values
            ):
                raise PlanningError(f"snapshot Supabase: {field}[] invalide pour {row_id}")
            if not isinstance(is_null, bool) or (is_null and values):
                raise PlanningError(
                    f"snapshot Supabase: {field}_is_null absent ou incohérent pour {row_id}"
                )
    return records


def _validate_normalization(normalization: dict) -> list[dict]:
    if normalization.get("schema_version") != 1:
        raise PlanningError("normalisation consultants v1 attendue")
    groups = normalization.get("groups")
    if not isinstance(groups, list):
        raise PlanningError("normalisation consultants: groups[] manquant")

    seen: set[tuple[str, int]] = set()
    validated: list[dict] = []
    for position, group in enumerate(groups):
        if not isinstance(group, dict):
            raise PlanningError(f"normalisation consultants: groupe {position} invalide")
        client = str(group.get("client") or "").strip()
        try:
            slot = int(group.get("slot"))
        except (TypeError, ValueError) as exc:
            raise PlanningError(f"normalisation consultants: slot invalide pour {client!r}") from exc
        classification = group.get("class")
        targets = group.get("proposed_targets")
        key = (client, slot)
        if not client or slot not in SLOT_TO_TYPE or key in seen:
            raise PlanningError(f"normalisation consultants: clé absente, hors plage ou dupliquée: {key}")
        if classification not in KNOWN_CLASSES:
            raise PlanningError(f"normalisation consultants: classe inconnue pour {key}")
        if not isinstance(targets, list) or any(
            not isinstance(target, str) or not target.strip() for target in targets
        ):
            raise PlanningError(f"normalisation consultants: proposed_targets invalide pour {key}")
        if len(set(targets)) != len(targets):
            raise PlanningError(f"normalisation consultants: cible dupliquée pour {key}")
        if classification == "canonicalisable_safe" and len(targets) != 1:
            raise PlanningError(f"normalisation consultants: une cible canonique attendue pour {key}")
        for target in targets:
            if not conv_lib.new_type_columns(target)[0]:
                raise PlanningError(f"normalisation consultants: new_type inconnu {target!r} pour {key}")
        seen.add(key)
        validated.append(group)
    return validated


def _relation(source_ids: set[str], target_ids: set[str]) -> str:
    if source_ids == target_ids:
        return "equal"
    if target_ids < source_ids:
        return "target_strict_subset_of_source"
    if source_ids < target_ids:
        return "source_strict_subset_of_target"
    if source_ids.isdisjoint(target_ids):
        return "disjoint"
    return "overlap_without_inclusion"


def _record_context(record: dict) -> dict:
    """Contexte suffisant pour revue, sans fabriquer de payload HTTP."""
    return {
        "conversion_row_id": record["conversion_row_id"],
        "account_row_id": record.get("account_row_id"),
        "account_external_id": record.get("account_external_id"),
        "account_name": record.get("account_name"),
        "conversion_id": record.get("conversion_id"),
        "conversion_name": record.get("conversion_name"),
    }


def _add_new_type_change(record: dict, target: str) -> dict:
    """Décrit un ajout pur en conservant aussi la distinction brute NULL/array."""
    before_type = None if record["type_is_null"] else copy.deepcopy(record["type"])
    before_new_type = (
        None if record["new_type_is_null"] else copy.deepcopy(record["new_type"])
    )
    normalized_before_new_type = record["new_type"]
    if target in normalized_before_new_type:
        raise PlanningError(
            f"ajout new_type redondant pour {record['conversion_row_id']}: {target}"
        )
    return {
        **_record_context(record),
        "before": {
            "type": before_type,
            "new_type": before_new_type,
        },
        "after": {
            "type": copy.deepcopy(before_type),
            "new_type": copy.deepcopy(normalized_before_new_type) + [target],
        },
    }


def _human_change_requirement(operation: str, records_by_id: dict[str, dict], row_ids: set[str], **extra) -> dict:
    """Inventorie une mutation dangereuse sans produire de valeur ``after`` exécutable."""
    return {
        "operation": operation,
        "automatic": False,
        "requires_human_data_change": True,
        "conversion_row_ids": sorted(row_ids),
        "records": [_record_context(records_by_id[row_id]) for row_id in sorted(row_ids)],
        **extra,
    }


def build_plan(snapshot: dict, normalization: dict) -> dict:
    """Construit un plan déterministe et fail-closed à partir de deux artefacts locaux."""
    records = _validate_snapshot(snapshot)
    groups = _validate_normalization(normalization)
    records_by_id = {record["conversion_row_id"]: record for record in records}
    records_by_client: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        client = record.get("client")
        if isinstance(client, str) and client:
            records_by_client[client].append(record)

    source_sets: dict[str, dict[int, set[str]]] = defaultdict(dict)
    target_sets: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for client, client_records in records_by_client.items():
        source_sets[client] = {
            slot: {
                record["conversion_row_id"]
                for record in client_records
                if old_type in record["type"]
            }
            for slot, old_type in SLOT_TO_TYPE.items()
        }
        targets = {
            target
            for record in client_records
            for target in record["new_type"]
            if isinstance(target, str) and conv_lib.new_type_columns(target)[0]
        }
        target_sets[client] = {
            target: {
                record["conversion_row_id"]
                for record in client_records
                if target in record["new_type"]
            }
            for target in targets
        }

    # Assignations exactes que les ajouts consultants rendraient effectives. Elles sont
    # calculées globalement afin de bloquer deux groupes qui choisiraient la même cible
    # pour des source_sets différents. Une simple cooccurrence de ``type[]`` ne compte
    # jamais comme une assignation.
    consultant_assignments: dict[tuple[str, str], list[tuple[int, set[str]]]] = defaultdict(list)
    for group in groups:
        if group["class"] != "canonicalisable_safe" or len(group["proposed_targets"]) != 1:
            continue
        client = group["client"]
        slot = int(group["slot"])
        target = group["proposed_targets"][0]
        source_ids = source_sets.get(client, {}).get(slot, set())
        target_ids = target_sets.get(client, {}).get(target, set())
        if source_ids and target_ids <= source_ids:
            consultant_assignments[(client, target)].append((slot, source_ids))

    planned_groups: list[dict] = []
    for group in sorted(groups, key=lambda row: (row["client"].casefold(), int(row["slot"]))):
        client = group["client"]
        slot = int(group["slot"])
        old_type = SLOT_TO_TYPE[slot]
        client_records = records_by_client.get(client, [])
        source_ids = source_sets.get(client, {}).get(slot, set())
        company_ids = sorted({
            str(record.get("company_id"))
            for record in client_records
            if record.get("company_id")
        })
        account_ids = sorted({
            str(record.get("account_row_id"))
            for record in client_records
            if record["conversion_row_id"] in source_ids and record.get("account_row_id")
        })

        comparisons = []
        comparison_by_target: dict[str, dict] = {}
        for target in group["proposed_targets"]:
            target_ids = target_sets.get(client, {}).get(target, set())
            comparison = {
                "new_type": target,
                "relation": _relation(source_ids, target_ids),
                "source_row_count": len(source_ids),
                "target_row_count": len(target_ids),
                "intersection_row_count": len(source_ids & target_ids),
                "source_only_conversion_row_ids": sorted(source_ids - target_ids),
                "target_only_conversion_row_ids": sorted(target_ids - source_ids),
                "target_conversion_row_ids": sorted(target_ids),
            }
            comparisons.append(comparison)
            comparison_by_target[target] = comparison

        result = {
            "client": client,
            "slot": slot,
            "old_type": old_type,
            "consultant_class": group["class"],
            "proposed_targets": copy.deepcopy(group["proposed_targets"]),
            "source_conversion_row_ids": sorted(source_ids),
            "source_row_count": len(source_ids),
            "source_account_row_ids": account_ids,
            "source_account_count": len(account_ids),
            "target_comparisons": comparisons,
            "disposition": "blocked",
            "operation_kinds_needed": [],
            "automatic_operations": [],
            "human_data_change_requirements": [],
            "requires_human_data_change": False,
            "diagnostics": [],
        }

        if not client_records:
            result["diagnostics"].append({
                "kind": "client_not_found_in_snapshot",
                "message": "Aucune ligne Supabase ne correspond exactement au client.",
            })
            planned_groups.append(result)
            continue
        if len(company_ids) > 1:
            result["disposition"] = "ambiguous_or_account_specific"
            result["diagnostics"].append({
                "kind": "client_name_collision",
                "company_ids": company_ids,
                "message": "Le nom client désigne plusieurs companies Supabase.",
            })
            planned_groups.append(result)
            continue

        if group["class"] != "canonicalisable_safe":
            if group["class"] == "row_level":
                result["disposition"] = "ambiguous_or_account_specific"
                result["diagnostics"].append({
                    "kind": "exact_row_selectors_required",
                    "message": (
                        "Une correction row-level exige des conversion_row_id explicitement "
                        "validés et, si nécessaire, un sélecteur de compte par cible."
                    ),
                })
            else:
                result["diagnostics"].append({
                    "kind": "class_not_automatically_actionable",
                    "class": group["class"],
                    "message": "Cette classe ne permet pas de fabriquer un write plan sans sélecteurs exacts.",
                })
            planned_groups.append(result)
            continue

        target = group["proposed_targets"][0]
        comparison = comparison_by_target[target]
        target_ids = set(comparison["target_conversion_row_ids"])
        source_only = source_ids - target_ids
        target_only = target_ids - source_ids
        # Collision effective = la même cible est assignée à des slots dont les
        # source_sets diffèrent. Les lignes multi-taggées dans ``type[]`` ne suffisent
        # pas à créer une collision.
        assigned_source_sets: dict[int, set[str]] = {}
        for raw_slot, mapped_target in (snapshot["slot_mapping"].get(client) or {}).items():
            try:
                mapped_slot = int(raw_slot)
            except (TypeError, ValueError) as exc:
                raise PlanningError(f"snapshot Supabase: slot_mapping invalide pour {client!r}") from exc
            if mapped_target == target:
                assigned_source_sets[mapped_slot] = source_sets.get(client, {}).get(mapped_slot, set())
        for assigned_slot, assigned_rows in consultant_assignments.get((client, target), []):
            assigned_source_sets[assigned_slot] = assigned_rows

        colliding_slots = [
            {
                "slot": assigned_slot,
                "old_type": SLOT_TO_TYPE[assigned_slot],
                "source_row_count": len(assigned_rows),
                "source_conversion_row_ids": sorted(assigned_rows),
            }
            for assigned_slot, assigned_rows in sorted(assigned_source_sets.items())
            if assigned_slot != slot and assigned_rows != source_ids
        ]

        if not source_ids:
            result["diagnostics"].append({
                "kind": "empty_source_set",
                "message": "Le slot consultant ne contient aucune conversion_row_id dans le snapshot.",
            })
        if colliding_slots:
            result["diagnostics"].append({
                "kind": "target_would_collide_with_other_slots",
                "new_type": target,
                "colliding_slots": colliding_slots,
                "message": (
                    "La même cible serait effectivement assignée à des slots dont les "
                    "source_sets exacts diffèrent."
                ),
            })

        if source_only:
            result["operation_kinds_needed"].append("add_new_type")
        if target_only:
            # Deux résolutions incompatibles sont possibles. Le planificateur ne choisit
            # jamais entre modifier l'histoire (type[]) et retirer un tag nommé.
            result["operation_kinds_needed"].extend(["remove_new_type", "add_old_type"])
            result["requires_human_data_change"] = True
            result["human_data_change_requirements"].extend([
                _human_change_requirement(
                    "remove_new_type",
                    records_by_id,
                    target_only,
                    new_type=target,
                    reason="target_only_rows_prevent_exact_set_equality",
                    mutually_exclusive_alternative="add_old_type",
                ),
                _human_change_requirement(
                    "add_old_type",
                    records_by_id,
                    target_only,
                    old_type=old_type,
                    reason="target_only_rows_prevent_exact_set_equality",
                    mutually_exclusive_alternative="remove_new_type",
                ),
            ])
            result["diagnostics"].append({
                "kind": "human_choice_required_for_target_only_rows",
                "conversion_row_ids": sorted(target_only),
                "message": (
                    "Décider humainement si ces lignes ont un new_type en trop ou un type "
                    "historique manquant ; aucune des deux mutations n'est auto-planifiée."
                ),
            })

        if comparison["relation"] == "equal" and source_ids and not colliding_slots:
            result["disposition"] = "already_exact"
        elif (
            comparison["relation"] == "target_strict_subset_of_source"
            and source_ids
            and not colliding_slots
        ):
            changes = [
                _add_new_type_change(records_by_id[row_id], target)
                for row_id in sorted(source_only)
            ]
            result["disposition"] = "automatic_add_new_type"
            result["automatic_operations"] = [{
                "operation": "add_new_type",
                "automatic_safe": True,
                "new_type": target,
                "conversion_row_ids": sorted(source_only),
                "record_changes": changes,
                "safety_basis": (
                    "Après l'ajout pur, target_set == source_set du slot demandé et aucune "
                    "autre assignation effective de cette cible ne vise un source_set différent."
                ),
            }]
        else:
            result["disposition"] = (
                "requires_human_data_change"
                if result["requires_human_data_change"]
                else "blocked"
            )

        planned_groups.append(result)

    disposition_counts = Counter(group["disposition"] for group in planned_groups)
    operation_kind_counts = Counter(
        operation
        for group in planned_groups
        for operation in group["operation_kinds_needed"]
    )
    automatic_row_changes = sum(
        len(operation["conversion_row_ids"])
        for group in planned_groups
        for operation in group["automatic_operations"]
    )
    human_requirement_rows = Counter()
    for group in planned_groups:
        for requirement in group["human_data_change_requirements"]:
            human_requirement_rows[requirement["operation"]] += len(requirement["conversion_row_ids"])

    unsafe_groups = sum(
        group["disposition"] not in {"automatic_add_new_type", "already_exact"}
        for group in planned_groups
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "source": {
            "system": "supabase_snapshot",
            "environment": "production",
            "snapshot_exported_at": snapshot.get("exported_at"),
            "snapshot_schema_version": snapshot.get("schema_version"),
            "normalization_schema_version": normalization.get("schema_version"),
        },
        "status": "ready_with_blocked_groups" if unsafe_groups else "ready",
        "stats": {
            "groups": len(planned_groups),
            "unsafe_or_unresolved_groups": unsafe_groups,
            "dispositions": dict(sorted(disposition_counts.items())),
            "operation_kind_groups": dict(sorted(operation_kind_counts.items())),
            "automatic_add_new_type_rows": automatic_row_changes,
            "human_data_change_requirement_rows": dict(sorted(human_requirement_rows.items())),
            "requires_human_data_change_groups": sum(
                group["requires_human_data_change"] for group in planned_groups
            ),
        },
        "groups": planned_groups,
    }


def write_plan(plan: dict, output: Path) -> None:
    """Écrit seulement le plan local, atomiquement."""
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA_VERSION:
        raise PlanningError(f"plan consultants v{SCHEMA_VERSION} attendu")
    if plan.get("read_only") is not True:
        raise PlanningError("refus d'écrire un plan qui n'est pas explicitement read_only")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--normalization", type=Path, default=DEFAULT_NORMALIZATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="valide et affiche les comptes (défaut)")
    mode.add_argument("--write", action="store_true", help="écrit explicitement le plan JSON local")
    args = parser.parse_args(argv)

    try:
        snapshot = _load_json(args.snapshot, "snapshot Supabase")
        normalization = _load_json(args.normalization, "normalisation consultants")
        plan = build_plan(snapshot, normalization)
        stats = plan["stats"]
        dispositions = ", ".join(
            f"{name}={count}" for name, count in stats["dispositions"].items()
        )
        print(
            f"Plan consultants READ-ONLY: {stats['groups']} groupes; {dispositions}; "
            f"{stats['automatic_add_new_type_rows']} ajouts new_type auto-sûrs."
        )
        if args.write:
            write_plan(plan, args.output)
            print(f"Plan local écrit: {args.output}")
        else:
            print("DRY-RUN — aucun fichier écrit; aucune requête Supabase émise.")
        return 0
    except PlanningError as exc:
        print(f"ERREUR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
