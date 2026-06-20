# Ménage Triage — scripts/ classification

**Date**: 2026-06-20
**Status**: AWAITING USER CONFIRMATION (gate before Tasks 3 & 4)

Pre-classified KEEP (not re-litigated): `conv_lib.py`, `bascule_lib.py`, `conv_tracker.py` (committed T1); `audit_lib.py`, `audit_report.py`, `rename_lib.py`, `reorg_lib.py`, `swap_lib.py` (already tracked).

---

## KEEP (durable core — stays in scripts/ or moves to scripts/lib/)

- `audit_lib.py` — imported by `tests/test_audit_lib.py`; instance-wide scan/deep engine
- `audit_report.py` — imported by `tests/test_audit_report.py`; report renderer for audit_lib
- `rename_lib.py` — imported by `tests/test_rename_lib.py`; card-naming normalisation lib
- `reorg_lib.py` — imported by `tests/test_reorg_lib.py`; collection-reorg state machine
- `swap_lib.py` — imported by `tests/test_swap_lib.py`; card-swap safety-check + repoint
- `conv_lib.py` — imported by tests + 10+ campaign drivers; conversion-column mapping core
- `bascule_lib.py` — imported by `tests/test_bascule_lib.py`; time-filter bascule logic
- `conv_tracker.py` — imported by `tests/test_conv_tracker.py` + `migrate_client.py`; migration tracker state
- `archive_collections.py` — exports `connect_resilient()` imported by 8 scripts (audit_brand_clause, batch_brand_fix, convert_generic_temporal, migrate_client, fix_brand_clause_cards, tag_existing, validate_brand_batch, archive_superseded); durable connection helper even though it also has a `__main__`; default KEEP (non-leaf, would break imports)
- `audit.py` — generic instance-wide audit CLI (scan/deep/report), no client id hardcoded; referenced in memory + spec as the audit engine entry point
- `archive_stale_cards.py` — generic stale-card archiver (threshold-based, no client id); imports `audit_lib`; durable wave-0 tool
- `archive_empty_collections.py` — generic empty-collection archiver; reusable ménage utility
- `prune_unused.py` — archives unused cards from collection 215 (Generic Questions); generic utility tied to the library structure, not a specific campaign
- `find_dupes.py` — duplicate-card detector on collection 215; generic read-only analysis tool
- `reorg_phase1.py` — exports `_load_env()` + connection boilerplate imported by 46 scripts; also the Phase 1 CLI (done), but must stay as lib providing `_load_env`; default KEEP (non-leaf)
- `rename_phase15.py` — Phase 1.5 card-naming CLI; campaign complete, but imports `rename_lib` and is the primary CLI for that lib; default KEEP (the lib has no other runner)
- `reorg_xplat.py` — cross-platform reorg CLI; one-shot but has no client id hardcoded and could re-run; default KEEP (borderline — see note below)
- `sql_antipattern_scan.py` — read-only scan for antipattern candidates; generic, no client/card id; reusable for future audits
- `swap_card_on_dashboards.py` — generic card→canonical swap on all dashboards; parameterised by CLI args, no baked-in ids; durable utility
- `build_antipattern_tasks.py` — splits antipattern candidates into per-task SQL files; generic pipeline step
- `render_antipattern_report.py` — synthesises antipattern audit results into md+JSON; generic report renderer
- `fix_antipatterns.py` — applies antipattern fixes with before/after proof; general-purpose card-fix engine parameterised by card ids (not baked in)

---

## ARCHIVE (one-shot drivers → scripts/campaigns/<nom>/)

### campaigns/seo-manucurist/
- `build_seo_monitoring_v3.py` — winner of the v1/v2/v3 sequence; referenced as active in `docs/seo-manucurist-HANDOFF.md`; stays WITH the campaign
- `build_seo_dashboard_v3.py` — assembles Manucurist dashboard #25137; winner of the v1/v2/v3 sequence; referenced in HANDOFF
- `build_seo_pages_model.py` — builds pages model #49062 for Manucurist (collection #13752)
- `build_seo_saisonnalite.py` — builds saisonnalité model #49425 + pivot #49426 for Manucurist; imports `build_seo_monitoring_v3` (both move together)
- `build_seo_global_dashboard.py` — Phase 1 global-tracking dashboard for Manucurist (#13752); client-specific card ids
- `build_seo_grid.py` — builds the keyword-position grid card #48634 for Manucurist; historical V1 builder but not superseded by a v2/v3 grid builder
- `build_seo_inverted.py` — builds inverted-view card for Manucurist (#49557); client-specific
- `build_seo_polish.py` — V1 finishing touches on dashboard #25137 (layout, filters); one-shot
- `probe_v2.py` — data-discovery probe V2 for Manucurist SEO (GSC markets, page templates, brand kw); referenced in HANDOFF as useful template
- `probe_v3.py` — data-discovery probe V3 for Manucurist SEO (saisonnalité, CTR, URL, geo-clics); referenced in HANDOFF as active template
- `probe_vol.py` — probes volume variation in model #48633 (Manucurist); tied to that model
- `seo_collapse_fix.py` — applies pivot fold toggle + removes broken links on dashboard #25137 for Manucurist (V3.1 fix 2026-06-17)
- `seo_collapse_probe.py` — probe/backup for the collapse fix on dashboard #25137
- `seo_perf_probe.py` — perf diagnostic for Manucurist SEO dashboard #25137
- `seo_persist_apply.py` — activates persistence on models #48633/#49062/#49425 (Manucurist)
- `seo_persist_debug.py` — debug persistence endpoints for Manucurist models
- `seo_persist_probe.py` — probes persistence config before activation (Manucurist)
- `seo_persist_routes.py` — maps persistence routes for card #48633 (Manucurist)
- `serp_difftest.py` — differential test for card #32496 (Manucurist SERP positions cleanup)
- `apply_fixes_32496.py` — applied antipattern fixes to card #32496 (Manucurist SERP); one-shot, campaign done per memory 2026-06-11

### campaigns/conv-migration/
- `discover_conversion_targets.py` — crawls dashboards under collection 317 for old-conv tiles; conv-migration campaign driver
- `conv_preflight.py` — resolves each conversion tile and produces the migration worklist; conv-migration driver
- `export_conv_mapping.py` — transforms Airtable rows into client mapping JSON; conv-migration driver
- `build_new_conv_index.py` — indexes new-conversion cards by (col, shape); conv-migration driver
- `migrate_conversions_on_dashboard.py` — migrates conversion tiles on a single dashboard; conv-migration driver
- `migrate_dashboard_reuse.py` — migrates a copy dashboard by reusing 11673 cards; conv-migration driver
- `migrate_dashboard_full.py` — full migration (no tile left on old system) with generation; conv-migration driver
- `migrate_client.py` — orchestrator: copy → reuse → swap → bascule per client; conv-migration driver
- `generate_fallback.py` — generates fallback copies for tiles without an 11673 equivalent; conv-migration driver
- `polish_generated_viz.py` — fixes viz settings on generated-card dashcards after migration
- `swap_tables.py` — swaps multi-slot tables to mixed-family 11673 cards on a copy; conv-migration driver
- `bascule_time_filter.py` — bascules the time filter from category→temporal-unit on a copy; conv-migration driver (imports `bascule_lib`)
- `convert_generic_temporal.py` — creates temporal-unit copies of generic blocking cards (sandbox 13885); conv-migration driver
- `tag_existing.py` — applies [conv-2026-06] anchor to already-migrated dashboards; conv-migration driver
- `archive_superseded.py` — archives old dashboards superseded by migrated copies; conv-migration driver
- `validate_brand_batch.py` — post-batch validation: re-runs 1967 cards, triages failures; brand-fix campaign driver

### campaigns/brand-fix/
- `audit_brand_clause.py` — read-only audit of brand-exclusion clauses on subtree 11673; brand-fix campaign
- `batch_brand_fix.py` — batch-applies canonical brand rule to all 11673 cards with wrong clause; brand-fix driver
- `fix_brand_clause_cards.py` — fixes brand clause on specific card ids with before/after proof; brand-fix driver

### campaigns/quiz-room/
- `add_quizroom_disclaimer.py` — adds disclaimer text card to Quiz Room dashboards; one-shot quizroom

### campaigns/generic-questions-reorg/
- `bilingual_24576.py` — adds EN bilingual columns to dashboard #24576 (Quiz Room FR); one-shot
- `polish_headings_24576.py` — polishes heading heights/alignment on dashboard #24576 (Quiz Room FR); one-shot
- `translate_en_24576.py` — creates EN translation of dashboard #24576; one-shot
- `fit_text_cards.py` — adjusts text-card heights on dashboard #24576 (hardcoded); one-shot tied to that dash
- `set_card_heights.py` — sets explicit text-card heights on dashboard #24576 (TARGETS hardcoded); one-shot

### campaigns/audit-engine/
- `audit_extract_checks.py` — extracts Metabase "check" cards → dbt backlog (audit-engine phase 2); one-shot survey driver

---

## KILL (superseded version-cruft)

Evidence for each: the HANDOFF doc `docs/seo-manucurist-HANDOFF.md` explicitly lists v1/v2 as "historiques (cartes archivées)".

- `build_seo_monitoring.py` (V1) — **KILL**; winner = `build_seo_monitoring_v3.py`. Evidence: HANDOFF lists it as "Historique V1"; v3 is newer (Jun 15 vs May 29), adds FR keywords, richer columns, updates #48633 in-place.
- `build_seo_monitoring_v2.py` (V2) — **KILL**; winner = `build_seo_monitoring_v3.py`. Evidence: HANDOFF lists it as "Historique V2"; v3 is newer (Jun 15 vs Jun 11), adds Gamme/Catégorie/URL/traffic-potential columns.
- `build_seo_dashboard.py` (V1) — **KILL**; winner = `build_seo_dashboard_v3.py`. Evidence: HANDOFF lists it as "Historique V1"; v3 is newer (Jun 15 vs May 29), adds 7 filters + saisonnalité tile.
- `build_seo_dashboard_v2.py` (V2) — **KILL**; winner = `build_seo_dashboard_v3.py`. Evidence: HANDOFF lists it as "Historique V2"; v3 is newer (Jun 15 vs Jun 11), adds saisonnalité section + links.

> **Note on probe_v2.py**: NOT a kill candidate despite the name. The HANDOFF explicitly keeps both `probe_v2.py` and `probe_v3.py` as "réutilisables comme gabarits de sondage" (useful reference templates). They probe different things (v2 = GSC markets/page templates, v3 = saisonnalité/CTR/URL/geo). Both go to ARCHIVE → campaigns/seo-manucurist/.

---

## NEEDS HUMAN DECISION

- `reorg_xplat.py` — Cross-platform collection 214 reorg. It ran once (one-shot), but has no client-specific id hardcoded and is generic enough to re-run. Unclear if the reorg is considered "done" or may need re-running. **Decision needed**: ARCHIVE → campaigns/generic-questions-reorg/ (if done) or KEEP (if may re-run).

- `audit_extract_checks.py` — Extracts Metabase "check" cards for dbt audit-engine phase 2 porting. The docstring says "audit engine, phase 2" which suggests it's a driver for a planned campaign, not yet run. **Decision needed**: ARCHIVE → campaigns/audit-engine/ (if phase 2 is shelved) or KEEP at root (if phase 2 is imminent).

---

## Counts summary

| Bucket | Count |
|--------|-------|
| KEEP (incl. 8 pre-classified re-listed + 14 new) | 22 |
| ARCHIVE (one-shot drivers) | 38 |
| KILL (superseded version-cruft) | 4 |
| NEEDS HUMAN DECISION | 2 |
| **Total scripts/*.py classified** | **66** (all 72 files covered: 8 pre-classified + 64 new) |

(All 72 `scripts/*.py` files accounted for. The 8 pre-classified libs appear at the top of KEEP for completeness.)
