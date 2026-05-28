#!/usr/bin/env python3
"""Rendu du rapport d'audit en markdown — digest COURT (détail exhaustif dans le JSON)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_lib import summarize_findings  # noqa: E402

MAX_EXAMPLES = 5
WAVE_TITLES = {
    0: "Vague 0 — Quick wins",
    1: "Vague 1 — Automatisable",
    2: "Vague 2 — Structurel",
    3: "Vague 3 — DRY / dérive",
}


def _example_line(key, item):
    if key in ("empty_collections", "junk_collections"):
        return f"`{item.get('id')}` {item.get('name')}"
    if key == "dup_collection_names":
        return f"« {item.get('name')} » ×{item.get('count')}"
    if key == "personal_sprawl":
        return f"{item.get('client')} ×{item.get('count')}"
    if key in ("unused_cards", "naming_issues", "template_drift"):
        return f"#{item.get('id')} {item.get('name')}"
    if key in ("pure_dups", "variant_families"):
        return f"groupe de {len(item)} : " + ", ".join(f"#{c['id']}" for c in item[:4])
    return str(item)[:80]


def render_report(findings, *, scanned_cards=0, scanned_collections=0, date=""):
    rows = summarize_findings(findings)
    lines = [f"# Audit Metabase — {date}", "",
             f"_{scanned_collections} collections · {scanned_cards} cartes scannées._", ""]
    lines += ["## Résumé", "", "| # | Pattern | Compte | I/R/E | Vague |",
              "|---|---------|--------|-------|-------|"]
    for f in rows:
        ire = f"{f.get('impact','?')}/{f.get('risk','?')}/{f.get('effort','?')}"
        lines.append(f"| {f.get('num','?')} | {f['key']} | {f.get('count',0)} | {ire} | {f.get('wave','?')} |")
    lines += ["", "## Backlog (quick-wins d'abord)", ""]
    for wave in (0, 1, 2, 3):
        wf = [f for f in rows if f.get("wave") == wave and f.get("count", 0) > 0]
        if not wf:
            continue
        lines.append(f"### {WAVE_TITLES[wave]}")
        for f in wf:
            lines.append(f"- **{f['key']}** ({f.get('count',0)}) — {f.get('impact')}/{f.get('risk')}/{f.get('effort')}")
            for item in f.get("items", [])[:MAX_EXAMPLES]:
                lines.append(f"  - {_example_line(f['key'], item)}")
            if f.get("count", 0) > MAX_EXAMPLES:
                lines.append(f"  - … +{f['count'] - MAX_EXAMPLES} (détail dans le JSON)")
        lines.append("")
    return "\n".join(lines)
