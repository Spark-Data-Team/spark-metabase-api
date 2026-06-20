# Repo Ménage Léger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate the durable, reusable core from spent one-shot scripts, commit critical uncommitted work, and delete version-cruft — so the validation layer (Phase 1) wires only to what survives.

**Architecture:** Pure repo reorganization. Move spent one-shot drivers into `scripts/campaigns/<nom>/` (reversible `git mv`), commit untracked durable libs, delete superseded `_v2`/`_v3` after explicit confirmation. No behavior changes.

**Tech Stack:** git, Python 3, pytest.

## Global Constraints

- This is Phase 0 of `docs/superpowers/specs/2026-06-20-metabase-pre-apply-validation-design.md`. Relocation only, **not** a rewrite.
- **Never delete a file without explicit user confirmation of the keep/delete list** (Task 2 gate).
- `pytest` must be green before and after the reorg.
- All moves use `git mv` (reversible); deletions only after Task 2 confirmation.
- Commit messages end with the `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` trailer.

---

### Task 1: Commit untracked durable libs + their tests

**Files:**
- Commit (currently untracked): `scripts/conv_lib.py`, `scripts/bascule_lib.py`, `scripts/conv_tracker.py` and their tests `tests/test_conv_lib.py`, `tests/test_bascule_lib.py`, `tests/test_conv_tracker.py` (exact set discovered in Step 1).

**Interfaces:**
- Produces: a committed durable-lib baseline that Phase 1 and later tasks rely on existing in git.

- [ ] **Step 1: Discover the untracked durable libs and their tests**

Run:
```bash
git ls-files --others --exclude-standard scripts/ tests/ | grep -E '(_lib|_tracker|^tests/test_)' 
```
Expected: lists `scripts/conv_lib.py`, `scripts/bascule_lib.py`, `scripts/conv_tracker.py`, `tests/test_conv_lib.py`, `tests/test_bascule_lib.py`, `tests/test_conv_tracker.py` (a durable lib = imported by a `test_*.py` and not tied to one dashboard id).

- [ ] **Step 2: Verify these tests pass before committing**

Run: `python -m pytest tests/test_conv_lib.py tests/test_bascule_lib.py tests/test_conv_tracker.py -q`
Expected: PASS (all green). If a test imports a module not in the discovered set, add that module to the commit set.

- [ ] **Step 3: Stage ONLY the discovered durable libs + tests**

```bash
git add scripts/conv_lib.py scripts/bascule_lib.py scripts/conv_tracker.py \
        tests/test_conv_lib.py tests/test_bascule_lib.py tests/test_conv_tracker.py
git status --short   # confirm nothing else is staged
```
Expected: only the six files (adjust to the discovered set) are staged.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: commit durable campaign libs (conv, bascule, tracker) + tests

Critical bulk-migration logic was untracked (local-only); commit it so it is
versioned before the repo reorg.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
Expected: commit created; `git status` no longer lists those files as untracked.

---

### Task 2: Generate the evidence-based keep/archive/kill triage and CONFIRM

**Files:**
- Create: `docs/superpowers/plans/menage-triage.md` (the classified list, for the record).

**Interfaces:**
- Produces: a confirmed three-bucket classification (`KEEP` / `ARCHIVE` / `KILL`) that Tasks 3–4 act on. **Tasks 3–4 must not run until the user approves this list.**

- [ ] **Step 1: Classify every script by evidence**

Run these and record the output:
```bash
# durable libs (imported by tests) -> KEEP
git grep -l "import " tests/ | xargs -I{} grep -hoE "from scripts\.[a-z_]+|import [a-z_]+_lib" {} 2>/dev/null | sort -u
# version-cruft: a base name that also has _v2/_v3 -> KILL the superseded ones
ls scripts/ | sed -E 's/_v[0-9]+//' | sort | uniq -d
# one-shot drivers: reference a specific dashboard/card id or client -> ARCHIVE
grep -lE "2457[0-9]|3249[0-9]|24642|quizroom|manucurist" scripts/*.py
```

- [ ] **Step 2: Write the classification table**

Create `docs/superpowers/plans/menage-triage.md` with three sections:
```markdown
## KEEP (durable core, stays in scripts/lib/ or scripts/)
- conv_lib.py, bascule_lib.py, swap_lib.py, audit_lib.py, rename_lib.py, reorg_lib.py, audit_report.py, conv_tracker.py  (+ any imported by tests)

## ARCHIVE (one-shot drivers -> scripts/campaigns/<nom>/)
- <list each driver + its target campaign folder, e.g. apply_fixes_32496.py -> campaigns/serp-32496/>

## KILL (superseded version-cruft, after confirming the winner)
- <list each loser + WHY it is superseded by which winner>
```
For every KILL entry, state which version is the winner and the evidence (newer, imported, referenced in a tracker doc).

- [ ] **Step 3: GATE — present the list and get explicit confirmation**

Show the user the KEEP/ARCHIVE/KILL table. **Do not proceed to Task 3 or 4 until the user confirms.** Record their edits in `menage-triage.md`, then commit the doc:
```bash
git add docs/superpowers/plans/menage-triage.md
git commit -m "docs: ménage triage list (keep/archive/kill), confirmed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Relocate one-shot drivers into scripts/campaigns/

**Files:**
- Create: `scripts/campaigns/<nom>/` directories.
- Move: each ARCHIVE-bucket driver + its tracker/HANDOFF doc.

**Interfaces:**
- Consumes: the confirmed ARCHIVE list from Task 2.
- Produces: a `scripts/campaigns/` tree; the flat `scripts/` root no longer holds spent drivers.

- [ ] **Step 1: Create campaign folders and move files with git mv**

For each ARCHIVE entry (example shown — repeat per confirmed entry):
```bash
mkdir -p scripts/campaigns/serp-32496
git mv scripts/apply_fixes_32496.py scripts/campaigns/serp-32496/
git mv docs/seo-manucurist-HANDOFF.md scripts/campaigns/serp-32496/ 2>/dev/null || true
```

- [ ] **Step 2: Verify no durable code imports a moved driver**

Run: `git grep -nE "import (apply_fixes_32496|bilingual_24576|add_quizroom_disclaimer)" -- scripts/ tests/`
Expected: no matches (drivers are leaf scripts). If a match exists, that file is NOT a leaf — move it back to KEEP and re-confirm with the user.

- [ ] **Step 3: Commit the relocation**

```bash
git add -A scripts/campaigns/ && git add -u scripts/ docs/
git commit -m "refactor: archive one-shot campaign drivers under scripts/campaigns/

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Delete confirmed version-cruft

**Files:**
- Delete: each KILL-bucket file (superseded `_v2`/`_v3` losers).

**Interfaces:**
- Consumes: the confirmed KILL list from Task 2.

- [ ] **Step 1: Delete the confirmed losers (only those on the confirmed list)**

```bash
# example — use the exact confirmed KILL list
git rm scripts/build_seo_dashboard.py scripts/build_seo_dashboard_v2.py \
       scripts/build_seo_monitoring.py scripts/build_seo_monitoring_v2.py \
       scripts/probe_v2.py
```

- [ ] **Step 2: Verify nothing imports the deleted files**

Run: `git grep -nE "build_seo_dashboard_v2|build_seo_monitoring_v2|probe_v2" -- scripts/ tests/`
Expected: no matches. If a match exists, restore that file (`git checkout HEAD -- <file>`) and flag it.

- [ ] **Step 3: Commit the deletions**

```bash
git commit -m "chore: delete superseded version-cruft (kept the winning versions)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Fix imports broken by relocation and verify green

**Files:**
- Modify: any moved driver whose relative imports broke.
- Test: full suite.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS. If a moved driver fails to import a lib, fix its import path (libs stayed in `scripts/`; a driver in `scripts/campaigns/<nom>/` imports a lib via `from scripts.conv_lib import ...` or an explicit `sys.path` insert — match the project's existing import style).

- [ ] **Step 2: Confirm the flat scripts/ root is legible**

Run: `ls scripts/`
Expected: only durable libs + `campaigns/` + a small set of reusable utilities; no `_v2`/`_v3` duplicates, no dashboard-id-specific drivers at the root.

- [ ] **Step 3: Commit any import fixes**

```bash
git add -u && git commit -m "fix: repair import paths after campaign relocation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage:** Phase 0 rules 1–4 of the spec → Task 1 (commit untracked), Task 2 (triage + confirm), Task 3 (relocate), Task 4 (kill cruft), Task 5 (imports + pytest gate). ✓
- **Placeholder scan:** Example file lists are explicitly marked "use the confirmed list"; the concrete list is produced in Task 2 by design (confirm-before-delete). ✓
- **Safety:** No deletion before Task 2 confirmation; all moves reversible via git. ✓
