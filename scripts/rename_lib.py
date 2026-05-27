"""Logique pure de la Phase 1.5 — normalisation du nommage des cartes."""
from __future__ import annotations

import re
from collections import defaultdict
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


DISPLAY_LABEL = {
    "line": "Line", "bar": "Bar", "area": "Area", "combo": "Combo",
    "pie": "Pie", "table": "Table", "scalar": "Scalar",
    "smartscalar": "Smart scalar", "funnel": "Funnel",
    "map": "Map", "waterfall": "Waterfall", "row": "Row",
    "progress": "Progress", "gauge": "Gauge", "pivot": "Pivot",
}

_CRYPTIC = [re.compile(p) for p in (r"^Cac\d+$", r"^Conv\d+$")]


@dataclass(frozen=True)
class ProposalRow:
    card_id: int
    current_name: str
    proposed_name: str
    rule: str        # normalize | viz_collision | duplicate | cryptic
    status: str      # auto | décision
    notes: str = ""


def _is_cryptic(name: str) -> bool:
    return any(p.match(name) for p in _CRYPTIC)


def _viz_label(display: str) -> str:
    return DISPLAY_LABEL.get(display, display.title() if display else "?")


def propose_renames(snapshot: dict[int, CardRecord]) -> list[ProposalRow]:
    # Group by normalized name
    groups: dict[str, list[CardRecord]] = defaultdict(list)
    for rec in snapshot.values():
        groups[normalize_name(rec.name)].append(rec)

    rows: list[ProposalRow] = []
    for normalized, members in groups.items():
        if len(members) == 1:
            rec = members[0]
            if _is_cryptic(rec.name):
                rows.append(ProposalRow(
                    card_id=rec.id, current_name=rec.name,
                    proposed_name=rec.name, rule="cryptic", status="décision",
                    notes="nom court non descriptif — humain décide"))
            elif normalized != rec.name:
                rows.append(ProposalRow(
                    card_id=rec.id, current_name=rec.name,
                    proposed_name=normalized, rule="normalize", status="auto"))
            continue

        # Groupe de 2+ cartes au même nom normalisé
        displays = [m.display for m in members]
        has_dup_display = len(set(displays)) < len(displays)
        if has_dup_display:
            # Au moins 2 cartes partagent le même display -> vrai doublon, humain tranche
            ids = ", ".join(f"#{m.id}" for m in members)
            for rec in members:
                rows.append(ProposalRow(
                    card_id=rec.id, current_name=rec.name,
                    proposed_name=rec.name, rule="duplicate", status="décision",
                    notes=f"doublon dans le groupe ({ids})"))
        else:
            # Tous les displays distincts -> suffixer
            for rec in members:
                proposed = f"{normalized} — {_viz_label(rec.display)}"
                rows.append(ProposalRow(
                    card_id=rec.id, current_name=rec.name,
                    proposed_name=proposed, rule="viz_collision", status="auto"))

    return rows
