#!/usr/bin/env python3
"""Logique pure du déploiement des cartes « sélecteur » de conversion.

Cas #87 « Social ad metric (filter choice) by date » -> carte 49788 (résolue sans
table, cf. docs). La carte NEW remplace le sélecteur de métrique par une **Text
variable** (`{{metric}}`) au lieu de l'ancien field-filter (`dimension`). Déployer
la carte sur un dashboard exige donc, EN PLUS du swap de la carte :
  (a) re-pointer chaque parameter_mapping de la carte 87 vers 49788 ;
  (b) RETARGETER le mapping du filtre Metric : `dimension` -> `variable`
      (la valeur passe alors DIRECT au SQL, comme une Text variable) ;
  (c) poser la **custom list** (libellés des conversions nommées) sur le filtre
      Metric du DASHBOARD (sinon le dropdown ne montre pas les nommées) ;
  (d) dropper tout mapping vers une template-tag absente de la carte NEW.

Tout est pur (aucune API) -> testé par tests/test_special_cards_lib.py.
Le driver live = scripts/deploy_special_cards.py.
"""
import json
import conv_lib

VARIABLE_TAG = "metric"


def _clone(x):
    return json.loads(json.dumps(x))


def _dcs(dashboard):
    return dashboard.get("dashcards") or dashboard.get("ordered_cards") or []


def _card_id(dc):
    """id de carte d'un dashcard, robuste à la forme {card:{id}} sans clé card_id."""
    return dc.get("card_id") or (dc.get("card") or {}).get("id")


def _target_tag(target):
    """Nom de la template-tag d'un target `[dimension|variable, [template-tag, <name>], ...]`."""
    if (isinstance(target, list) and len(target) >= 2 and isinstance(target[1], list)
            and len(target[1]) == 2 and target[1][0] == "template-tag"):
        return target[1][1]
    return None


def selector_dashcards(dashboard, old_card_id):
    """Les dashcards du dashboard qui référencent la carte sélecteur (old)."""
    return [dc for dc in _dcs(dashboard) if _card_id(dc) == old_card_id]


def dashcard_metric_pid(dc, variable_tag=VARIABLE_TAG):
    """Le parameter_id qui pilote le tag metric sur CE dashcard (sinon None).
    Sert à vérifier chaque tuile avec SON propre filtre Metric (cas multi-filtres)."""
    for pm in dc.get("parameter_mappings") or []:
        if _target_tag(pm.get("target")) == variable_tag:
            return pm.get("parameter_id")
    return None


def metric_driven_dashcards(dashboard, old_card_id, variable_tag=VARIABLE_TAG):
    """Dashcards carte old dont un mapping pilote le tag metric = vraies tuiles « sélecteur »
    (client-agnostiques, batch-safe). On ne swappe QUE celles-là."""
    return [dc for dc in selector_dashcards(dashboard, old_card_id)
            if any(_target_tag(pm.get("target")) == variable_tag
                   for pm in dc.get("parameter_mappings") or [])]


def fixed_metric_dashcards(dashboard, old_card_id, variable_tag=VARIABLE_TAG):
    """Dashcards carte old SANS mapping metric = métrique FIXE (défaut de la carte). À NE PAS
    swapper en batch : 49788 a un défaut différent et la cible nommée est client-spécifique
    (cac -> cac_<conversion mappée>). Laissées sur l'ancienne carte, reportées pour passe par client."""
    driven = {id(dc) for dc in metric_driven_dashcards(dashboard, old_card_id, variable_tag)}
    return [dc for dc in selector_dashcards(dashboard, old_card_id) if id(dc) not in driven]


def metric_param_ids(dashboard, old_card_id, variable_tag=VARIABLE_TAG):
    """Ids des params du DASHBOARD mappés à la tag `variable_tag` sur les dashcards old
    = les filtres « Metric » à équiper de la custom list et dont le target doit basculer."""
    out = set()
    for dc in selector_dashcards(dashboard, old_card_id):
        for pm in dc.get("parameter_mappings") or []:
            if _target_tag(pm.get("target")) == variable_tag:
                out.add(pm.get("parameter_id"))
    return out


def foreign_metric_consumers(dashboard, metric_pids, old_card_id):
    """Garde-fou : dashcards (carte != old) qui mappent AUSSI un filtre Metric. Si non vide,
    équiper ce filtre d'une custom list de conversions nommées risque de casser ces cartes
    -> le driver doit STOP. Retourne [(dashcard_id, card_id)]."""
    out = []
    for dc in _dcs(dashboard):
        cid = _card_id(dc)
        if cid is None or cid == old_card_id:
            continue
        for pm in dc.get("parameter_mappings") or []:
            if pm.get("parameter_id") in metric_pids:
                out.append((dc.get("id"), cid))
                break
    return out


def rewrite_selector_dashcard(dc, old_id, new_id, metric_pids, new_tags, variable_tag=VARIABLE_TAG):
    """NOUVEAU dashcard : card_id old->new, mappings re-pointés vers new, le mapping Metric
    basculé dimension->variable, et les mappings vers une tag absente de la carte NEW droppés.
    Pur (deep-copy ; n'altère pas l'entrée)."""
    nd = _clone(dc)
    nd["card_id"] = new_id
    pms = []
    for pm in nd.get("parameter_mappings") or []:
        tag = _target_tag(pm.get("target"))
        if tag is not None and tag not in new_tags:
            continue  # tag inexistante côté NEW -> mapping pendouillant droppé
        pm["card_id"] = new_id
        if tag == variable_tag and pm.get("parameter_id") in metric_pids:
            pm["target"] = ["variable", ["template-tag", variable_tag]]
        pms.append(pm)
    nd["parameter_mappings"] = pms
    # dashcard « visualizer » : repointer les réfs "card:<old>" vers la carte NEW (sinon tuile vide)
    if nd.get("visualization_settings"):
        nd["visualization_settings"] = conv_lib.repoint_visualizer_source(
            nd["visualization_settings"], old_id, new_id)
    return nd


def replacement_ids(registry_entries):
    """new_ids des cartes spéciales DÉJÀ migrées (#87->49788, #4854->49755…) depuis les entrées
    du registre tu-generic-*.json (vérifiées). À NE PAS retraiter par generate_fallback : leur SQL
    référence des colonnes CONVERSIONS (dans le grand CASE) mais elles AFFICHENT du nommé — ce ne
    sont donc PAS des tuiles « restées sur l'ancien »."""
    return {int(e["new_id"]) for e in (registry_entries or []) if e.get("verified") and e.get("new_id")}


def source_tokens(source_param):
    """Tokens (valeurs SQL) de la custom list de la carte NEW. Tolère les deux formes :
    paires [token, label] ou strings simples."""
    return [v[0] if isinstance(v, (list, tuple)) else v
            for v in (source_param.get("values_source_config") or {}).get("values", [])]


def _unwrap(default):
    if isinstance(default, (list, tuple)):
        return default[0] if default else None
    return default


def equip_metric_param(dash_param, source_param, new_tokens):
    """NOUVEAU param de DASHBOARD portant la custom list des conversions nommées.
    - static-list + values_query_type=list + single-select (recette validée live) ;
    - type conservé (category) ;
    - default : on garde l'ancien s'il reste un token valide, sinon celui de la carte NEW."""
    np = _clone(dash_param)
    np["values_source_type"] = "static-list"
    np["values_source_config"] = _clone(source_param.get("values_source_config") or {})
    np["values_query_type"] = "list"
    np["isMultiSelect"] = False
    old_def = _unwrap(dash_param.get("default"))
    np["default"] = old_def if old_def in set(new_tokens) else _unwrap(source_param.get("default"))
    return np


def apply_selector_deploy(dashboard, old_id, new_id, new_tags, source_param, variable_tag=VARIABLE_TAG):
    """(parameters, dashcards) prêts pour le PUT. Pur.
    new_tags     : set des template-tags de la carte NEW.
    source_param : le param `metric` de la carte NEW (custom list source).
    Lève ValueError si la carte old n'est pas sur le dashboard."""
    if not any(_card_id(dc) == old_id for dc in _dcs(dashboard)):
        raise ValueError(f"carte {old_id} absente du dashboard")
    pids = metric_param_ids(dashboard, old_id, variable_tag)
    toks = source_tokens(source_param)
    # on ne swappe QUE les tuiles sélecteur (metric piloté) ; les tuiles à métrique fixe
    # restent sur l'ancienne carte (cible nommée client-spécifique -> passe par client).
    driven = {id(dc) for dc in metric_driven_dashcards(dashboard, old_id, variable_tag)}

    out_dcs = []
    for dc in _dcs(dashboard):
        if id(dc) in driven:
            out_dcs.append(rewrite_selector_dashcard(dc, old_id, new_id, pids, new_tags, variable_tag))
        else:
            out_dcs.append(_clone(dc))

    out_params = []
    for p in dashboard.get("parameters") or []:
        out_params.append(equip_metric_param(p, source_param, toks) if p.get("id") in pids else _clone(p))
    return out_params, out_dcs
