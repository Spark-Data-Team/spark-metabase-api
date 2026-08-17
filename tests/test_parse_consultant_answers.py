#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import parse_consultant_answers as pca


def _row(ref, answer):
    return {"ref": ref, "✍️ TA RÉPONSE": answer}


def test_consolidate_accepts_exact_canonical_and_deduplicates():
    decisions, reviews = pca.consolidate([
        _row("Ecopia§0§CONFLIT", "Marketing Qualified Leads"),
        _row("Ecopia§0§PAIRING_AMBIGU", "Marketing Qualified Leads"),
    ])
    assert len(decisions) == 1
    assert decisions[0]["client"] == "Ecopia"
    assert decisions[0]["slot"] == 0
    assert decisions[0]["new_type"] == "Marketing Qualified Leads"
    assert reviews == []


def test_consolidate_rejects_free_text_and_mixed():
    decisions, reviews = pca.consolidate([
        _row("Arrago§1§CONFLIT", "Compte SEO"),
        _row("Rivadouce§1§CONFLIT", "Les deux"),
    ])
    assert decisions == []
    assert {r["reason"] for r in reviews} == {
        "noncanonical_free_text", "mixed_not_migratable"
    }


def test_consolidate_rejects_conflicting_canonical_answers():
    decisions, reviews = pca.consolidate([
        _row("Client§1§CONFLIT", "Leads"),
        _row("Client§1§PAIRING_AMBIGU", "Purchases"),
    ])
    assert decisions == []
    assert reviews[0]["reason"] == "conflicting_canonical_answers"


def test_consolidate_keeps_missing_answer_in_review():
    decisions, reviews = pca.consolidate([_row("Redesk§1§NON_MAPPE_UTILISE", "")])
    assert decisions == []
    assert reviews[0]["reason"] == "missing_answer"


def test_consolidate_does_not_apply_partially_answered_pairing():
    decisions, reviews = pca.consolidate([
        _row("Client§0§CONFLIT", "Leads"),
        _row("Client§0§PAIRING_AMBIGU", ""),
    ])
    assert decisions == []
    assert reviews[0]["reason"] == "incomplete_group"


def test_validate_refs_counts_pairing_duplicates():
    baseline = [_row("A§0§PAIRING_AMBIGU", ""), _row("A§0§PAIRING_AMBIGU", "")]
    pca.validate_refs(list(baseline), baseline)
    try:
        pca.validate_refs(baseline[:1], baseline)
    except ValueError as exc:
        assert "manquantes" in str(exc)
    else:
        raise AssertionError("un doublon de ref manquant doit bloquer")


def test_read_csv_requires_answer_header_for_source(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("ref,answer\nA§0§CONFLIT,Purchases\n", encoding="utf-8")
    try:
        pca.read_csv(path, ("ref", "✍️ TA RÉPONSE"))
    except ValueError as exc:
        assert "TA RÉPONSE" in str(exc)
    else:
        raise AssertionError("un header de réponse altéré doit bloquer")


def test_main_fails_closed_when_baseline_is_missing(tmp_path):
    source = tmp_path / "answers.csv"
    source.write_text("ref,✍️ TA RÉPONSE\nA§0§CONFLIT,Purchases\n", encoding="utf-8")
    try:
        pca.main([str(source), "--baseline", str(tmp_path / "missing.csv"), "--yes"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("une baseline absente doit bloquer avant écriture")
