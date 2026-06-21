# Unify the differential — `check_values` + dogfood conv-migration

- **Date**: 2026-06-21
- **Status**: Proposed (revised after reading the real conv-migration comparison code)
- **Author**: Louis + Claude

## 1. Context & motivation

The merged validation layer (`spark_metabase_api/validate.py`, PR #16) ships a tabular
`check_differential` (rows-of-dicts → row count / column set / per-column sums) that is **not wired
into any real flow**. The natural consumer is the active **conversion-migration** campaign, which has
its own **bespoke, duplicated, untested** before/after diff in `migrate_dashboard_reuse.py`
(and `migrate_conversions_on_dashboard.py` / `migrate_dashboard_full.py`).

**Key finding (from reading the code):** conv-migration does **not** compare tables. `card_values` /
`displayed_cells` return `sorted(round(float(x), 4) …)` — a **sorted multiset of numeric values**. Its
comparison is `before != after` (and `b2 == a2` for the series-mapped case): "the same bag of numbers
before and after". The series mapping (`series_display_map`) and column extraction happen **upstream**
in `card_cells`; by the time the diff runs, there are no named columns or rows to align.

So a tabular `column_map`/cell-by-cell differ does **not** fit. The right shared primitive is a
**numeric value-sequence comparison**. This spec adds that primitive (`check_values`), tested, and has
conv-migration delegate its hand-rolled compare to it — one tested diff, dogfooded on the live campaign,
DRY, no weaker than today.

## 2. Goals / non-goals

**Goals**
- Add `check_values` to `validate.py`: compare two numeric value-sequences (the sorted/rounded multiset
  convention), tolerance-aware, returning `Finding`s with the same `mode` semantics as `check_differential`.
- Refactor conv-migration's before/after comparison to delegate to `check_values`, **preserving its exact
  decisions** ("À DÉCIDER" on mismatch; migrate + note under `--accept-diffs`).
- Forward `tolerance` through `guarded_apply` (closes the adversarial-review gap where it was dropped).
- Dogfood: dry-run the refactor on a **test copy** and confirm identical per-card decisions to the old code.

**Non-goals (YAGNI)**
- No `column_map` / tabular cell-by-cell differ — it does not match conv-migration's data shape.
- No change to `series_display_map` / `card_cells` extraction (stays upstream, domain logic).
- No change to `check_differential`'s tabular behaviour beyond the `guarded_apply` tolerance forward.
- No wiring into `iac.apply` (deferred), no change to conv-migration orchestration (copies, dry-run, steps).

## 3. Design

### 3.1 `check_values` (new, in `validate.py`)

```
check_values(target, before, after, mode="monitor", tolerance=0.0) -> List[Finding]
```
- `before` / `after`: sequences of scalar values. conv-migration passes its sorted/rounded numeric lists;
  the function works for any list of comparable scalars.
- `mode`: `identical` ⇒ a difference is an **error** Finding; `monitor` ⇒ a **warn** Finding (same convention as `check_differential`).
- Comparison:
  - If `len(before) != len(after)` ⇒ a single `value count A -> B` Finding (the multisets cannot align). No element comparison.
  - Else, treat as a **multiset**: if every element on both sides is numeric (int/float, not bool), sort both
    numerically and compare element-wise; numeric elements differ when `abs(a-b)/(abs(b) or 1) > tolerance`
    (or NaN). If any element is non-numeric, compare the two sequences for **exact ordered equality** (no sort).
  - Aggregate to **one summary Finding** (not one per element): e.g. `2/14 values differ beyond tolerance, first 100.0 -> 120.0`.
  - No differences ⇒ a single `ok` Finding (`N values, no change`).
- `tolerance=0.0` reproduces conv-migration's exact `before != after` on its rounded lists.

### 3.2 `guarded_apply` — forward `tolerance` (closes adversarial gap)

```
guarded_apply(client, units, mutate_fn, differential="monitor",
              force=False, execute=True, tolerance=0.0) -> Report
```
Pass `tolerance` into its `check_differential` call instead of silently dropping it. (Tabular path; no `column_map`.)

### 3.3 conv-migration refactor (decisions unchanged)

In `migrate_dashboard_reuse.py` (and the duplicated compare in `migrate_conversions_on_dashboard.py` /
`migrate_dashboard_full.py`), replace the hand-rolled comparison:

```
from spark_metabase_api import validate as V

# direct case (was: before != after)
findings = V.check_values(card_name, before, after,
                          mode="monitor" if args.accept_diffs else "identical")
# series-mapped case (was: b2 == a2) — same call on b2 / a2

if any(f.level == "error" for f in findings):
    decision = "À DÉCIDER (valeurs ≠ : {})".format(
        next(f.message for f in findings if f.level == "error"))
elif args.accept_diffs and any(f.level == "warn" for f in findings):
    diff_note = " [écart accepté: {}]".format(
        next(f.message for f in findings if f.level == "warn"))
# else: migrate cleanly
```
`before`/`after`/`b2`/`a2` are exactly today's `card_values`/`card_cells` outputs (sorted numeric lists);
no adapter needed. `series_display_map` + `card_cells` stay upstream. The "À VÉRIFIER (fenêtre vide)" and
"À DÉCIDER (rendu incohérent)" branches are untouched. `migrate_client.py` orchestration is untouched.

### 3.4 Dogfood — differential test of the differential

After the refactor, dry-run the migration on a throwaway **test copy** of a small sample of dashboards and
assert per-card decisions ("À DÉCIDER" / "migrée" / écart-accepté note) are **identical** to the
pre-refactor code on the same sample — behaviour-preserving verification on the real, active campaign.

## 4. Error handling / safety
- Pure behaviour-preserving refactor; §3.4 dogfood is the proof.
- conv-migration keeps running on **copies** with **dry-run** by default — live dashboards untouched by this work.
- `check_values` is additive and `check_differential` is unchanged, so the merged layer's 148 tests stay green.

## 5. Testing
- `check_values` unit tests: equal lists ⇒ `ok`; length mismatch ⇒ `value count` Finding; one value beyond
  tolerance ⇒ Finding (`identical`⇒error, `monitor`⇒warn); difference **within** tolerance ⇒ `ok`; unsorted
  numeric inputs still compared as a multiset; a non-numeric sequence compared exactly; `tolerance=0` exact.
- conv-migration: fixture-based test of the delegation — a before/after that yields "À DÉCIDER", one that
  yields "migrée", and one `--accept-diffs` that yields the écart note — proving the decision mapping is preserved.
- `guarded_apply` honours a non-zero `tolerance` (no longer dropped).

## 6. Decisions & open points
- **Decided**: `check_values` treats all-numeric inputs as a **multiset** (sorts internally), so it is
  order-agnostic; mixed/non-numeric inputs fall back to exact ordered equality.
- **Decided**: length mismatch ⇒ a single `value count` Finding; one summary Finding per call (not per element).
- **Risk**: a `migrate_*` script may compute `before`/`after` slightly differently across the three files;
  the implementation reads each call site and routes it through the same `check_values` call, confirming the
  same decision via §3.4 before relying on it.
