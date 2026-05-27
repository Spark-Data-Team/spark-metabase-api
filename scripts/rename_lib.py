"""Logique pure de la Phase 1.5 — normalisation du nommage des cartes."""
from __future__ import annotations

import re
from dataclasses import dataclass

ROOT_COLLECTION_ID = 215
EXCLUDE_COLLECTION_ID = 11673

ACRONYMS = {
    "CAC", "CPC", "CPM", "CPL", "CPA", "CPI",
    "CTR", "CR", "ROAS", "COS", "KPI", "KPIs",
    "SEO", "GA4", "PMax", "DPA", "ATC", "ROI",
}

_ACRONYM_BY_UPPER = {a.upper(): a for a in ACRONYMS}
_TOKEN_RE = re.compile(r"^(\W*)([A-Za-z0-9]+)(\W*)$")


def _fix_acronym(tok: str) -> str:
    m = _TOKEN_RE.match(tok)
    if not m:
        return tok
    pre, core, post = m.groups()
    canonical = _ACRONYM_BY_UPPER.get(core.upper())
    return f"{pre}{canonical}{post}" if canonical else tok


def normalize_name(name: str) -> str:
    """Trim, snake_case→spaces, Sentence case, acronymes préservés."""
    s = name.replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return s
    s = s.lower()
    s = " ".join(_fix_acronym(t) for t in s.split(" "))
    # Capitaliser le premier caractère alphabétique
    for i, ch in enumerate(s):
        if ch.isalpha():
            return s[:i] + ch.upper() + s[i + 1 :]
    return s
