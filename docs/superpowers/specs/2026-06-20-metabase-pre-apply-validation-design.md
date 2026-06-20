# Pre-apply validation layer + repo ménage léger — Design

- **Date**: 2026-06-20
- **Status**: Proposed (awaiting review)
- **Author**: Louis + Claude (principal-eng pairing)

## 1. Context & motivation

Spark drives a live **Metabase + Snowflake** estate via the REST API: an IaC module
(`iac.py`, declarative YAML `plan`/`apply`) plus ~70 operational scripts that mutate
client dashboards/cards in bulk. **Neither has any pre-apply validation.** The only
safety net today is a manual "differential test" (run a card before/after a change,
eyeball the numbers) applied ad hoc per campaign.

Our incident history is the design driver. The bugs that actually hurt — wrong
conversion-column mapping, SERP `CTR>100`, multi-GSC paid-metric inflation ×N — **did
not error**. They ran fine and produced wrong numbers. A correctness gate alone catches
none of them; the differential test catches all of them. So the validator must do both.

We evaluated Metabase's official [`agent-skills`](https://github.com/metabase/agent-skills)
repo. It does **not** replace this repo (8 of 11 skills are embedding/SSO/SDK or learning,
outside our domain). We take the *ideas* of three skills, rebuilt natively — live/REST,
**no Enterprise JAR / Docker dependency**:

| Skill source | What we take |
|---|---|
| `metabase-semantic-checker` | referential-integrity + query-correctness checks (live, not via the EE JAR) |
| `metabase-representation-format` | the canonical entity schema for structural validation + `entity_id` as stable identity (field already in our specs) |
| `metabase-cli` | a unified `spark-metabase validate` command + report/exit-code ergonomics |

## 2. Goals / non-goals

**Goals**
- One reusable validation core, consumed by `iac.apply()`, the durable campaign libs, and a `spark-metabase validate` CLI.
- Four checks, cheap→expensive, fail-fast: `structure → refs → execution → differential`.
- **Execution is the source of truth**: run the real query via Metabase (same path the dashboard uses).
- Differential regression detection with **caller-declared intent** (`identical` vs `monitor`).
- A light repo ménage (Phase 0) that separates the durable core from spent one-shot scripts and commits the uncommitted critical work.

**Non-goals (YAGNI)**
- No chatbot integration (unused experiment).
- No Enterprise serialization / JAR / Docker.
- No static-only metadata cache — we execute instead.
- No destroy-aware Terraform, no cross-instance migration, no embedding/SSO/SDK.
- Phase 0 is relocation + cleanup, **not** a rewrite of the scripts.

## 3. Phase 0 — Ménage léger (first, separate PR)

**Why first**: it tells the validation layer exactly which libs survive and deserve wiring.

Target layout:
```
scripts/
  lib/             durable, reusable, tested libs (conv, bascule, swap, audit, rename, reorg, audit_report)
  campaigns/<nom>/ one-shot drivers + their tracker/HANDOFF docs (archived, reversible via git mv)
  *.py             (flat root emptied of disposable drivers and version-cruft)
```
Rules:
1. **Commit first** the untracked durable libs + their tests (`conv_lib`, `bascule_lib`,
   `test_conv_lib`, `test_bascule_lib`, `test_conv_tracker`, …). This work currently exists
   only on the local machine (bus-factor).
2. **Kill version-cruft**: keep the winning version, delete superseded `_v2`/`_v3`
   (`build_seo_dashboard{,_v2}`, `build_seo_monitoring{,_v2}`, `probe{,_v2}`, …). The
   concrete keep/delete list is generated from evidence and **confirmed before any deletion**.
3. **Relocate** spent one-shot drivers (`apply_fixes_32496`, `*_24576`,
   `add_quizroom_disclaimer`, finished `migrate_client`, …) into `scripts/campaigns/<nom>/`
   with their docs, via `git mv` (reversible).
4. Fix import paths broken by relocation; `pytest` green before merge.

## 4. Phase 1 — Validation layer

New module `spark_metabase_api/validate.py`.

### 4.1 Target abstraction
A `Target` normalizes the three things we validate into common **card units**:
- an `iac.CollectionSpec` (cards/dashboards declared, pre-apply),
- a raw card payload a campaign lib is about to PUT,
- a live card/dashboard by id.

Each card unit carries `dataset_query`, `display`, `visualization_settings`, identity, and
an optional `live_card_id` (for baseline capture).

### 4.2 Check pipeline
Per card unit, fail-fast cheap→expensive; units run in parallel; **only the touched scope**
is validated (never the whole instance).

1. **`check_structure(unit)`** — our own structural rules, informed by the
   representation-format conventions (no dependency on Metabase's schema files): required
   fields present, `display` is a known type, `visualization_settings` shape valid,
   `dataset_query` has `database` + (`native.query` | MBQL `query`). Offline. → **error** on fail. *(representation-format)*
2. **`check_refs(unit, client)`** — every reference resolves: `collection_id`,
   `dashboard_id`, dashcard `card_id`, `parameter_mappings` targets, field-filter
   `values_source_config.card_id`. Intra-spec forward refs reuse `iac._resolve_card_names`;
   plus live lookups. → **error** on dangling ref. *(semantic-checker)*
3. **`check_execution(unit, client)`** — run the real query and inspect the result:
   - saved card → `POST /api/card/:id/query`; not-yet-created → `POST /api/dataset` with the
     `dataset_query` (+ default values for native template-tags / field filters).
   - → **error** if the query fails; **warn** if 0 rows (configurable) or expected columns missing. *(toujours exécuter)*
4. **`check_differential(baseline, after, mode)`** — only for updates with a baseline.
   Compares row count, column set, and the sum of each numeric column.
   - `mode=identical` (result-preserving refactors: anti-pattern fixes, swaps) → any change beyond tolerance (default tolerance = 0, i.e. exact) = **error**.
   - `mode=monitor` (intentional changes: conversion migration) → changes reported as **warn**.
   - metric: **auto** (row count + column set + per-numeric-column sums) with optional per-card **override** (pin columns / set tolerance). *(your differential test, automated)*

### 4.3 Report model
`Finding{target, level (error|warn|ok), check, message, before?, after?}`.
`Report` aggregates findings, has `.render()` (Terraform-style glyphs, like `iac.Plan`) and
maps to a process exit code (non-zero on any `error`). Findings are **collected, not raised
mid-batch**, so a bulk run yields a full picture.

### 4.4 Around-apply orchestration
The differential is inherently before/after, so the validator exposes building blocks and a
guarded wrapper:
```
for each card unit being updated:
    baseline = capture(client, card_id)        # if differential enabled
pre-apply gate: structure + refs + execution   # abort, do NOT mutate, if any error
mutate (PUT/POST)
after = execute(client, card_id)
report += check_differential(baseline, after, mode)
```
For creates: no baseline; gate + post-create execution only.

### 4.5 Integration points
- `iac.apply(client, spec, ..., validate=True, differential="monitor", force=False)` — runs
  the gate before mutating; aborts on error unless `force`.
- Campaign libs call `validate.guarded_apply(client, payload, mutate_fn, mode=...)`.
- CLI: `spark-metabase validate <spec.yaml | collection-name/id | card-id> [--differential identical|monitor|off] [--no-execute]`.

### 4.6 Wrapper additions
- Thin `run_query(dataset_query)` (POST `/api/dataset`); reuse existing `get_card_data` for saved cards.
- *Nice-to-have, not v1-blocking*: retry/backoff hardening on the shared session.

## 5. Error handling / safety
- The pre-apply gate **never mutates** on error; default is abort, `--force` overrides (logged).
- `--no-execute` falls back to `structure`+`refs` only (fast smoke check) — escape hatch when the warehouse is down.

## 6. Testing
- Each check is a pure-ish function tested in isolation (mock client / fixture payloads), mirroring our `test_*_lib.py` culture.
- `Report.render()` snapshot-tested.
- Differential logic unit-tested with synthetic before/after result sets (identical / dropped rows / sum drift / new column).
- An opt-in live phase extends `tests/integration_test.py` against a sandbox collection.

## 7. Decisions & risks
- **Decided** (delegated to eng judgment): differential metric = auto (row count + column set + per-numeric-column sums) + optional per-card override.
- **Risk**: native SQL with required template-tags / field filters needs default param values
  to execute via `/api/dataset`. *Mitigation*: derive defaults from the card's `template-tags`;
  else fall back to `/api/card/:id/query` for saved cards, and flag un-runnable unsaved cards
  as **warn** ("execution skipped: needs params").
- **Risk**: Phase 0 relocation breaks imports. *Mitigation*: `git mv` + import fix + green `pytest` gate before merge.
