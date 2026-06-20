#!/usr/bin/env python3
"""Logique pure de la BASCULE du filtre temps d'un dashboard :
param 'Time period' (category -> tags dimension sur TIME_PERIODS.NAME, l'ancien trick)
vers un param 'temporal-unit' (-> tags temporal-unit des cartes).

Principe (validé avec l'utilisateur) : la bascule est PAR DASHBOARD et atomique —
jamais deux filtres temps en état final. Pré-condition : toutes les cartes câblées
au filtre temps doivent être prêtes (tag temporal-unit), via swap vers une carte de
remplacement (11673 ou copie sandbox). Le param est remplacé SUR PLACE (même id),
donc les parameter_mappings existants restent valides sans recâblage.

Testé par tests/test_bascule_lib.py.
"""

TIME_TAG = "time_period"
TIME_TARGET = ["dimension", ["template-tag", TIME_TAG]]
TEMPORAL_UNITS = ["day", "week", "month", "quarter", "year"]


def time_param_payload(tags, value):
    """Paramètre d'exécution (POST /query) pour épingler la granularité d'une carte,
    selon le mécanisme de SON tag time_period. None si pas pilotable (absent, ou
    variable texte — l'ancien mécanisme cassé)."""
    tag = (tags or {}).get(TIME_TAG) or {}
    t = tag.get("type")
    if t == "dimension":
        return {"type": "category", "value": [value], "target": TIME_TARGET}
    if t == "temporal-unit":
        return {"type": "temporal-unit", "value": value, "target": TIME_TARGET}
    return None


def find_time_param(dashboard):
    """L'ancien param 'Time period' (type category) du dashboard, sinon None."""
    for p in dashboard.get("parameters") or []:
        if p.get("type") != "category":
            continue
        if p.get("slug") == TIME_TAG or str(p.get("name", "")).strip().lower() == "time period":
            return p
    return None


def build_temporal_unit_param(old_param):
    """Nouveau param temporal-unit, MÊME id que l'ancien (les mappings survivent).
    Défaut conservé (week sur les dashboards existants). L'ancien défaut category
    est une LISTE (['week']) — temporal-unit attend une string."""
    default = old_param.get("default")
    if isinstance(default, (list, tuple)):
        default = default[0] if default else None
    return {
        "id": old_param["id"],
        "name": old_param.get("name") or "Time period",
        "slug": old_param.get("slug") or TIME_TAG,
        "type": "temporal-unit",
        "sectionId": "temporal-unit",
        "temporal_units": list(TEMPORAL_UNITS),
        "default": default or "week",
    }


def _dcs(dashboard):
    return dashboard.get("dashcards") or dashboard.get("ordered_cards") or []


def bascule_plan(dashboard, tags_by_card, swaps=None):
    """Classe chaque dashcard vis-à-vis du filtre temps. Pure (pas d'API).

    tags_by_card : {card_id: template-tags dict} pour toutes les cartes du dashboard
    swaps        : {old_card_id: new_card_id} résolutions déjà connues (registre) —
                   le new_card_id doit figurer dans tags_by_card.

    Retourne None si le dashboard n'a pas d'ancien param temps, sinon :
      old_param / new_param,
      swaps         {old->new} repris tels quels,
      blockers      [{dashcard_id, card_id, reason}]  câblées non prêtes, non résolues,
      dead_mappings [(dashcard_id, parameter_id)]     mapping temps vers carte sans tag,
      to_wire       [(dashcard_id, card_id)]          cartes temporal-unit non câblées.
    """
    old_param = find_time_param(dashboard)
    if not old_param:
        return None
    swaps = dict(swaps or {})
    pid = old_param["id"]
    blockers, dead, to_wire = [], [], []
    for dc in _dcs(dashboard):
        cid = dc.get("card_id")
        if not cid:
            continue
        tags = tags_by_card.get(cid) or {}
        tag_type = ((tags.get(TIME_TAG) or {}).get("type"))
        wired = any(pm.get("parameter_id") == pid for pm in dc.get("parameter_mappings") or [])
        if wired:
            if tag_type == "temporal-unit":
                continue  # déjà prête, mapping conservé
            if tag_type is None:
                dead.append((dc["id"], pid))
            elif cid in swaps:
                continue  # sera swappée vers une carte prête
            else:
                blockers.append({"dashcard_id": dc["id"], "card_id": cid,
                                 "reason": f"tag time_period type={tag_type!r} sans remplacement"})
        else:
            if tag_type == "temporal-unit":
                to_wire.append((dc["id"], cid))
    return {"old_param": old_param, "new_param": build_temporal_unit_param(old_param),
            "swaps": swaps, "blockers": blockers, "dead_mappings": dead, "to_wire": to_wire}


def apply_bascule(dashboard, plan):
    """(parameters, dashcards) prêts pour le PUT. Pure : ne modifie pas les entrées.
    Refuse (ValueError) si le plan a encore des blockers."""
    import json as _json
    if plan["blockers"]:
        raise ValueError(f"blockers non résolus: {plan['blockers']}")
    pid = plan["old_param"]["id"]
    dead = set(plan["dead_mappings"])
    wire = dict(plan["to_wire"])
    swaps = plan["swaps"]

    params = [_json.loads(_json.dumps(p)) for p in dashboard.get("parameters") or []]
    params = [plan["new_param"] if p.get("id") == pid else p for p in params]

    dcs = []
    for dc in _dcs(dashboard):
        nd = _json.loads(_json.dumps(dc))
        cid = nd.get("card_id")
        if cid in swaps:
            new_cid = swaps[cid]
            nd["card_id"] = new_cid
            for pm in nd.get("parameter_mappings") or []:
                pm["card_id"] = new_cid
        nd["parameter_mappings"] = [
            pm for pm in nd.get("parameter_mappings") or []
            if (nd["id"], pm.get("parameter_id")) not in dead
        ]
        if nd.get("id") in wire:
            nd["parameter_mappings"].append(
                {"parameter_id": pid, "card_id": wire[nd["id"]], "target": list(TIME_TARGET)})
        dcs.append(nd)
    return params, dcs
