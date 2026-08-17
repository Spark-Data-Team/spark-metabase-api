#!/usr/bin/env python3
"""Orchestre la migration copy-first d'une liste de dashboards d'un client.

Le mode par défaut est un vrai dry-run : il valide uniquement les entrées locales et
n'ouvre aucune session Metabase. ``--yes`` déclenche ensuite un préflight complet de
tous les dashboards source avant de créer la première copie. Le pipeline est fail-fast
et une copie n'est marquée ``migré`` qu'après contrôle de l'absence de résidus.
``--preflight-live`` exécute ce même préflight en lecture seule, sans tracker ni mutation
métier (un POST d'authentification peut être nécessaire), et peut écrire son rapport
déterministe avec ``--preflight-output``.

Usage :
  python3 scripts/migrate_client.py --client "Father and Sons" \
      --dashboards 11804,15963 --test-collection 14016
  python3 scripts/migrate_client.py --client "Father and Sons" \
      --dashboards 11804,15963 --preflight-live --preflight-output /tmp/preflight.json
  # ajouter --yes pour appliquer
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from archive_collections import connect_resilient
import bascule_lib
import conv_lib
import conv_tracker
from generate_fallback import load_special_ids
from migrate_dashboard_full import _dcs, load_inputs
from reorg_phase1 import _load_env
from special_cards_lib import SPECIAL_OLD_IDS
from spark_metabase_api import Metabase_API

PY = str(REPO / ".venv" / "bin" / "python")

_SESSION_OUTPUT_RE = re.compile(
    r"(?im)^.*(?:authenticated successfully.*session id|session id\s*(?:is)?\s*:).*$"
)


STEPS = (
    ("ensure_client_default.py", lambda _original: []),
    ("migrate_dashboard_reuse.py", lambda original: [
        "--source", str(original), "--planned-temporal-unit",
    ]),
    ("swap_tables.py", lambda _original: []),
    ("deploy_special_cards.py", lambda _original: []),
    ("bascule_time_filter.py", lambda _original: ["--auto-prepare"]),
    ("generate_fallback.py", lambda _original: []),
    ("polish_generated_viz.py", lambda _original: []),
)


class GetOnlyMetabase:
    """Façade minimale : le préflight ne reçoit matériellement aucune méthode de mutation."""

    def __init__(self, client):
        self._client = client

    def get(self, endpoint, *args, **kwargs):
        client = self._client
        # Le wrapper historique sonde /api/user/current avant chaque GET. Après une
        # authentification réussie, sa session HTTP peut lire directement les endpoints
        # métier sans ce round-trip répété. Les doubles de tests gardent le chemin public.
        if all(hasattr(client, attr) for attr in ("_http", "domain", "header")):
            response = client._http.get(
                client.domain + endpoint,
                headers=client.header,
                *args,
                **kwargs,
            )
            if response.status_code not in (401, 403):
                response.raise_for_status()
                return response.json()
        return client.get(endpoint, *args, **kwargs)


def connect_read_only() -> tuple[GetOnlyMetabase, str]:
    """Session existante d'abord, puis authentification standard si nécessaire.

    Le fallback peut effectuer le POST technique ``/api/session``. Sa sortie est capturée
    car le client historique affiche l'id de session; aucun secret ne doit polluer le rapport.
    La façade retournée n'expose ensuite que ``GET``.
    """
    env = _load_env()
    domain = str(env.get("METABASE_DOMAIN") or "").strip()
    session_id = str(env.get("METABASE_SESSION_ID") or "").strip()
    if domain and session_id:
        try:
            with redirect_stdout(io.StringIO()):
                client = Metabase_API(domain=domain, session_id=session_id)
            return GetOnlyMetabase(client), "existing_session"
        except Exception:
            pass

    # Auth standard du repo. Le POST /api/session est autorisé; aucune opération métier
    # n'est possible via la façade GetOnlyMetabase rendue au préflight.
    try:
        with redirect_stdout(io.StringIO()):
            client = connect_resilient()
    except (Exception, SystemExit) as exc:
        raise RuntimeError(
            "authentification Metabase impossible pour le preflight"
        ) from exc
    return GetOnlyMetabase(client), "credential_fallback"


def run_step(script, copy, client, extra, yes=True):
    """Exécute une étape et renvoie son diagnostic court et son succès.

    ``yes`` reste injectable pour les tests/appels directs, mais l'orchestrateur
    n'appelle jamais cette fonction en dry-run.
    """
    cmd = [PY, str(REPO / "scripts" / script), "--copy", str(copy), "--client", client] + extra
    if yes:
        cmd.append("--yes")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        partial = redact_sensitive_output("\n".join(x for x in (stdout, stderr) if x))
        tail = "\n".join(partial.strip().splitlines()[-3:])
        if tail:
            tail += "\n"
        return tail + "⛔ étape interrompue après 1800 s (timeout)", False
    safe_stdout = redact_sensitive_output(out.stdout or "")
    safe_stderr = redact_sensitive_output(out.stderr or "")
    tail = "\n".join(safe_stdout.strip().splitlines()[-4:])
    if out.returncode != 0 and safe_stderr.strip():
        if tail:
            tail += "\n"
        tail += "  [stderr] " + "\n  [stderr] ".join(
            safe_stderr.strip().splitlines()[-3:]
        )
    return tail, out.returncode == 0


def redact_sensitive_output(value: str) -> str:
    """Supprime les ids de session que le client historique imprime sur stdout."""
    return _SESSION_OUTPUT_RE.sub("[authentification Metabase réussie — session masquée]", value)


def _parse_originals(raw: str) -> list[int]:
    try:
        originals = [int(value.strip()) for value in raw.split(",") if value.strip()]
    except ValueError as exc:
        raise ValueError("--dashboards doit contenir uniquement des ids entiers") from exc
    if not originals:
        raise ValueError("--dashboards ne contient aucun id")
    if len(set(originals)) != len(originals):
        raise ValueError("un même dashboard original est demandé plusieurs fois")
    return originals


def _has_original(tracker: list[dict], original_id: int) -> bool:
    """Égalité tolérante aux anciens trackers ayant sérialisé les ids en texte."""
    for entry in tracker:
        try:
            if int(entry.get("original_id")) == original_id:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _save_tracker(tracker: list[dict]) -> None:
    conv_tracker.save(tracker)
    conv_tracker.render_to_file(tracker)


def _update_tracker(tracker: list[dict], copy_id: int, **changes) -> list[dict]:
    tracker = conv_tracker.upsert_entry(tracker, {"copy_id": copy_id, **changes})
    _save_tracker(tracker)
    return tracker


def _slot_of(column: str) -> int | None:
    if column in ("CONVERSIONS", "CONVERSION_VALUE"):
        return 0
    match = re.search(r"(\d+)", column)
    return int(match.group(1)) if match else None


def _mapping_diagnostic(column: str, client_mapping: dict[int, str]) -> dict:
    slot = _slot_of(column)
    new_type = client_mapping.get(slot) if slot is not None else None
    if new_type == conv_lib.CONFLICT:
        state = "CONFLICT"
    elif not new_type or new_type == conv_lib.UNMAPPED:
        state = "UNMAPPED"
    else:
        count_column, value_column = conv_lib.new_type_columns(new_type)
        if not count_column:
            state = "UNMAPPED"
        else:
            state = "USABLE"
        target = (
            value_column
            if column == "CONVERSION_VALUE" or column.endswith("_VALUE")
            else count_column
        )
        return {
            "column": column,
            "slot": slot,
            "mapping": state,
            "new_type": new_type,
            "target_column": target,
        }
    return {
        "column": column,
        "slot": slot,
        "mapping": state,
        "new_type": new_type,
        "target_column": None,
    }


def analyze_card_coverage(card_id: int, card: dict, client_mapping: dict[int, str]) -> dict:
    """Prouve (ou refuse) un chemin structurel vers l'Iron Law pour une carte.

    La preuve reproduit le dernier filet du pipeline : substitution des slots utilisables,
    puis cascade SELECT-aware des slots non mappés. Un mapping count-only utilisé comme
    valeur reste bloquant, conformément au garde-fou de ``generate_fallback``.
    """
    result = {
        "card_id": card_id,
        "coverage_status": "PROVEN",
        "path": "NO_POSITIONAL_SLOTS",
        "old_columns": [],
        "slots": [],
        "blocking_reasons": [],
        "post_fallback_residuals": [],
    }
    if card_id in SPECIAL_OLD_IDS:
        result.update({"coverage_status": "SPECIAL", "path": "DEPLOY_SPECIAL_CARD"})
        return result

    sql, _tags = conv_lib.native_and_tags(card)
    dataset_query = card.get("dataset_query") or {}
    scan_text = sql or json.dumps(dataset_query, ensure_ascii=False)
    old_columns = sorted(conv_lib.old_conversion_columns(scan_text))
    result["old_columns"] = old_columns

    # Une référence opaque peut cacher précisément les colonnes que le préflight cherche
    # à inventorier. On ne conclut jamais « couvert » à partir d'un contenu invisible.
    if sql and conv_lib.has_opaque_refs(sql):
        result.update({
            "coverage_status": "BLOCKED",
            "path": "OPAQUE_REFERENCE",
            "blocking_reasons": ["OPAQUE_REFERENCE_UNPROVABLE"],
        })
        return result
    if not old_columns:
        return result

    result["slots"] = [_mapping_diagnostic(column, client_mapping) for column in old_columns]
    if not sql:
        result.update({
            "coverage_status": "BLOCKED",
            "path": "UNSUPPORTED_STRUCTURED_QUERY",
            "blocking_reasons": ["POSITIONAL_SLOTS_OUTSIDE_NATIVE_SQL"],
        })
        return result

    substitution, unmapped = conv_lib.substitution_map(old_columns, client_mapping)
    lossy_values = conv_lib.lossy_count_only_value_columns(unmapped, client_mapping)
    if lossy_values:
        result.update({
            "coverage_status": "BLOCKED",
            "path": "COUNT_ONLY_VALUE",
            "blocking_reasons": [f"COUNT_ONLY_VALUE_NO_TARGET:{column}" for column in lossy_values],
        })
        return result
    if not substitution:
        states = sorted({slot["mapping"] for slot in result["slots"]})
        result.update({
            "coverage_status": "BLOCKED",
            "path": "NO_USABLE_MAPPING",
            "blocking_reasons": [f"NO_USABLE_MAPPING:{state}" for state in states],
        })
        return result

    transformed = conv_lib.apply_substitution(sql, substitution)
    transformed = conv_lib.drop_conversion_selects(transformed)
    remaining = sorted(conv_lib.old_conversion_columns(transformed))
    result["post_fallback_residuals"] = remaining
    if remaining:
        result.update({
            "coverage_status": "BLOCKED",
            "path": "UNSAFE_PARTIAL_DROP",
            "blocking_reasons": ["POSITIONAL_RESIDUAL_AFTER_FALLBACK"],
        })
    elif unmapped:
        result.update({
            "coverage_status": "PARTIAL_PROVEN",
            "path": "SUBSTITUTE_AND_SAFE_DROP",
        })
    else:
        result["path"] = "DIRECT_SUBSTITUTION"
    return result


def _source_card_references(dashboard: dict) -> list[dict]:
    """Références primaires et séries, avec leur position pour un diagnostic actionnable."""
    references = []
    for dashcard in _dcs(dashboard):
        dashcard_id = dashcard.get("id")
        card_id = dashcard.get("card_id") or (dashcard.get("card") or {}).get("id")
        if card_id:
            references.append({
                "dashcard_id": dashcard_id,
                "reference": "primary",
                "card_id": int(card_id),
            })
        for series in dashcard.get("series") or []:
            series_id = series.get("id") or series.get("card_id") or (series.get("card") or {}).get("id")
            if series_id:
                references.append({
                    "dashcard_id": dashcard_id,
                    "reference": "series",
                    "card_id": int(series_id),
                })
    return references


def preflight_sources(
    mb, originals: list[int], client_mapping: dict[int, str]
) -> tuple[dict[int, dict], list[dict]]:
    """Lit toutes les sources/cartes et prouve leur couverture avant toute copie."""
    sources, diagnostics, card_cache = {}, [], {}
    for original in originals:
        try:
            dashboard = mb.get(f"/api/dashboard/{original}")
        except Exception:
            dashboard = None
        if not isinstance(dashboard, dict) or not dashboard.get("id"):
            diagnostics.append({
                "dashboard_id": original,
                "dashcard_id": None,
                "reference": "dashboard",
                "card_id": None,
                "coverage_status": "BLOCKED",
                "path": "DASHBOARD_INACCESSIBLE",
                "old_columns": [],
                "slots": [],
                "blocking_reasons": ["DASHBOARD_INACCESSIBLE"],
                "post_fallback_residuals": [],
            })
            continue
        sources[original] = dashboard

    # Important : les dashboards du batch sont tous lus avant les cartes et aucune mutation
    # n'est possible dans cette fonction. Toute carte inaccessible devient un BLOCKED explicite.
    for original in originals:
        if original not in sources:
            continue
        try:
            references = _source_card_references(sources[original])
        except (TypeError, ValueError):
            diagnostics.append({
                "dashboard_id": original,
                "dashcard_id": None,
                "reference": "dashboard",
                "card_id": None,
                "coverage_status": "BLOCKED",
                "path": "CARD_REFERENCE_INVALID",
                "old_columns": [],
                "slots": [],
                "blocking_reasons": ["CARD_REFERENCE_INVALID"],
                "post_fallback_residuals": [],
            })
            continue
        for reference in references:
            card_id = reference["card_id"]
            if card_id not in card_cache:
                try:
                    card_cache[card_id] = mb.get(f"/api/card/{card_id}")
                except Exception:
                    card_cache[card_id] = None
            card = card_cache[card_id]
            location = {"dashboard_id": original, **reference}
            if (
                not isinstance(card, dict)
                or ("dataset_query" not in card and "legacy_query" not in card)
            ):
                diagnostics.append({
                    **location,
                    "coverage_status": "BLOCKED",
                    "path": "CARD_INACCESSIBLE",
                    "old_columns": [],
                    "slots": [],
                    "blocking_reasons": ["CARD_INACCESSIBLE"],
                    "post_fallback_residuals": [],
                })
                continue
            coverage = analyze_card_coverage(card_id, card, client_mapping)
            # Aucun step du pipeline ne repointe les cartes de série. Une substitution
            # théoriquement possible n'est donc pas un chemin exécutable aujourd'hui.
            if (
                reference["reference"] == "series"
                and coverage["old_columns"]
                and coverage["coverage_status"] != "SPECIAL"
            ):
                coverage.update({
                    "coverage_status": "BLOCKED",
                    "path": "SERIES_NOT_AUTOMIGRATED",
                    "blocking_reasons": ["POSITIONAL_SERIES_REQUIRES_DEDICATED_MIGRATION"],
                })
            diagnostics.append({**location, **coverage})
    return sources, diagnostics


def build_preflight_report(
    client: str,
    originals: list[int],
    diagnostics: list[dict],
    fatal_error: str | None = None,
    authentication_mode: str = "unknown",
) -> dict:
    """Rapport déterministe et sérialisable du préflight live."""
    def sort_key(item):
        reference_order = {"primary": 0, "series": 1}
        return (
            int(item.get("dashboard_id") or -1),
            int(item.get("dashcard_id") or -1),
            reference_order.get(item.get("reference"), 9),
            int(item.get("card_id") or -1),
        )

    ordered = sorted((_clone_diagnostic(item) for item in diagnostics), key=sort_key)
    blocked = [item for item in ordered if item.get("coverage_status") == "BLOCKED"]
    status_counts = {}
    mapping_counts = {"USABLE": 0, "UNMAPPED": 0, "CONFLICT": 0}
    for item in ordered:
        status = item.get("coverage_status") or "UNKNOWN"
        status_counts[status] = status_counts.get(status, 0) + 1
        for slot in item.get("slots") or []:
            mapping_state = slot.get("mapping")
            if mapping_state in mapping_counts:
                mapping_counts[mapping_state] += 1
    ready = not fatal_error and not blocked
    report = {
        "schema_version": 1,
        "client": client,
        "authentication_mode": authentication_mode,
        "originals": list(originals),
        "result": "READY" if ready else "BLOCKED",
        "summary": {
            "dashboards": len(originals),
            "card_references": len(ordered),
            "blocked_references": len(blocked),
            "coverage_statuses": dict(sorted(status_counts.items())),
            "mapping_columns": mapping_counts,
        },
        "diagnostics": ordered,
    }
    if fatal_error:
        report["fatal_error"] = fatal_error
    return report


def _clone_diagnostic(item: dict) -> dict:
    """Copie JSON profonde pour que tri/sérialisation ne mutent pas le préflight."""
    return json.loads(json.dumps(item, ensure_ascii=False))


def serialize_preflight_report(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_preflight_report(report: dict, output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_preflight_report(report))
    return path


def run_live_preflight(
    client: str,
    originals: list[int],
    mapping: dict[int, str],
    output: str | Path | None = None,
) -> int:
    """Lecture métier GET-only, sans tracker : rapport puis READY/BLOCKED."""
    authentication_mode = "unavailable"
    try:
        mb, authentication_mode = connect_read_only()
        _sources, diagnostics = preflight_sources(mb, originals, mapping)
        report = build_preflight_report(
            client,
            originals,
            diagnostics,
            authentication_mode=authentication_mode,
        )
    except Exception as exc:
        report = build_preflight_report(
            client,
            originals,
            [],
            fatal_error=f"{type(exc).__name__}: {exc}",
            authentication_mode=authentication_mode,
        )
    serialized = serialize_preflight_report(report)
    print(serialized, end="")
    if output is not None:
        try:
            path = write_preflight_report(report, output)
        except OSError as exc:
            print(f"⛔ écriture rapport impossible: {exc}", file=sys.stderr)
            return 1
        print(f"Rapport local: {path}", file=sys.stderr)
    return 0 if report["result"] == "READY" else 1


def find_residuals(mb, dashboard: dict, special_ids: set[int] | None = None) -> list[str]:
    """Retourne les références encore positionnelles, y compris dans les séries.

    Une carte inaccessible est elle aussi un échec de contrôle : l'absence de résidu
    ne doit jamais être déduite d'une lecture incomplète.
    """
    special_ids = set(special_ids or ())
    references: list[tuple[str, int]] = []
    for dashcard in _dcs(dashboard):
        card_id = dashcard.get("card_id") or (dashcard.get("card") or {}).get("id")
        if card_id:
            references.append((f"dashcard {dashcard.get('id')}", card_id))
        for series in dashcard.get("series") or []:
            series_id = series.get("id") or series.get("card_id")
            if series_id:
                references.append((f"série de dashcard {dashcard.get('id')}", series_id))

    residuals, seen = [], set()
    for location, card_id in references:
        key = (location, card_id)
        if key in seen or card_id in special_ids:
            continue
        seen.add(key)
        card = mb.get(f"/api/card/{card_id}")
        if not isinstance(card, dict):
            residuals.append(f"{location}: carte #{card_id} inaccessible")
            continue
        sql, _ = conv_lib.native_and_tags(card)
        old_columns = sorted(conv_lib.old_conversion_columns(sql))
        if old_columns:
            residuals.append(f"{location}: carte #{card_id} ({', '.join(old_columns)})")
    return residuals


def verify_pipeline(
    mb,
    copy_id: int,
    expected_client: str | None = None,
    *,
    require_account_default_cleared: bool = False,
) -> tuple[bool, str]:
    dashboard = mb.get(f"/api/dashboard/{copy_id}")
    if not isinstance(dashboard, dict):
        return False, f"dashboard copie #{copy_id} inaccessible au contrôle final"
    if expected_client:
        from ensure_client_default import account_defaults, client_defaults
        defaults = client_defaults(dashboard)
        wrong = [
            item for item in defaults if item.get("default") != [expected_client]
        ]
        if wrong:
            return False, (
                f"défaut Client incorrect: attendu {[expected_client]!r}, "
                f"relu {[item.get('default') for item in wrong]!r}"
            )
        if require_account_default_cleared:
            wrong_accounts = [
                item for item in account_defaults(dashboard)
                if item.get("default") is not None
            ]
            if wrong_accounts:
                return False, (
                    "défaut Account incorrect: attendu None, "
                    f"relu {[item.get('default') for item in wrong_accounts]!r}"
                )
    time_issues = find_time_filter_issues(mb, dashboard)
    if time_issues:
        return False, "filtre temps incohérent: " + "; ".join(time_issues)
    residuals = find_residuals(mb, dashboard, load_special_ids())
    if residuals:
        return False, "résidus ancien système: " + "; ".join(residuals)
    return True, "pipeline terminé; contrôle final sans résidu"


def find_time_filter_issues(mb, dashboard: dict) -> list[str]:
    """Vérifie la bascule globale et le câblage des cartes sur le temporal-unit."""
    old = bascule_lib.find_time_param(dashboard)
    if old is not None:
        return [f"ancien paramètre Time period encore présent ({old.get('id')})"]

    temporal_parameters = {
        parameter.get("id")
        for parameter in dashboard.get("parameters") or []
        if parameter.get("type") == "temporal-unit"
        and (
            str(parameter.get("slug") or "").casefold() == "time_period"
            or str(parameter.get("name") or "").strip().casefold() == "time period"
        )
    }
    temporal_parameters.discard(None)
    if not temporal_parameters:
        return []

    issues = []
    for dashcard in _dcs(dashboard):
        card_id = dashcard.get("card_id")
        if not card_id:
            continue
        wired = False
        for mapping in dashcard.get("parameter_mappings") or []:
            if mapping.get("parameter_id") not in temporal_parameters:
                continue
            target = mapping.get("target")
            try:
                is_time_target = (
                    target[1][0] == "template-tag" and target[1][1] == "time_period"
                )
            except Exception:
                is_time_target = False
            if is_time_target and mapping.get("card_id", card_id) == card_id:
                wired = True
        card = mb.get(f"/api/card/{card_id}")
        if not isinstance(card, dict):
            issues.append(f"dashcard {dashcard.get('id')}: carte #{card_id} inaccessible")
            continue
        _sql, tags = conv_lib.native_and_tags(card)
        tag_type = ((tags.get("time_period") or {}).get("type"))
        if tag_type == "temporal-unit" and not wired:
            issues.append(
                f"dashcard {dashcard.get('id')}: carte #{card_id} temporal-unit non câblée"
            )
        elif tag_type != "temporal-unit" and wired:
            issues.append(
                f"dashcard {dashcard.get('id')}: carte #{card_id} type {tag_type!r} "
                "câblée au temporal-unit"
            )
    return issues


def execute(args) -> int:
    """Exécute l'orchestration. Retourne un code shell, sans masquer les échecs."""
    preflight_live = bool(getattr(args, "preflight_live", False))
    preflight_output = getattr(args, "preflight_output", None)
    if preflight_output and not preflight_live:
        print("⛔ --preflight-output requiert --preflight-live", file=sys.stderr)
        return 2
    if preflight_live and bool(args.yes):
        # Le parser CLI l'interdit déjà; garde-fou pour les appels programmatiques/tests.
        print("⛔ --preflight-live et --yes sont mutuellement exclusifs", file=sys.stderr)
        return 2
    try:
        originals = _parse_originals(args.dashboards)
    except ValueError as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 2

    # Préflight local : mapping Supabase exporté + unicité du tracker. Il se fait même
    # en dry-run, mais ne provoque aucune connexion ni écriture distante.
    try:
        mapping_all, _index = load_inputs()
    except Exception as exc:
        print(f"⛔ mapping indisponible: {exc}", file=sys.stderr)
        return 1
    raw_mapping = mapping_all.get(args.client, {})
    if not raw_mapping:
        print(f"⛔ aucun mapping pour {args.client!r}", file=sys.stderr)
        return 1
    try:
        mapping = {int(slot): new_type for slot, new_type in raw_mapping.items()}
    except (TypeError, ValueError) as exc:
        print(f"⛔ mapping invalide pour {args.client!r}: {exc}", file=sys.stderr)
        return 1

    if preflight_live:
        # Branche dédiée avant tout accès au tracker : session existante ou POST d'auth,
        # puis GET métier uniquement. Aucun chemin ne rejoint les mutations.
        return run_live_preflight(
            args.client, originals, mapping, output=preflight_output
        )

    tracker = conv_tracker.load()
    duplicates = [original for original in originals if _has_original(tracker, original)]
    if duplicates:
        print(
            "⛔ original(aux) déjà présent(s) dans le tracker, aucune copie créée: "
            + ", ".join(map(str, duplicates)),
            file=sys.stderr,
        )
        return 1

    if not args.yes:
        print(
            f"DRY-RUN — {len(originals)} dashboard(s) pour {args.client}; "
            "aucune connexion, copie ou écriture Metabase/tracker."
        )
        print(
            "Sources à préflighter en lecture seule avec --preflight-live: "
            + ", ".join(map(str, originals))
        )
        return 0

    # Le client historique imprime encore l'id de session lors de l'authentification.
    # L'orchestrateur ne doit jamais le faire remonter dans ses logs ou le tracker.
    with redirect_stdout(io.StringIO()):
        mb = connect_resilient()
    try:
        sources, coverage = preflight_sources(mb, originals, mapping)
    except RuntimeError as exc:
        print(f"⛔ préflight source: {exc}", file=sys.stderr)
        return 1
    relevant_coverage = [
        item for item in coverage
        if item["coverage_status"] != "PROVEN" or item["old_columns"]
    ]
    if relevant_coverage:
        print("Préflight couverture cartes (JSON structuré) :")
        print(json.dumps(relevant_coverage, ensure_ascii=False, indent=2))
    blocked = [item for item in coverage if item["coverage_status"] == "BLOCKED"]
    if blocked:
        print(
            f"⛔ préflight Iron Law: {len(blocked)} référence(s) sans chemin prouvé; "
            "aucune copie créée",
            file=sys.stderr,
        )
        return 1

    # Tous les préflights ont réussi. À partir d'ici seulement, les copies sont autorisées.
    for original in originals:
        source = sources[original]
        name = source.get("name", str(original))
        copy_name = conv_tracker.apply_tag(f"{args.name_prefix} {name}")
        deep = conv_lib.has_dashboard_questions(source)
        copied = mb.post(
            f"/api/dashboard/{original}/copy",
            json={
                "name": copy_name,
                "collection_id": args.test_collection,
                "is_deep_copy": deep,
            },
        )
        copy_id = copied.get("id") if isinstance(copied, dict) else None
        print(
            f"\n### {original} «{name}» → copie {copy_id}"
            + ("  [deep copy: Dashboard Questions]" if deep else "")
        )
        if not copy_id:
            print("  ⛔ copie échouée; pipeline arrêté", file=sys.stderr)
            return 1

        tracker = conv_tracker.upsert_entry(tracker, {
            "client": args.client,
            "dashboard": name,
            "copy_id": copy_id,
            "original_id": original,
            "tagged": True,
            "status": "en cours",
            "archive_old": False,
            "old_archived": False,
            "notes": "pipeline démarré",
        })
        _save_tracker(tracker)

        for script, extra_factory in STEPS:
            extra = extra_factory(original)
            if script == "ensure_client_default.py" and args.clear_account_default:
                extra.append("--clear-account-default")
            tail, ok = run_step(script, copy_id, args.client, extra, yes=True)
            print(f"  --- {script} {'' if ok else '(exit≠0)'}")
            for line in tail.splitlines():
                print(f"      {line}")
            if not ok:
                note = f"pipeline arrêté à {script}"
                if tail:
                    note += ": " + " | ".join(tail.splitlines())
                tracker = _update_tracker(
                    tracker, copy_id, status="échec", notes=note[:2000]
                )
                return 1

        ok, note = verify_pipeline(
            mb,
            copy_id,
            args.client,
            require_account_default_cleared=args.clear_account_default,
        )
        if not ok:
            print(f"  ⛔ {note}", file=sys.stderr)
            tracker = _update_tracker(
                tracker, copy_id, status="résiduel", notes=note[:2000]
            )
            return 1

        tracker = _update_tracker(
            tracker, copy_id, status="migré", notes=note
        )
        print("  ✅ pipeline terminé et contrôlé sans résidu")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--client", required=True)
    parser.add_argument("--dashboards", required=True, help="ids ORIGINAUX séparés par virgules")
    parser.add_argument("--test-collection", type=int, default=14016)
    parser.add_argument("--name-prefix", default="[TEST conv]")
    parser.add_argument(
        "--clear-account-default",
        action="store_true",
        help="vide explicitement les defaults Account sur la copie avant validation",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--yes", action="store_true", help="applique le pipeline de migration")
    mode.add_argument(
        "--preflight-live",
        action="store_true",
        help="préflight distant en lecture seule, sans copie ni écriture tracker",
    )
    parser.add_argument(
        "--preflight-output",
        help="écrit localement le rapport JSON déterministe (avec --preflight-live)",
    )
    return parser


def main() -> int:
    return execute(build_parser().parse_args())


if __name__ == "__main__":
    sys.exit(main())
