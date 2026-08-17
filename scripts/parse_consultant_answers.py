#!/usr/bin/env python3
"""Valide le round-trip du handoff consultants avant de surcharger le mapping.

Le CSV autorise du texte libre, mais la migration n'accepte qu'une taxonomie fermée
(`Purchases`, `Leads`, `Custom 1`, ...). Ce parseur est donc conservateur :

- il valide les références contre le handoff strict ;
- il consolide les doublons par (client, slot) ;
- il n'émet que les réponses exactement canoniques et cohérentes ;
- il place tout le reste (prose, mélange, absence, contradiction) dans un rapport de revue.

Dry-run par défaut. Ajouter ``--yes`` pour écrire les deux artefacts JSON.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import conv_lib

REPO = Path(__file__).resolve().parent.parent
MIG = REPO / "migration"
DEFAULT_BASELINE = MIG / "HANDOFF-consultants-CORRIGE.csv"
DEFAULT_OUT = MIG / "consultant-decisions.json"
DEFAULT_REVIEWS = MIG / "consultant-answer-reviews.json"

CANONICAL_NEW_TYPES = tuple(
    list(conv_lib.NAMED_COL) + [f"Custom {i}" for i in range(1, 16)]
)
_CANONICAL_BY_CASEFOLD = {value.casefold(): value for value in CANONICAL_NEW_TYPES}
_MIXED = {"mélange", "melange", "les deux", "mix"}


def read_csv(path: Path, required_headers: tuple[str, ...] = ("ref",)) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        headers = tuple(reader.fieldnames or ())
        missing = [header for header in required_headers if header not in headers]
        if missing:
            raise ValueError(
                f"colonnes requises absentes de {path}: {missing}; présentes={list(headers)}"
            )
        return list(reader)


def parse_ref(ref: str) -> tuple[str, int, str]:
    parts = (ref or "").strip().split("§")
    if len(parts) != 3 or not parts[0].strip() or not parts[2].strip():
        raise ValueError(f"référence invalide: {ref!r}")
    try:
        slot = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"slot invalide dans {ref!r}") from exc
    if not 0 <= slot <= 19:
        raise ValueError(f"slot hors plage dans {ref!r}")
    return parts[0].strip(), slot, parts[2].strip()


def validate_refs(rows: list[dict], baseline_rows: list[dict]) -> None:
    """Exige exactement les mêmes refs, doublons de pairing compris."""
    got = Counter((r.get("ref") or "").strip() for r in rows)
    expected = Counter((r.get("ref") or "").strip() for r in baseline_rows)
    if got != expected:
        missing = list((expected - got).elements())
        extra = list((got - expected).elements())
        raise ValueError(f"refs différentes du handoff strict; manquantes={missing}, ajoutées={extra}")


def canonical_answer(answer: str) -> str | None:
    return _CANONICAL_BY_CASEFOLD.get((answer or "").strip().casefold())


def consolidate(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Retourne (décisions applicables, groupes à revoir)."""
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    malformed: list[dict] = []

    for row_number, row in enumerate(rows, start=2):
        ref = (row.get("ref") or "").strip()
        try:
            client, slot, kind = parse_ref(ref)
        except ValueError as exc:
            malformed.append({
                "row": row_number,
                "ref": ref,
                "reason": "invalid_ref",
                "detail": str(exc),
            })
            continue
        grouped[(client, slot)].append({
            "row": row_number,
            "ref": ref,
            "kind": kind,
            "answer": (row.get("✍️ TA RÉPONSE") or "").strip(),
        })

    decisions: list[dict] = []
    reviews: list[dict] = list(malformed)
    for (client, slot), entries in sorted(grouped.items()):
        answers = [entry["answer"] for entry in entries if entry["answer"]]
        blanks = [entry for entry in entries if not entry["answer"]]
        canonical = {canonical_answer(answer) for answer in answers}
        canonical.discard(None)
        mixed = [answer for answer in answers if answer.casefold() in _MIXED]
        noncanonical = [
            answer for answer in answers
            if canonical_answer(answer) is None and answer.casefold() not in _MIXED
        ]

        if len(canonical) == 1 and not blanks and not mixed and not noncanonical:
            new_type = next(iter(canonical))
            decisions.append({
                "client": client,
                "slot": slot,
                "new_type": new_type,
                "raw": sorted(set(answers)),
                "refs": sorted({entry["ref"] for entry in entries}),
            })
            continue

        if not answers:
            reason = "missing_answer"
        elif blanks:
            reason = "incomplete_group"
        elif mixed:
            reason = "mixed_not_migratable"
        elif len(canonical) > 1:
            reason = "conflicting_canonical_answers"
        elif noncanonical:
            reason = "noncanonical_free_text"
        else:
            reason = "incomplete_or_conflicting_group"
        reviews.append({
            "client": client,
            "slot": slot,
            "reason": reason,
            "answers": sorted(set(answers)),
            "refs": sorted({entry["ref"] for entry in entries}),
            "rows": [entry["row"] for entry in entries],
        })

    return decisions, reviews


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.PRE-CONSULTANTS-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--reviews-output", type=Path, default=DEFAULT_REVIEWS)
    ap.add_argument("--yes", action="store_true", help="écrit les artefacts (dry-run sinon)")
    args = ap.parse_args(argv)

    if not args.baseline.is_file():
        ap.error(f"baseline stricte introuvable : {args.baseline}")
    rows = read_csv(args.source, ("ref", "✍️ TA RÉPONSE"))
    validate_refs(rows, read_csv(args.baseline, ("ref",)))
    decisions, reviews = consolidate(rows)
    nclients = len({d["client"] for d in decisions})

    print(f"CSV validé : {len(rows)} lignes")
    print(f"Décisions canoniques : {len(decisions)} / {nclients} clients")
    for decision in decisions:
        print(f"  {decision['client']} slot {decision['slot']} -> {decision['new_type']}")
    print(f"Groupes conservés en revue : {len(reviews)}")

    if not args.yes:
        print("(DRY-RUN — aucun fichier écrit.)")
        return 0

    for path in (args.output, args.reviews_output):
        backup = _backup(path)
        if backup:
            print(f"backup : {backup}")
    args.output.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n")
    args.reviews_output.write_text(json.dumps(reviews, ensure_ascii=False, indent=2) + "\n")
    print(f"écrit : {args.output}")
    print(f"écrit : {args.reviews_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
