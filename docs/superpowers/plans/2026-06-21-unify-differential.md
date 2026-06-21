# Unify the differential (check_values) Implementation Plan

> **For agentic workers:** execute task-by-task (TDD, frequent commits). Code-level design lives in `docs/superpowers/specs/2026-06-21-differential-wiring-design.md`.

**Goal:** Add a tested `check_values` value-sequence comparator and have conv-migration delegate its bespoke before/after diff to it (DRY, dogfooded), plus forward `tolerance` through `guarded_apply`.

**Architecture:** `check_values` is a new sibling of `check_differential` in `validate.py` for the flat numeric-multiset shape conv-migration produces (`card_values`/`displayed_cells` → `sorted(round(float(x),4)…)`). conv-migration keeps its upstream series extraction; only the final `before != after` / `b2 == a2` compare is delegated.

**Tech Stack:** Python 3, `spark_metabase_api.validate`, the conv-migration `scripts/migrate_*.py`, pytest (`.venv/bin/python -m pytest`).

## Global Constraints
- Spec: `docs/superpowers/specs/2026-06-21-differential-wiring-design.md`. Branch: `feat/unify-differential`.
- `check_differential` tabular behaviour unchanged; `check_values` is additive. The 148 existing tests stay green.
- conv-migration decision semantics ("À DÉCIDER" / "migrée" / écart-accepté note) preserved exactly.
- No live Metabase in this env → the §3.4 live dry-run dogfood becomes a **fixture equivalence test** (assert `check_values` reproduces the old `before != after` decisions); a real dry-run is a manual follow-up the user runs.
- Commits end with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `check_values` + `guarded_apply` tolerance forwarding
**Files:** Modify `spark_metabase_api/validate.py`; Test `tests/test_validate.py`.
**Produces:** `check_values(target, before, after, mode="monitor", tolerance=0.0) -> List[Finding]` (check="values"); `guarded_apply(..., tolerance=0.0)` forwards tolerance to `check_differential`.

- Behaviour per spec §3.1/§3.2: length mismatch → single `value count` finding; all-numeric → multiset (sorted) element-wise within tolerance, one summary finding; non-numeric → exact ordered equality; `tolerance=0` exact; no diff → one `ok`.
- Tests: order-agnostic equal multiset → ok; length mismatch → finding; numeric drift beyond/within tolerance (identical=error / monitor=warn / within-tol=ok); non-numeric exact; `guarded_apply` with a within-tolerance change emits no differential finding (proves forwarding).
- TDD → `.venv/bin/python -m pytest tests/test_validate.py -q` green → commit.

### Task 2: conv-migration delegates to `check_values`
**Files:** Modify `scripts/migrate_dashboard_reuse.py` (and `migrate_conversions_on_dashboard.py` / `migrate_dashboard_full.py` where the same compare is duplicated); Test `tests/test_conv_diff.py` (new).
**Consumes:** `validate.check_values`.

- Per spec §3.3: replace `before != after` and the mapped `b2 == a2` with `check_values(name, …, mode="monitor" if accept_diffs else "identical")`; map findings → existing decisions ("À DÉCIDER" on error; écart note on accept-diffs warn; else migrate). `series_display_map`/`card_cells` untouched.
- Test (fixture equivalence, no live MB): for representative before/after value-lists, assert the new delegation yields the same decision the old `!=`/`==` would (a "À DÉCIDER" case, a "migrée" case, an `--accept-diffs` note case).
- TDD → full suite green → commit.

### Task 3: whole-branch review + merge
- Adversarial-leaning whole-branch review of `master..feat/unify-differential`; fix Critical/Important findings.
- Full suite green → PR (or direct) → merge to master (admin override, as established) → done.

## Self-Review
- Spec coverage: §3.1 check_values → T1; §3.2 guarded_apply tolerance → T1; §3.3 conv-migration → T2; §3.4 dogfood → T2 (fixture equivalence; live run = manual follow-up, noted). ✓
- No placeholders: code-level detail is in the spec, referenced per task. ✓
