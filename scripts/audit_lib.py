#!/usr/bin/env python3
"""Logique d'analyse de l'audit instance-wide (pur, testable, aucune I/O réseau).

Empreintes de requête v2, détecteurs de patterns, scoring. Les fonctions opèrent
sur des listes de dicts déjà récupérés par audit.py.

Voir docs/superpowers/specs/2026-05-28-metabase-instance-audit-design.md
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from rename_lib import normalize_name  # noqa: E402  (réutilise la normalisation Phase 1.5)

TEMPLATE_ROOT_ID = 215

# Registre des patterns : scoring Impact/Risque/Effort + vague (cf. spec §6).
PATTERNS = {
    "empty_collections":    {"num": 1,  "family": "structurel", "impact": "H", "risk": "L", "effort": "L", "wave": 0},
    "personal_sprawl":      {"num": 2,  "family": "structurel", "impact": "H", "risk": "H", "effort": "M", "wave": 2},
    "dup_collection_names": {"num": 3,  "family": "structurel", "impact": "M", "risk": "M", "effort": "M", "wave": 2},
    "junk_collections":     {"num": 4,  "family": "structurel", "impact": "M", "risk": "L", "effort": "L", "wave": 0},
    "unused_cards":         {"num": 5,  "family": "gaspillage", "impact": "H", "risk": "L", "effort": "L", "wave": 1},
    "pure_dups":            {"num": 6,  "family": "gaspillage", "impact": "H", "risk": "M", "effort": "M", "wave": 1},
    "archived_backlog":     {"num": 7,  "family": "gaspillage", "impact": "M", "risk": "L", "effort": "L", "wave": 0},
    "template_drift":       {"num": 8,  "family": "dry",        "impact": "H", "risk": "H", "effort": "H", "wave": 3},
    "variant_families":     {"num": 9,  "family": "dry",        "impact": "M", "risk": "M", "effort": "H", "wave": 3},
    "naming_issues":        {"num": 10, "family": "nommage",    "impact": "M", "risk": "L", "effort": "M", "wave": 1},
    "expensive_cards":      {"num": 11, "family": "perf",       "impact": "M", "risk": "L", "effort": "M", "wave": 3},
}


# --- Empreintes v2 -----------------------------------------------------------

def _legacy_query(card):
    """Retourne le legacy_query (dict) ou None.

    Via l'API, `dataset_query` (nouveau format) ressort souvent vide ;
    `legacy_query` (string JSON) porte la requête classique fiable.
    """
    lq = card.get("legacy_query")
    if isinstance(lq, str):
        try:
            lq = json.loads(lq)
        except Exception:
            lq = None
    return lq if isinstance(lq, dict) and lq else None


def query_fingerprint(card):
    """Empreinte de la REQUÊTE seule (SQL/MBQL normalisé + base). Identité logique."""
    lq = _legacy_query(card)
    if lq is None:
        dq = card.get("dataset_query", {}) or {}
        return "ds|" + hashlib.md5(json.dumps(dq, sort_keys=True).encode()).hexdigest()
    db = lq.get("database")
    if lq.get("type") == "native":
        sql = (lq.get("native", {}) or {}).get("query", "") or ""
        norm = re.sub(r"\s+", " ", sql.strip().lower())
        payload = f"native|{db}|{norm}"
    else:
        payload = f"mbql|{db}|" + json.dumps(lq.get("query", {}), sort_keys=True)
    return hashlib.md5(payload.encode()).hexdigest()


def _output_selection(card):
    """Ce que la carte AFFICHE réellement — la clé des faux positifs.

    Graphes : graph.metrics + graph.dimensions. Tables/pivots : colonnes activées.
    """
    vs = card.get("visualization_settings", {}) or {}
    metrics = vs.get("graph.metrics")
    dims = vs.get("graph.dimensions")
    if metrics or dims:
        return json.dumps({"m": sorted(metrics or []), "d": sorted(dims or [])}, sort_keys=True)
    cols = vs.get("table.columns")
    if cols:
        enabled = [c.get("name") for c in cols if isinstance(c, dict) and c.get("enabled", True)]
        return json.dumps({"cols": enabled}, sort_keys=True)
    return ""


def output_fingerprint(card):
    """Empreinte FONCTIONNELLE : requête + display + sélection affichée.

    Même output_fingerprint ⇒ rendu identique ⇒ vrai doublon (#6). Même
    query_fingerprint mais output ≠ (ex. GSC clics/CTR/position) ⇒ variante (#9).
    """
    payload = f"{query_fingerprint(card)}|{card.get('display') or ''}|{_output_selection(card)}"
    return hashlib.md5(payload.encode()).hexdigest()


# --- Classification doublons / variantes -------------------------------------

def classify_query_groups(cards):
    """Classe les cartes partageant une même requête. Enrichit chaque carte de
    'query_fp' et 'output_fp'. Retourne {pure_dups, variant_families, diff_viz}.
    """
    for c in cards:
        c["query_fp"] = query_fingerprint(c)
        c["output_fp"] = output_fingerprint(c)

    by_q = defaultdict(list)
    for c in cards:
        by_q[c["query_fp"]].append(c)

    pure_dups, variant_families, diff_viz = [], [], []
    for _q, group in by_q.items():
        if len(group) < 2:
            continue
        by_out = defaultdict(list)
        for c in group:
            by_out[c["output_fp"]].append(c)
        for _out, sub in by_out.items():
            if len(sub) >= 2:
                pure_dups.append(sub)                 # #6 : rendu identique
        displays = {c.get("display") or "" for c in group}
        if len(by_out) >= 2 and len(displays) == 1:
            variant_families.append(group)            # #9 : même viz, sélection ≠
        if len(displays) >= 2:
            diff_viz.append(group)                    # même logique, viz ≠
    pure_dups.sort(key=len, reverse=True)
    variant_families.sort(key=len, reverse=True)
    return {"pure_dups": pure_dups, "variant_families": variant_families, "diff_viz": diff_viz}


# --- Graphe de sources / cartes inutilisées ----------------------------------

_CARD_SRC_RE = re.compile(r"card__(\d+)")


def build_source_ids(card_details):
    """Ids des cartes référencées comme SOURCE par une autre (`card__<id>`)."""
    source_ids = set()
    for d in card_details:
        lq = d.get("legacy_query")
        lq_blob = lq if isinstance(lq, str) else json.dumps(lq or {})
        blob = json.dumps(d.get("dataset_query", {})) + lq_blob
        for m in _CARD_SRC_RE.findall(blob):
            source_ids.add(int(m))
    return source_ids


def find_unused_cards(cards, source_ids):
    """Cartes 0 dashboard, non archivées, non utilisées comme source (règle 'hors sources')."""
    return [c for c in cards
            if c.get("dashboard_count", 0) == 0
            and not c.get("archived")
            and c["id"] not in source_ids]


# --- Détecteurs de collections -----------------------------------------------

def _is_personal(col):
    return bool(col.get("personal_owner_id"))


def find_empty_collections(collections, cards, dashboards):
    """Collections non-perso sans carte/dashboard actif ET sans descendant occupé."""
    occupied = {c.get("collection_id") for c in cards if not c.get("archived")}
    occupied |= {d.get("collection_id") for d in dashboards if not d.get("archived")}
    occupied.discard(None)

    # ids de toutes les collections-ancêtres d'une collection occupée (via location)
    occupied_ancestors = set()
    for col in collections:
        if col.get("id") in occupied:
            for part in (col.get("location") or "/").strip("/").split("/"):
                if part.isdigit():
                    occupied_ancestors.add(int(part))

    empty = []
    for col in collections:
        cid = col.get("id")
        if _is_personal(col) or cid in occupied or cid in occupied_ancestors:
            continue
        empty.append({"id": cid, "name": col.get("name"), "location": col.get("location") or "/"})
    return empty


_JUNK_RE = re.compile(
    r"\b(to ?sort|[àa] trier|test|tmp|temp|old|draft|brouillon|wip|backup|"
    r"sauvegarde|copy|copie|untitled|sans titre|delete|supprimer)\b", re.I)


def find_junk_collections(collections):
    """Collections non-perso dont le nom évoque du fourre-tout / staging."""
    out = []
    for col in collections:
        if _is_personal(col):
            continue
        name = col.get("name") or ""
        if _JUNK_RE.search(name):
            out.append({"id": col.get("id"), "name": name, "location": col.get("location") or "/"})
    return out


def find_duplicate_collection_names(collections):
    """Noms de collections apparaissant plus d'une fois."""
    names = defaultdict(list)
    for col in collections:
        nm = (col.get("name") or "").strip()
        if nm:
            names[nm].append({"id": col.get("id"),
                              "location": col.get("location") or "/",
                              "personal": _is_personal(col)})
    return [{"name": nm, "count": len(entries), "entries": entries}
            for nm, entries in names.items() if len(entries) > 1]


# --- Sprawl perso / nommage --------------------------------------------------

_CLIENT_PREFIX_RE = re.compile(r"^\s*(.+?)\s*\|\s*.+personal collection\s*$", re.I)


def find_personal_sprawl(collections, cards):
    """Collections personnelles préfixées d'un nom de client (travail client mal logé).

    Retourne des groupes : [{client, count, collections:[...]}].
    """
    by_client = defaultdict(list)
    for col in collections:
        if not _is_personal(col):
            continue
        m = _CLIENT_PREFIX_RE.match(col.get("name") or "")
        if m:
            by_client[m.group(1).strip()].append({"id": col.get("id"), "name": col.get("name")})
    return [{"client": k, "count": len(v), "collections": v} for k, v in sorted(by_client.items())]


def find_naming_issues(cards, template_card_ids):
    """Cartes hors template dont le nom n'est pas normalisé (cf. Phase 1.5)."""
    out = []
    for c in cards:
        if c.get("archived") or c["id"] in template_card_ids:
            continue
        name = c.get("name") or ""
        norm = normalize_name(name)
        if norm and norm != name:
            out.append({"id": c["id"], "name": name, "normalized": norm})
    return out


# --- Dérive template ---------------------------------------------------------

def find_template_drift(template_cards, other_cards):
    """Copies clientes divergentes : même nom normalisé qu'une carte template,
    mais empreinte de requête différente.

    Limite connue : appariement par NOM (rate les copies renommées) — l'audit
    le signale dans le rapport.
    """
    tpl_by_name = {}
    for c in template_cards:
        tpl_by_name.setdefault(normalize_name(c.get("name") or ""), []).append(c)
    drift = []
    for c in other_cards:
        matches = tpl_by_name.get(normalize_name(c.get("name") or ""))
        if not matches:
            continue
        if query_fingerprint(c) != query_fingerprint(matches[0]):
            drift.append({"id": c["id"], "name": c.get("name"),
                          "collection_id": c.get("collection_id"),
                          "template_id": matches[0]["id"]})
    return drift


# --- Scoring / agrégation ----------------------------------------------------

def summarize_findings(findings):
    """Joint le scoring (PATTERNS) à chaque finding et trie par vague puis compte décroissant.

    findings : {pattern_key: {count, items}}. Retourne une liste de dicts plats.
    """
    out = []
    for key, data in findings.items():
        meta = PATTERNS.get(key, {})
        out.append({"key": key, **meta, "count": data.get("count", 0), "items": data.get("items", [])})
    out.sort(key=lambda f: (f.get("wave", 9), -f.get("count", 0)))
    return out
