#!/usr/bin/env python3
"""Repolit la visualisation des dashcards pointant vers une carte générée.

La mutation est transactionnelle au mieux des possibilités de l'API Metabase : snapshot
complet avant PUT, contrôle HTTP, relecture des dashcards modifiées et rollback best-effort
si le PUT échoue ou si la relecture diverge.

Usage : python3 scripts/polish_generated_viz.py --copy 25765 --client "Goodiespub" [--yes]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import conv_lib
from conv_paths import reg_dir
from migrate_dashboard_full import _dcs, connect, load_inputs

GEN_COLL = 14115
ALL_OLD = (
    ["CONVERSIONS", "CONVERSION_VALUE"]
    + [f"CONVERSIONS_{n}" for n in range(1, 20)]
    + [f"CONVERSION_{n}_VALUE" for n in range(1, 20)]
)


def _clone(value):
    return json.loads(json.dumps(value))


def dashboard_payload(dashboard: dict) -> dict:
    """Payload réversible construit depuis le snapshot complet."""
    payload = {"dashcards": _clone(_dcs(dashboard))}
    if dashboard.get("tabs"):
        payload["tabs"] = _clone(dashboard["tabs"])
    return payload


def write_snapshot(dashboard_id: int, dashboard: dict, directory: Path | None = None) -> Path:
    """Écrit le dashboard complet, jamais uniquement le sous-ensemble PUT."""
    directory = directory or (reg_dir() / "polish-snapshots")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"dashboard-{dashboard_id}-{stamp}.json"
    path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n")
    return path


def dashboard_divergences(
    expected_dashcards: list[dict], actual_dashboard: dict, changed_ids: set[int]
) -> list[str]:
    """Compare la structure et les visualisations que le PUT devait persister.

    Fonction pure : elle est volontairement stricte sur les ids/card_ids de toutes les
    dashcards et sur ``visualization_settings`` des seules dashcards modifiées.
    """
    if not isinstance(actual_dashboard, dict):
        return ["dashboard inaccessible après PUT"]
    expected = {dc.get("id"): dc for dc in expected_dashcards if dc.get("id") is not None}
    actual = {dc.get("id"): dc for dc in _dcs(actual_dashboard) if dc.get("id") is not None}
    divergences = []
    if set(expected) != set(actual):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        divergences.append(f"dashcards manquantes={missing}, supplémentaires={extra}")
    for dashcard_id, expected_dc in expected.items():
        actual_dc = actual.get(dashcard_id)
        if not actual_dc:
            continue
        if expected_dc.get("card_id") != actual_dc.get("card_id"):
            divergences.append(
                f"dashcard {dashcard_id}: card_id attendu {expected_dc.get('card_id')}, "
                f"relu {actual_dc.get('card_id')}"
            )
        if dashcard_id in changed_ids and (
            (expected_dc.get("visualization_settings") or {})
            != (actual_dc.get("visualization_settings") or {})
        ):
            divergences.append(f"dashcard {dashcard_id}: visualization_settings divergents")
    return divergences


def _http_ok(response) -> bool:
    return getattr(response, "status_code", None) == 200


def rollback_dashboard(mb, dashboard_id: int, snapshot: dict) -> tuple[bool, str]:
    """Rollback best-effort avec contrôle HTTP et relecture, sans masquer l'erreur initiale."""
    try:
        response = mb.put(
            f"/api/dashboard/{dashboard_id}", "raw", json=dashboard_payload(snapshot)
        )
        if not _http_ok(response):
            return False, f"rollback HTTP {getattr(response, 'status_code', '?')}"
        reread = mb.get(f"/api/dashboard/{dashboard_id}")
        original_ids = {
            dc.get("id") for dc in _dcs(snapshot) if dc.get("id") is not None
        }
        divergences = dashboard_divergences(_dcs(snapshot), reread, original_ids)
        if divergences:
            return False, "rollback divergent: " + "; ".join(divergences)
        return True, "rollback vérifié"
    except Exception as exc:  # best-effort : rendre le diagnostic, jamais remplacer l'erreur initiale
        return False, f"rollback impossible: {exc}"


def put_verified(
    mb,
    dashboard_id: int,
    before: dict,
    new_dashcards: list[dict],
    changed_ids: set[int],
    snapshot_directory: Path | None = None,
) -> Path:
    """Snapshot → PUT → relecture; rollback et RuntimeError au moindre doute."""
    snapshot_path = write_snapshot(dashboard_id, before, snapshot_directory)
    payload = {"dashcards": _clone(new_dashcards)}
    if before.get("tabs"):
        payload["tabs"] = _clone(before["tabs"])

    try:
        response = mb.put(f"/api/dashboard/{dashboard_id}", "raw", json=payload)
    except Exception as exc:
        rolled_back, rollback_note = rollback_dashboard(mb, dashboard_id, before)
        raise RuntimeError(
            f"PUT a levé {exc}; {rollback_note}; snapshot {snapshot_path}"
        ) from exc

    if not _http_ok(response):
        rolled_back, rollback_note = rollback_dashboard(mb, dashboard_id, before)
        body = str(getattr(response, "text", ""))[:300]
        raise RuntimeError(
            f"PUT HTTP {getattr(response, 'status_code', '?')}: {body}; "
            f"{rollback_note}; snapshot {snapshot_path}"
        )

    reread = mb.get(f"/api/dashboard/{dashboard_id}")
    divergences = dashboard_divergences(new_dashcards, reread, changed_ids)
    if divergences:
        rolled_back, rollback_note = rollback_dashboard(mb, dashboard_id, before)
        raise RuntimeError(
            "relecture post-PUT divergente: " + "; ".join(divergences)
            + f"; {rollback_note}; snapshot {snapshot_path}"
        )
    return snapshot_path


def build_polish_plan(mb, dashboard: dict, sub_map: dict) -> tuple[list[dict], list[tuple]]:
    """Construit le payload sans mutation du dashboard lu."""
    new_dashcards, polished = [], []
    for dashcard in _dcs(dashboard):
        card_id = dashcard.get("card_id")
        new_dashcard = _clone(dashcard)
        if card_id:
            card = mb.get(f"/api/card/{card_id}")
            if (
                isinstance(card, dict)
                and card.get("collection_id") == GEN_COLL
                and new_dashcard.get("visualization_settings")
            ):
                before = json.dumps(new_dashcard["visualization_settings"])
                after = conv_lib.apply_substitution(before, sub_map)
                if after != before:
                    new_dashcard["visualization_settings"] = json.loads(after)
                    polished.append(
                        (new_dashcard.get("id"), card_id, card.get("name"))
                    )
        new_dashcards.append(new_dashcard)
    return new_dashcards, polished


def execute(args) -> int:
    mb = connect()
    mapping = {int(key): value for key, value in load_inputs()[0].get(args.client, {}).items()}
    sub_map, _ = conv_lib.substitution_map(ALL_OLD, mapping)
    dashboard = mb.get(f"/api/dashboard/{args.copy}")
    if not isinstance(dashboard, dict):
        print(f"⛔ dashboard {args.copy} inaccessible", file=sys.stderr)
        return 1

    new_dashcards, polished = build_polish_plan(mb, dashboard, sub_map)
    print(f"Dashboard {args.copy} — repolissage viz ({len(polished)} dashcards générés) :")
    for _dashcard_id, card_id, name in polished:
        print(f"  {card_id} {str(name)[:50]}")
    if not args.yes:
        print("(DRY-RUN)")
        return 0
    if not polished:
        return 0

    changed_ids = {dashcard_id for dashcard_id, _card_id, _name in polished}
    if None in changed_ids:
        print("⛔ dashcard sans id stable; PUT refusé", file=sys.stderr)
        return 1
    try:
        snapshot = put_verified(
            mb, args.copy, dashboard, new_dashcards, changed_ids
        )
    except RuntimeError as exc:
        print(f"⛔ {exc}", file=sys.stderr)
        return 1
    print(f"PUT {args.copy}: 200 vérifié | snapshot: {snapshot}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--copy", type=int, required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--yes", action="store_true")
    return execute(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
