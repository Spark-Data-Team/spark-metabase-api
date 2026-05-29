#!/usr/bin/env python3
"""Logique pure du swap de carte sur dashboards (réécriture de dashcards). Aucune I/O.

Remplace une carte `old` par sa canonique `new` dans des dashcards : `card_id`,
les `parameter_mappings` (le `target` — qui pointe un template-tag par NOM — reste
valide car les cartes partagent la même empreinte fonctionnelle), et les `series`.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from audit_lib import output_fingerprint, _legacy_query  # noqa: E402


def _target_tag(target):
    """Nom du template-tag d'un `target` de mapping, ex. ['dimension',['template-tag','date'],…]."""
    try:
        inner = target[1]
        if isinstance(inner, list) and len(inner) >= 2 and inner[0] == "template-tag":
            return inner[1]
    except Exception:
        pass
    return None


def referenced_template_tags(dashcards, card_id):
    """Template-tags du dashboard câblés vers `card_id` (les filtres à préserver)."""
    tags = set()
    for dc in dashcards:
        for pm in dc.get("parameter_mappings") or []:
            if pm.get("card_id") == card_id:
                t = _target_tag(pm.get("target"))
                if t:
                    tags.add(t)
    return tags


def rewrite_dashcards(dashcards, old_id, new_id):
    """Retourne (dashcards réécrits, nb de dashcards modifiés). N'altère pas l'entrée."""
    out = copy.deepcopy(dashcards)
    n = 0
    for dc in out:
        changed = False
        if dc.get("card_id") == old_id:
            dc["card_id"] = new_id
            changed = True
        for pm in dc.get("parameter_mappings") or []:
            if pm.get("card_id") == old_id:
                pm["card_id"] = new_id  # target inchangé (pointe le tag par nom)
                changed = True
        for s in dc.get("series") or []:
            if isinstance(s, dict):
                if s.get("id") == old_id:
                    s["id"] = new_id
                    changed = True
                if s.get("card_id") == old_id:
                    s["card_id"] = new_id
                    changed = True
        if changed:
            n += 1
    return out, n


def card_template_tags(card):
    """Noms des template-tags de la requête native de la carte."""
    lq = _legacy_query(card)
    if not lq:
        return set()
    tags = (lq.get("native", {}) or {}).get("template-tags", {}) or {}
    return set(tags.keys())


def swap_safety_check(old_card, new_card, referenced_tags):
    """Liste des raisons de NE PAS faire le swap (vide = sûr)."""
    if not isinstance(new_card, dict):
        return ["carte canonique introuvable"]
    problems = []
    if new_card.get("archived"):
        problems.append("la canonique est archivée")
    odb, ndb = old_card.get("database_id"), new_card.get("database_id")
    if odb is not None and ndb is not None and odb != ndb:
        problems.append(f"bases différentes ({odb} vs {ndb})")
    if output_fingerprint(old_card) != output_fingerprint(new_card):
        problems.append("empreinte fonctionnelle différente (rendu non identique)")
    missing = referenced_tags - card_template_tags(new_card)
    if missing:
        problems.append(f"la canonique ne couvre pas les filtres: {sorted(missing)}")
    return problems
