"""Logique pure de la Phase 1.5 — normalisation du nommage des cartes."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

ROOT_COLLECTION_ID = 215
EXCLUDE_COLLECTION_ID = 11673

ACRONYMS = {
    # KPIs / metric acronyms
    "CAC", "CPC", "CPM", "CPL", "CPA", "CPI",
    "CTR", "CR", "ROAS", "COS", "KPI", "KPIs",
    "ATC", "ROI", "AOV", "IS", "CA",
    "NCAC", "NROAS", "NCOS", "EVS",
    # Domains / channels
    "SEO", "SEA", "SMA", "GA4", "GSC", "SERP",
    "PMax", "DPA", "DNVB", "BP",
    # Misc
    "URL", "LLM", "HT", "TTC", "NC", "YoY", "IA", "AI",
    # Brand / platform names (preserved like acronyms)
    "Adjust", "Shopify", "Google", "Amazon", "Meta",
    "TikTok", "Magento", "Pinterest", "Spotify",
}

_ACRONYM_BY_UPPER = {a.upper(): a for a in ACRONYMS}
_ALNUM_RUN = re.compile(r"[A-Za-z0-9]+")


def normalize_name(name: str) -> str:
    """Trim, snake_case→spaces, ponctuation propre, Sentence case, acronymes préservés.

    Nettoyage : espace après virgule, espace avant parenthèse collée à un mot,
    parenthèses répétées identiques (`(X) (X)` -> `(X)`) réduites.
    """
    s = name.replace("_", " ").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r",(?=\S)", ", ", s)                 # espace après virgule
    s = re.sub(r"(?<=[A-Za-z0-9])\(", " (", s)      # espace avant '(' collée
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(\([^()]+\))\s+\1", r"\1", s, flags=re.IGNORECASE)  # parenthèses dupliquées
    if not s:
        return s
    s = s.lower()
    # Détection d'acronyme sur chaque segment alphanumérique (gère la ponctuation interne)
    s = _ALNUM_RUN.sub(
        lambda m: _ACRONYM_BY_UPPER.get(m.group(0).upper(), m.group(0)), s)
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
    "line": "line", "bar": "bar", "area": "area", "combo": "combo",
    "pie": "pie", "table": "table", "scalar": "scalar",
    "smartscalar": "smart scalar", "funnel": "funnel",
    "map": "map", "waterfall": "waterfall", "row": "row",
    "progress": "progress", "gauge": "gauge", "pivot": "pivot",
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
    if display in DISPLAY_LABEL:
        return DISPLAY_LABEL[display]
    if not display:
        return "?"
    return display.replace("_", " ").lower()


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
            elif normalized and normalized != rec.name:
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


@dataclass(frozen=True)
class Divergence:
    kind: str        # lost_card | archived_card | dashboard_count_changed | moved_card
    card_id: int
    detail: str


def verify_invariant(baseline: dict[int, CardRecord],
                     current: dict[int, CardRecord]) -> list[Divergence]:
    out: list[Divergence] = []
    for cid, base in baseline.items():
        cur = current.get(cid)
        if cur is None:
            out.append(Divergence("lost_card", cid,
                                   f"{base.name!r} absente de l'état courant"))
            continue
        if cur.archived and not base.archived:
            out.append(Divergence("archived_card", cid,
                                   f"{base.name!r} a été archivée"))
        if cur.dashboard_count != base.dashboard_count:
            out.append(Divergence(
                "dashboard_count_changed", cid,
                f"{base.name!r}: dashboard_count "
                f"{base.dashboard_count} -> {cur.dashboard_count}"))
        if cur.collection_id != base.collection_id:
            out.append(Divergence(
                "moved_card", cid,
                f"{base.name!r}: collection {base.collection_id} -> "
                f"{cur.collection_id}"))
    return out
