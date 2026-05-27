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


@dataclass(frozen=True)
class CardRecord:
    id: int
    name: str
    collection_id: int
    dashboard_count: int
    archived: bool
    display: str


def capture_snapshot(get, root_id: int = ROOT_COLLECTION_ID) -> dict[int, CardRecord]:
    """Parcourt le sous-arbre `root_id` et capture les cartes (hors EXCLUDE).

    `get` est une fonction `endpoint -> json`. Le sous-arbre
    EXCLUDE_COLLECTION_ID n'est pas parcouru.
    """
    cards: dict[int, CardRecord] = {}

    def walk(coll_id: int):
        items = get(f"/api/collection/{coll_id}/items?limit=2000").get("data", [])
        for it in items:
            if it["model"] == "collection":
                if it["id"] != EXCLUDE_COLLECTION_ID:
                    walk(it["id"])
            elif it["model"] in ("card", "dataset"):
                detail = get(f"/api/card/{it['id']}")
                cards[it["id"]] = CardRecord(
                    id=detail["id"],
                    name=detail["name"],
                    collection_id=detail.get("collection_id"),
                    dashboard_count=detail.get("dashboard_count", 0),
                    archived=bool(detail.get("archived", False)),
                    display=detail.get("display") or "",
                )

    walk(root_id)
    return cards
