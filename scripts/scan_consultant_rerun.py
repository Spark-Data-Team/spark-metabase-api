#!/usr/bin/env python3
"""Calcule les COPIES existantes réellement débloquées par les décisions consultants.

Le handoff de visibilité est antérieur à la correction d'attribution des dashboards :
on ne l'utilise donc pas pour cibler. La source des paires original/copie est le tracker,
puis chaque copie est rescannée live pour vérifier qu'elle contient encore le slot
positionnel décidé.

Lecture seule côté Metabase. Écrit uniquement un artefact de périmètre local.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MIG = REPO / "migration"
sys.path.insert(0, str(REPO / "scripts"))

import conv_lib
import special_cards_lib as scl
from migrate_dashboard_full import connect
from final_accounting import embedded_cards, fetch_dict


def decision_slots(decisions: list[dict]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = defaultdict(set)
    for decision in decisions:
        client = str(decision.get("client") or "").strip()
        slot = int(decision.get("slot"))
        new_type = str(decision.get("new_type") or "").strip()
        if not client or not 0 <= slot <= 19 or conv_lib.new_type_columns(new_type)[0] is None:
            raise ValueError(f"décision non validée: {decision!r}")
        out[client].add(slot)
    return dict(out)


def load_special_ids() -> set[int]:
    entries = []
    for path in MIG.glob("tu-generic-*.json"):
        try:
            entries.append(json.loads(path.read_text()))
        except Exception:
            pass
    return scl.replacement_ids(entries)


def matching_cards(
    dashboard: dict,
    wanted_slots: set[int],
    card_lookup,
    special_ids: set[int] | None = None,
) -> list[dict]:
    matches = []
    special_ids = special_ids or set()
    for dc in dashboard.get("dashcards") or dashboard.get("ordered_cards") or []:
        refs = [("card", None, dc.get("card_id"))]
        refs.extend(
            ("series", index, series.get("id") or series.get("card_id"))
            for index, series in enumerate(dc.get("series") or [])
        )
        for location, series_index, cid in refs:
            if not cid or cid in special_ids:
                continue
            card = card_lookup(cid)
            if not isinstance(card, dict):
                continue
            sql, _ = conv_lib.native_and_tags(card)
            old_cols = conv_lib.old_conversion_columns(sql)
            slots = sorted({conv_lib._slot_of(col) for col in old_cols} & wanted_slots)
            if slots:
                match = {
                    "dashcard_id": dc.get("id"),
                    "location": location,
                    "card_id": cid,
                    "card_name": card.get("name"),
                    "slots": slots,
                    "old_columns": sorted(old_cols),
                }
                if series_index is not None:
                    match["series_index"] = series_index
                matches.append(match)
    return matches


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decisions", type=Path, default=MIG / "consultant-decisions.json")
    ap.add_argument("--tracker", type=Path, default=MIG / "conv-migration-tracker.json")
    ap.add_argument("--output", type=Path, default=MIG / "consultant-rerun-scope.json")
    args = ap.parse_args(argv)

    decisions = json.loads(args.decisions.read_text())
    wanted = decision_slots(decisions)
    tracker = json.loads(args.tracker.read_text())
    entries = tracker if isinstance(tracker, list) else tracker.get("entries", [])

    # Déduplique les anciens pilotes et entrées répétées par copy_id ; une copie sans id
    # n'est jamais une cible exécutable.
    candidates = {}
    for entry in entries:
        client = entry.get("client")
        copy_id = entry.get("copy_id")
        if client in wanted and copy_id:
            candidates[int(copy_id)] = entry

    mb = connect()
    special = load_special_ids()
    card_cache = {}

    def card_lookup(card_id):
        if card_id not in card_cache:
            card_cache[card_id] = fetch_dict(mb, f"/api/card/{card_id}")
        return card_cache[card_id]

    scope, inaccessible, untagged = [], [], []
    for copy_id, entry in sorted(candidates.items()):
        try:
            dash = fetch_dict(mb, f"/api/dashboard/{copy_id}")
        except RuntimeError:
            inaccessible.append(copy_id)
            continue
        for card in embedded_cards(dash):
            card_cache.setdefault(int(card["id"]), card)
        if "[conv-2026-06]" not in str(dash.get("name") or ""):
            untagged.append(copy_id)
            continue
        matches = matching_cards(dash, wanted[entry["client"]], card_lookup, special)
        if not matches:
            continue
        scope.append({
            "client": entry["client"],
            "original_id": entry.get("original_id"),
            "copy_id": copy_id,
            "dashboard": entry.get("dashboard") or dash.get("name"),
            "live_name": dash.get("name"),
            "collection_id": dash.get("collection_id"),
            "campaign_tagged": True,
            "decided_slots": sorted(wanted[entry["client"]]),
            "matches": matches,
        })

    if inaccessible:
        raise RuntimeError(f"copies inaccessibles, scope non écrit: {inaccessible}")
    args.output.write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n")
    by_client = defaultdict(int)
    for item in scope:
        by_client[item["client"]] += 1
    print(f"Décisions : {sum(len(v) for v in wanted.values())} slots / {len(wanted)} clients")
    print(f"Copies candidates tracker : {len(candidates)}")
    print(f"Copies avec résidu débloqué : {len(scope)}")
    for client, count in sorted(by_client.items()):
        print(f"  {client}: {count}")
    if untagged:
        print(f"Copies ignorées car non taguées : {untagged}")
    print(f"écrit : {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
