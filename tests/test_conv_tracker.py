#!/usr/bin/env python3
"""Tests de conv_tracker — script autonome. Usage : python3 tests/test_conv_tracker.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import conv_tracker as T


# ─── tag (ancre de campagne) ─────────────────────────────────────────

def test_apply_tag_appends_when_absent():
    assert T.apply_tag("[TEST conv] Home") == "[TEST conv] Home [conv-2026-06]"

def test_apply_tag_idempotent():
    once = T.apply_tag("Home")
    assert T.apply_tag(once) == once  # ne re-tague pas

def test_is_tagged_detects_anchor():
    assert T.is_tagged("Home [conv-2026-06]") is True
    assert T.is_tagged("Home") is False
    assert T.is_tagged(None) is False


# ─── registre / tracker (upsert sans doublon) ────────────────────────

def test_upsert_entry_appends_new():
    tr = T.upsert_entry([], {"copy_id": 25764, "client": "Goodiespub", "status": "migré"})
    assert len(tr) == 1 and tr[0]["copy_id"] == 25764

def test_upsert_entry_merges_existing_no_dup_keeps_order():
    tr = [{"copy_id": 25764, "client": "Goodiespub", "status": "migré", "notes": "x"},
          {"copy_id": 25765, "client": "Goodiespub", "status": "migré"}]
    tr = T.upsert_entry(tr, {"copy_id": 25764, "status": "validé"})
    assert len(tr) == 2                      # pas de doublon
    assert tr[0]["copy_id"] == 25764         # ordre préservé
    assert tr[0]["status"] == "validé"       # champ mis à jour
    assert tr[0]["notes"] == "x"             # autres champs préservés (merge)


# ─── prédicat d'archivage : OPT-IN EXPLICITE obligatoire ─────────────

def test_archivable_requires_explicit_optin_and_known_original():
    tr = [
        {"copy_id": 1, "original_id": 100, "archive_old": True,  "old_archived": False},  # ✅
        {"copy_id": 2, "original_id": 200, "archive_old": False, "old_archived": False},  # pas d'opt-in
        {"copy_id": 3, "original_id": None, "archive_old": True, "old_archived": False},  # pas d'original connu
        {"copy_id": 4, "original_id": 400, "archive_old": True,  "old_archived": True},   # déjà archivé
    ]
    assert T.archivable_originals(tr) == [100]

def test_archivable_empty_when_nothing_opted_in():
    tr = [{"copy_id": 1, "original_id": 100, "status": "validé", "archive_old": False, "old_archived": False}]
    assert T.archivable_originals(tr) == []


# ─── rendu markdown (vue humaine) ────────────────────────────────────

def test_render_markdown_has_row_per_entry():
    tr = [{"client": "Goodiespub", "dashboard": "Home", "copy_id": 25764, "original_id": None,
           "tagged": False, "status": "migré", "archive_old": False, "old_archived": False, "notes": ""}]
    md = T.render_markdown(tr)
    assert "25764" in md and "Goodiespub" in md and "Home" in md

def test_render_markdown_escapes_pipes_in_values():
    # un nom comme "Ecomm | Home" ne doit PAS casser les colonnes de la table
    tr = [{"client": "X", "dashboard": "Ecomm | Home", "copy_id": 1, "original_id": 2,
           "tagged": False, "status": "migré", "archive_old": False, "old_archived": False, "notes": ""}]
    md = T.render_markdown(tr)
    assert "Ecomm \\| Home" in md


def test_merge_trackers_adds_new_and_updates_same_key_no_loss():
    master = [{"client": "A", "original_id": 1, "copy_id": 10, "status": "migré"},
              {"client": "B", "original_id": 2, "copy_id": 20, "status": "migré"}]
    shard = [{"client": "B", "original_id": 2, "copy_id": 20, "status": "validé"},   # même clé -> update
             {"client": "C", "original_id": 3, "copy_id": 30, "status": "migré"}]    # nouveau -> ajout
    out = T.merge_trackers(master, shard)
    assert len(out) == 3                                   # A gardé, B mis à jour, C ajouté
    b = [e for e in out if e["client"] == "B"][0]
    assert b["status"] == "validé"                         # shard l'emporte sur même clé
    assert [e["client"] for e in out] == ["A", "B", "C"]   # ordre maître préservé, nouveaux à la fin

def test_merge_trackers_empty_shard_is_identity():
    master = [{"client": "A", "original_id": 1, "copy_id": 10}]
    assert T.merge_trackers(master, []) == master


TESTS = [test_apply_tag_appends_when_absent, test_apply_tag_idempotent, test_is_tagged_detects_anchor,
         test_merge_trackers_adds_new_and_updates_same_key_no_loss, test_merge_trackers_empty_shard_is_identity,
         test_upsert_entry_appends_new, test_upsert_entry_merges_existing_no_dup_keeps_order,
         test_archivable_requires_explicit_optin_and_known_original, test_archivable_empty_when_nothing_opted_in,
         test_render_markdown_has_row_per_entry, test_render_markdown_escapes_pipes_in_values]


def run():
    failures = 0
    for t in TESTS:
        try:
            t(); print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1; print(f"FAIL  {t.__name__}: {e!r}")
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} tests passés")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    run()
