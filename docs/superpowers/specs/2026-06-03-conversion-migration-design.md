# Conversion migration (old positional → new named) — Design

> **Status:** test/spike validated 2026-06-03 · scaling plan pending Airtable mapping.
> **Spike artifacts (sandbox, safe to delete):** copy dashboard `25302`, collection `13851`.
> Related: `docs/cleaning-roadmap.md` (invariant dashboard, swap tooling), `docs/generic-questions-reorg.md` (§5 Nouvelles Conversions).

## 1. Problem

Spark changed its conversion-counting system. Snowflake `global.campaign_daily_metrics`
gained **new named columns** (`custom_conversions_1..5`, `custom_conversions_N_value`, and
standard named conversions — purchases, leads, add-to-cart, …), replacing the old
**positional** columns (`conversions`, `conversions_1..19`, `conversion_value*`).

New Metabase questions already exist under collection **`11673 "Nouvelles Conversions"`**
(`11871 Conversions génériques`, `11872 Conversions custom`), organised as
`conversion type × chart type × variant` (e.g. `Custom Conversion 1 → Smartscalar → {Custom Conversion 1, value, CAC, COS, CR, ROAS, …}`).

**Goal:** on each client's **custom** dashboards, replace every tile backed by an
old-system conversion question with its new-system equivalent, preserving layout and
filter wiring. Then scale across all clients with agents + task tracking.

## 2. Architecture (as found)

- Each client has a collection under `317`. Custom dashboards (vs templates) are
  **client-pinned**: a dashboard `Client` param (default e.g. `["Pro Nutrition"]`) + a `Date` param.
- Tiles reference **shared template cards** (in shared collections, *not* the client
  collection), wired to the dashboard's params via `parameter_mappings`. Example tile:
  `card 266 "Conversions 1"` (collection 13687), a native-SQL card summing
  `conversions_1`, with ~19 filter template-tags; the dashcard wires only `clients` and `date`.
- The new equivalent `card 42635 "Custom Conversion 1"` (collection 12311) sums
  `custom_conversions_1`, same DB (144), same `smartscalar` display, exposes the same
  `clients`/`date` tags ⇒ filter wiring survives a `card_id` swap untouched.

**Mapping is per-client and positional→named.** The *same* old card maps to *different*
new cards depending on the client. Source of truth: Airtable base `apptzpE1FqCMGH0dw`,
table `tbliHOIPYGJCvLvas` ("Conversions"). Each row = one platform conversion per
account/brand; designated reporting conversions carry `type` (slot) + `new_type` (named).

Confirmed model (read 2026-06-03):
- `type` ∈ {Main conversion, 1st…19th conversion, Add to cart, App install, runs}
  → old column: `Main`→`CONVERSIONS`, `Nth`→`CONVERSIONS_N` (+ `*_VALUE` for value cards).
- `new_type` ∈ {Purchases, Add to cart, Initiate checkouts, Content views/View Item,
  Sign ups, Leads, MQL, SQL, Offline sales, App installs, Search visits…, Custom 1…15}
  → new column: `Purchases`→`PURCHASES`, `Custom K`→`CUSTOM_CONVERSIONS_K`, etc. (+ `*_VALUE`).
- Per client the slot→new_type is **consistent across the client's accounts/platforms**.
  Pro Nutrition: `Main→Purchases`, `1st→Custom 1`, `3rd→Custom 2`.
- **Slot number ≠ Custom number** (`3rd → Custom 2`) ⇒ Airtable is mandatory; never assume
  `conversions_N → custom_conversions_N`.
- Some (client, slot) rows have **empty `new_type`** (not yet mapped) ⇒ those tiles go to a
  review/skip queue, never guessed.
- The dashboard's `Client` param value (e.g. "Pro Nutrition") = Airtable `brand_name` → join key.

## 3. Why the existing `swap_card_on_dashboards.py` can't be reused as-is

It is a **dedup** tool. Four behaviours are wrong for migration:

| dim | dedup tool (existing) | migration tool (new) |
|---|---|---|
| old→new source | "find the canonical duplicate" | per-client mapping (Airtable) |
| safety check | **requires identical output fingerprint** | relaxed: same DB · new not archived · new covers wired tags |
| tag extractor | `legacy_query.native.template-tags` only | **format-tolerant** (`dataset_query.stages[].template-tags`) — *required* |
| scope / cleanup | all dashboards of old card, then **archive** | **one dashcard on one dashboard**, **never archive** the shared template |

`swap_lib.rewrite_dashcards` is correct as-is and is reused (repoints `card_id`,
`parameter_mappings.card_id`, `series`; targets stay valid — same tag names).

## 4. Validated test (spike) — 2026-06-03

Tile `266 → 42635` on a **shallow copy** of dashboard 14118 (Home Pro Nutrition).
Live dashboard never touched. Results:

- **Structural ✅** — `card_id` 266→42635; size/row/col preserved (`7×5 @ 6/17`);
  both `parameter_mappings` repointed to 42635 with identical targets.
- **Renders ✅** — new tile returns data.
- **Value + Snowflake cross-check ✅ exact** (Pro Nutrition, 2026-05-01→05-31):
  new tile current `646.225741` == independent `SUM(custom_conversions_1)` `646.225741`;
  old tile `646.225741` == `SUM(conversions_1)`. Old==new here is *correct* (faithful
  slot-1→Custom-1 remap); a wrong target would have diverged from the independent SUM.

Confirmed required fixes: (1) format-tolerant tag extractor — the new card has **no
`legacy_query`**, so plain `swap_lib` saw 0 tags and would have refused; (2) cosmetic:
dashcard `column_settings` keyed on old column name `CONVERSIONS_1` won't apply to
`CUSTOM_CONVERSIONS_1` → remap the keys.

## 5. Migration tool — `scripts/migrate_conversions_on_dashboard.py`

Inputs: `--dashboard <id>` (+ optional `--dashcard`), mapping resolved per client.
Per conversion tile:

1. **Identify** the tile as old-system: its card's native SQL references an old
   conversion column (`conversions`, `conversions_1..19`, `conversion_value*`).
2. **Resolve new card** = `mapping(client, old slot/type) → new type` (Airtable)
   × **chart shape** (display + dimensions/breakdown + metric variant) within 11673.
   Ambiguous/none → **manual-review queue** (no guess).
3. **Safety (relaxed):** same DB · new not archived · new covers the tile's wired tags
   (via format-tolerant extractor). Refuse otherwise.
4. **Rewrite** dashcard via `swap_lib.rewrite_dashcards`; **remap** `column_settings`
   keys old-column→new-column on the dashcard.
5. **Snapshot** the dashboard's dashcards (rollback) before PUT. **Never archive** old cards.

Helpers: format-tolerant `native_and_tags(card)`; `old_conversion_columns(sql)`;
`resolve_new_card(client, old_card, tree_index)`.

## 6. Validation strategy (per migrated tile)

- **Structural:** card_id/size/pos/viz preserved; wired tags still mapped.
- **Value readout:** run old & new tile for the client over a fixed window; record both.
- **Snowflake cross-check:** independent native SQL via `/api/dataset` (DB 144), same
  join chain (`utils.clients → client_ad_platforms → campaign_details →
  campaign_daily_metrics`), summing the new column for the client+window; assert match
  (exact for faithful remaps; for genuine recomputations, record both for human sign-off).
- No local Snowflake creds in this env — Metabase `/api/dataset` is the SQL gateway.

## 7. Sizing & match-coverage (measured 2026-06-03, offline over audit cache)

Old/new columns are authoritative (Snowflake `information_schema`): old = positional
`CONVERSIONS`, `CONVERSIONS_1..19`, `CONVERSION_VALUE`, `CONVERSION_1..19_VALUE`; new =
`CUSTOM_CONVERSIONS_1..15(+_VALUE)` + named (`PURCHASES`, `LEADS`, `INITIATE_CHECKOUTS`,
`SIGN_UPS`, `MARKETING_/SALES_QUALIFIED_LEADS`, `OFFLINE_SALES`, `ORGANIC_/PAID_SEARCH_VISITS`,
`SEARCH_VISITS_COMBO`, `*_NEW`…).

Over 5,659 cached cards:

- **1,451** old-conversion cards; **1,114 live on dashboards** (target set); **337 dormant** (ignore).
- Targets span 23,409 dashboard placements; displays: table 309 / smartscalar 301 / line 202 /
  pie 109 / combo 78 / bar 78 / …; metric kinds: COUNT 611 / CAC 159 / ROAS 117 / RATE 114 / VALUE 65 / …
- New tree: **2,095** cards — a clean generated grid (line/bar/pie/smartscalar/combo/table ×
  COUNT/VALUE/CAC/COS/CR/ROAS × ~20 breakdowns incl. date, channel, network, category, country,
  location, device, product, type, url, segment, adset, adgroup).
- **Auto-match coverage** (shape = display+metric+breakdown, type-agnostic): **77%** strict
  (862/1114), **93%** on display+metric only. Unmatched ~23% = low-frequency long tail
  (funnels, brand/non-brand pies, `by medium/url/page`) → **review queue**, mostly 1–16 each.

Implication: structural matching resolves ~3/4 automatically; the type-axis comes from Airtable;
a bounded review queue (~80–250 distinct cards) needs human/agent sign-off. (Heuristic here is
name-based/approximate; the tool will match structurally on SQL + viz.)

## 8. Scaling plan (agents + task tracking)

1. **Ingest mapping** from Airtable `apptzpE1FqCMGH0dw/tbliHOIPYGJCvLvas` → per-client
   `{old slot/type → new named type}`. *(Pending Airtable auth to finalise schema.)*
2. **Index the new tree** (11673): build `{new type × chart shape × variant → card_id}`.
3. **Discover targets:** under each client collection in `317`, list **custom**
   dashboards (exclude templates); for each, find tiles whose card uses an old
   conversion column. Scope = **every card touching a conversion column** (incl.
   value / CR / CAC / COS / ROAS / combos / funnels).
4. **Unit of work = one custom dashboard.** Task tracker: one task per (client, dashboard).
   Per task: snapshot → migrate all conversion tiles → validate → write report +
   rollback artifact. Ambiguous matches → review queue, not auto-applied.
5. **Orchestration:** agents run the validated tool per dashboard in parallel; a tracker
   records status, diffs, and any review-queue items. Roll out in waves
   (1 client end-to-end → sample → batch), mirroring the cleaning-roadmap discipline.

## 9. Open questions / risks

- **Airtable type-axis** — ✅ resolved: `type`(slot)→`new_type`(named), per-client,
  consistent across accounts (see §2). Residual risk: some (client, slot) have empty
  `new_type` (unmapped) → review/skip; and a few clients may have slot conflicts across
  accounts → flag. Ingestion = group rows by `brand_name` where `type` non-empty.
- **Custom-dashboard population** — how many custom dashboards per client (under `317`),
  and how many conversion tiles each → the true project size. Needs a dashboard crawl +
  a custom-vs-template heuristic (exclude names like "template"/"Spec"). *(plan step 8.3)*
- **Match review queue** — measured ~23% long tail (~80–250 cards). Confirm tool's
  structural matcher (SQL+viz, not names) lifts strict coverage above the 77% estimate.
- **Standard-conversion value change** — validate one slot-0 `conversions` → `Purchases`
  case where the number genuinely changes, before batch (the Custom-1 test had old==new).
- **Tile titles** — preserved as-is (e.g. "NC (Platform data)"); renaming out of scope.

## 10. Safety

Copy-first for tests; snapshot + PUT for live; never archive shared templates; never
auto-apply ambiguous matches; reversible at every step (restore dashcards from snapshot).
