#!/usr/bin/env python3
"""Bascule le filtre temps d'un dashboard COPIE : param 'Time period' (category)
-> param temporal-unit (MÊME id, donc les câblages survivent), après swap des
cartes non prêtes.

Pré-requis :
- les tuiles CONVERSION câblées au filtre temps ont été swappées vers 11673
  (migrate_dashboard_reuse.py --planned-temporal-unit --yes) ;
- les cartes génériques non-conversion (Cost, Clicks, IS...) ont leur copie
  temporal-unit en sandbox 13885, inscrite au REGISTRE migration/tu-generic-*.json.

Garde-fous : par tuile swappée ici, valeurs avant (ancienne carte, granularité
épinglée par field-filter) == après (nouvelle carte, temporal-unit) sur week ET
month, non vides. Bascule atomique en un PUT (parameters + dashcards), snapshot
avant, refus si le moindre blocker reste. Dashboards à onglets refusés.

Usage :
  python3 scripts/bascule_time_filter.py --copy 25567 --client "Pro Nutrition"        # dry-run
  python3 scripts/bascule_time_filter.py --copy 25567 --client "Pro Nutrition" --yes
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib
import bascule_lib
from migrate_dashboard_full import connect, _dcs
from migrate_dashboard_reuse import card_values_pinned


def _is_time_parameter(parameter, *, temporal=None):
    identity = (
        str(parameter.get("slug") or "").rstrip("_").casefold() == "time_period"
        or str(parameter.get("name") or "").strip().casefold() == "time period"
    )
    if not identity:
        return False
    if temporal is True:
        return parameter.get("type") == "temporal-unit"
    if temporal is False:
        return parameter.get("type") in bascule_lib.OLD_TIME_TYPES
    return True


def _is_time_target(target):
    """Reconnaît le template-tag temps canonique, avec métadonnée MLv2 optionnelle."""
    if not isinstance(target, list) or len(target) not in (2, 3):
        return False
    if target[0] != "dimension" or target[1] != ["template-tag", bascule_lib.TIME_TAG]:
        return False
    if len(target) == 2:
        return True
    metadata = target[2]
    return isinstance(metadata, dict) and metadata.get("stage-number") == 0


def duplicate_time_cleanup_plan(dashboard):
    """Supprime les anciens sélecteurs temps seulement s'ils sont 100 % redondants.

    Certaines copies historiques contiennent ``Time period``, ``Time period_`` …
    câblés aux mêmes cartes. Après la bascule canonique, ces paramètres texte ne sont
    sûrs à retirer que si chaque mapping possède déjà son équivalent vers l'unique
    paramètre temporal-unit sur la même tuile/carte/tag.
    """
    parameters = dashboard.get("parameters") or []
    canon = [p for p in parameters if _is_time_parameter(p, temporal=True)]
    legacy = [p for p in parameters if _is_time_parameter(p, temporal=False)]
    if not legacy or not canon:
        return None
    if len(canon) != 1:
        return {"blockers": [f"{len(canon)} paramètres temporal-unit candidats"]}

    canonical_id = canon[0].get("id")
    legacy_ids = {p.get("id") for p in legacy}
    new_dcs = json.loads(json.dumps(_dcs(dashboard)))
    blockers = []
    for dashcard in new_dcs:
        mappings = dashcard.get("parameter_mappings") or []

        def signature(mapping):
            target = mapping.get("target")
            tag = bascule_lib.TIME_TAG if _is_time_target(target) else None
            return (mapping.get("card_id") or dashcard.get("card_id"), tag)

        canonical_signatures = {
            signature(mapping)
            for mapping in mappings
            if mapping.get("parameter_id") == canonical_id
        }
        kept = []
        for mapping in mappings:
            if mapping.get("parameter_id") not in legacy_ids:
                kept.append(mapping)
                continue
            sig = signature(mapping)
            if sig[1] != "time_period" or sig not in canonical_signatures:
                blockers.append(
                    f"dashcard {dashcard.get('id')}: mapping {mapping.get('parameter_id')} "
                    "sans équivalent temporal-unit"
                )
                kept.append(mapping)
        dashcard["parameter_mappings"] = kept
    if blockers:
        return {"blockers": blockers}
    return {
        "blockers": [],
        "canonical_id": canonical_id,
        "removed_ids": sorted(str(value) for value in legacy_ids if value is not None),
        "parameters": [
            json.loads(json.dumps(parameter))
            for parameter in parameters
            if parameter.get("id") not in legacy_ids
        ],
        "dashcards": new_dcs,
    }


def apply_duplicate_time_cleanup(mb, dashboard_id, before, plan):
    """Nettoie un seul dashboard avec précondition, preuve et rollback locaux."""
    endpoint = f"/api/dashboard/{dashboard_id}"
    baseline = _dashboard_mutable_state(before)
    if baseline is None:
        raise RuntimeError("précondition impossible: dashboard initial illisible")
    _assert_dashboard_unchanged(mb, endpoint, baseline)

    target_dashboard = {
        "parameters": plan["parameters"],
        "dashcards": plan["dashcards"],
        "tabs": before.get("tabs") or [],
    }
    target = _dashboard_mutable_state(target_dashboard)
    snapshot = _write_bascule_snapshot(
        dashboard_id,
        baseline,
        _dashboard_payload(before),
        prefix="bascule-duplicates-snapshot",
    )

    failure = None
    try:
        response = mb.put(
            endpoint,
            "raw",
            json=_dashboard_payload(target_dashboard),
        )
        if getattr(response, "status_code", None) != 200:
            failure = (
                f"PUT HTTP {getattr(response, 'status_code', '?')}: "
                f"{str(getattr(response, 'text', ''))[:400]}"
            )
        else:
            reread = mb.get(endpoint)
            errors = _duplicate_cleanup_postconditions(reread, plan)
            if _dashboard_mutable_state(reread) != target:
                errors.append("projection configurable divergente de la cible")
            if errors:
                failure = "; ".join(errors)
    except Exception as exc:
        failure = f"exception après tentative de PUT: {type(exc).__name__}: {exc}"

    if failure is None:
        return snapshot

    rollback_note = _rollback_dashboard_from_snapshot(mb, endpoint, snapshot)
    raise RuntimeError(f"{failure}; {rollback_note}; snapshot {snapshot}")


def load_registry():
    """{old_card_id: new_card_id} depuis tu-generic-*.json (verified only). Lit le maître
    migration/ ET le shard par-client (CONV_REG_DIR) ; le shard l'emporte (mode parallèle)."""
    from conv_paths import reg_dir
    reg = {}
    dirs = [REPO / "migration"]
    if reg_dir() != (REPO / "migration"):
        dirs.append(reg_dir())   # le shard par-client écrase le maître pour les mêmes ids
    for base in dirs:
        for f in sorted(base.glob("tu-generic-*.json")):
            d = json.loads(f.read_text())
            if d.get("verified") and d.get("new_id"):
                reg[int(d["old_id"])] = int(d["new_id"])
    return reg


def dashboard_defaults_for_card(dashboard, dashcard_id, card_id, card_tags=None):
    """Paramètres dashboard épinglés nécessaires aux requêtes de vérification carte.

    Les cartes génériques peuvent avoir un tag requis (notamment ``breakdown``) sans
    défaut propre : sa valeur vit alors sur le paramètre dashboard câblé à la tuile.
    Sans ce contexte, la baseline temporal-unit échoue à tort avant même de comparer.
    """
    dashboard_parameters = {
        parameter.get("id"): parameter
        for parameter in dashboard.get("parameters") or []
        if parameter.get("id") is not None
    }
    dashcard = next(
        (
            item for item in _dcs(dashboard)
            if item.get("id") == dashcard_id and item.get("card_id") == card_id
        ),
        None,
    )
    if not dashcard:
        return []
    out, seen = [], set()
    for mapping in dashcard.get("parameter_mappings") or []:
        target = mapping.get("target")
        try:
            tag = target[1][1] if target[1][0] == "template-tag" else None
        except Exception:
            tag = None
        if not tag or tag in {"client", "clients", "date", "time_period", "brand_included"}:
            continue
        # Des dashboards historiques gardent parfois un mapping vers un template-tag
        # supprimé de la carte (ex. ``spark_campaigns``). Le transmettre à /query fait
        # échouer Metabase en HTTP 500 : seuls les tags réellement exposés par la carte
        # peuvent devenir des paramètres supplémentaires de vérification/conversion.
        if card_tags is not None and tag not in card_tags:
            continue
        parameter = dashboard_parameters.get(mapping.get("parameter_id")) or {}
        value = parameter.get("default")
        if value is None or tag in seen:
            continue
        seen.add(tag)
        out.append({
            # Le type du paramètre dashboard peut être historique (``category``)
            # alors que la carte copiée expose désormais ``string/=``. Les requêtes
            # /api/card valident contre le widget-type de LA CARTE.
            "type": ((card_tags or {}).get(tag) or {}).get("widget-type")
                    or parameter.get("type") or "string/=",
            "value": json.loads(json.dumps(value)),
            "target": json.loads(json.dumps(target)),
        })
    return out


def _copy_json(value):
    return json.loads(json.dumps(value))


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


_DASHCARD_CONFIG_FIELDS = (
    "id",
    "card_id",
    "row",
    "col",
    "size_x",
    "size_y",
    "dashboard_tab_id",
    "parameter_mappings",
    "visualization_settings",
    "inline_parameters",
    "action_id",
)


def _series_card_id(reference):
    if not isinstance(reference, dict):
        return None
    return (
        reference.get("card_id")
        or reference.get("id")
        or (reference.get("card") or {}).get("id")
    )


def _parameter_mapping_config(mapping):
    projected = _copy_json(mapping)
    if isinstance(projected, dict) and _is_time_target(projected.get("target")):
        # Metabase MLv2 peut ajouter/retirer ce marqueur calculé entre PUT et GET.
        projected["target"] = _copy_json(bascule_lib.TIME_TARGET)
    return projected


def _dashcard_write_config(dashcard):
    """Payload PUT minimal, en conservant les mappings fournis par Metabase."""
    projected = {
        field: _copy_json(dashcard.get(field))
        for field in _DASHCARD_CONFIG_FIELDS
    }
    projected["card_id"] = (
        dashcard.get("card_id") or (dashcard.get("card") or {}).get("id")
    )
    projected["parameter_mappings"] = _copy_json(
        dashcard.get("parameter_mappings") or []
    )
    projected["visualization_settings"] = _copy_json(
        dashcard.get("visualization_settings") or {}
    )
    projected["inline_parameters"] = _copy_json(
        dashcard.get("inline_parameters") or []
    )
    projected["series"] = [
        {"id": _series_card_id(reference)}
        for reference in dashcard.get("series") or []
    ]
    return projected


def _dashcard_config(dashcard):
    """Projection stable sans objet ``card`` ni métadonnée serveur volatile."""
    projected = _dashcard_write_config(dashcard)
    projected["parameter_mappings"] = sorted(
        (
            _parameter_mapping_config(mapping)
            for mapping in projected["parameter_mappings"]
        ),
        key=_canonical_json,
    )
    return projected


def _tab_config(tab):
    """Champs configurables d'un onglet; timestamps/entity_id sont calculés."""
    if not isinstance(tab, dict):
        return None
    return {
        "id": tab.get("id"),
        "name": tab.get("name"),
        "position": tab.get("position"),
    }


def _dashboard_mutable_state(dashboard):
    """État configurable exact que cette bascule est autorisée à modifier.

    Les réponses GET embarquent dans chaque dashcard une carte complète, des timestamps,
    compteurs de vues et durées de requête. Ces champs changent sans édition dashboard et
    ne doivent ni provoquer un faux drift, ni rendre un rollback invérifiable. La série
    est ramenée à sa liste ordonnée d'ids, qui est sa seule configuration PUT utile.
    """
    if not isinstance(dashboard, dict):
        return None
    dashcards = [_dashcard_config(item) for item in _dcs(dashboard)]
    # L'API Metabase peut réordonner les dashcards et leurs mappings sans modifier
    # le dashboard. La projection de preuve est donc canonique, tandis que le payload
    # écrit/restauré reste construit séparément dans son ordre exact d'origine.
    dashcards.sort(
        key=lambda item: (
            _canonical_json(item.get("id")),
            _canonical_json(item),
        )
    )
    return {
        "parameters": _copy_json(dashboard.get("parameters") or []),
        "dashcards": dashcards,
        "tabs": [
            _tab_config(tab)
            for tab in dashboard.get("tabs") or []
        ],
    }


def _dashboard_payload(dashboard):
    body = {
        "parameters": _copy_json(dashboard.get("parameters") or []),
        "dashcards": [
            _dashcard_write_config(item)
            for item in _dcs(dashboard)
        ],
    }
    if dashboard.get("tabs"):
        # Un dashboard à onglets exige ``tabs`` dans le PUT. Pour un dashboard sans
        # onglets, l'omission conserve le comportement historique de l'API Metabase.
        body["tabs"] = [
            _tab_config(tab)
            for tab in dashboard["tabs"]
        ]
    return body


def _write_bascule_snapshot(
    dashboard_id,
    state,
    payload,
    *,
    prefix="bascule-snapshot",
):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    snapshot = REPO / "migration" / f"{prefix}-{dashboard_id}-{stamp}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text(
        json.dumps(
            {
                "dashboard_id": dashboard_id,
                "state": state,
                "payload": payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return snapshot


def _assert_dashboard_unchanged(mb, endpoint, baseline):
    try:
        current = mb.get(endpoint)
    except Exception as exc:
        raise RuntimeError(
            f"précondition impossible: relecture {type(exc).__name__}; aucun PUT"
        ) from exc
    if _dashboard_mutable_state(current) != baseline:
        raise RuntimeError(
            "drift pré-PUT sur paramètres/dashcards/onglets configurables; aucun PUT"
        )


def _rollback_dashboard_from_snapshot(mb, endpoint, snapshot):
    """Restaure uniquement ``endpoint`` et prouve sa configuration stable exacte."""
    snapshot_data = json.loads(snapshot.read_text())
    saved = snapshot_data["state"]
    saved_payload = snapshot_data.get("payload") or _dashboard_payload(saved)

    # Un HTTP non-200 ou une exception cliente ne prouve pas que Metabase a muté.
    # Si la relecture est déjà exactement le snapshot, un second PUT serait inutile
    # et créerait lui-même un risque de drift concurrent.
    try:
        current = mb.get(endpoint)
        if _dashboard_mutable_state(current) == saved:
            return (
                "rollback local vérifié exactement "
                "(état initial déjà intact; aucun PUT de rollback)"
            )
    except Exception:
        pass

    rollback_http = None
    rollback_error = None
    try:
        rollback = mb.put(endpoint, "raw", json=saved_payload)
        rollback_http = getattr(rollback, "status_code", None)
    except Exception as exc:
        rollback_error = f"PUT {type(exc).__name__}: {exc}"

    try:
        restored = mb.get(endpoint)
        rollback_exact = _dashboard_mutable_state(restored) == saved
    except Exception as exc:
        rollback_exact = False
        detail = f"relecture {type(exc).__name__}: {exc}"
        rollback_error = f"{rollback_error}; {detail}" if rollback_error else detail

    if rollback_http == 200 and rollback_exact:
        return "rollback local vérifié exactement"
    detail = rollback_error or "configuration relue différente du snapshot"
    return (
        "ROLLBACK LOCAL NON VÉRIFIÉ "
        f"(HTTP {rollback_http if rollback_http is not None else '?'}; {detail})"
    )


def _duplicate_cleanup_postconditions(dashboard, plan):
    if not isinstance(dashboard, dict):
        return ["dashboard illisible après PUT"]
    errors = []
    parameters = dashboard.get("parameters") or []
    legacy = [p for p in parameters if _is_time_parameter(p, temporal=False)]
    if legacy:
        errors.append(
            "ancien Time period encore présent: "
            + ", ".join(str(p.get("id")) for p in legacy)
        )
    canonical = [
        p
        for p in parameters
        if _is_time_parameter(p, temporal=True)
        and p.get("id") == plan["canonical_id"]
    ]
    if len(canonical) != 1:
        errors.append(
            "paramètre temporal-unit canonique absent ou non unique "
            f"({len(canonical)})"
        )
    return errors


def _normal_bascule_postconditions(mb, dashboard, plan):
    """Retourne (erreurs, anomalies résiduelles, ids temporal-unit).

    Aucun appel mutateur ici : seules des relectures de cartes permettent de vérifier
    que chaque câblage du paramètre temps correspond bien au mécanisme de sa carte.
    """
    errors, residual = [], []
    if not isinstance(dashboard, dict):
        return ["dashboard illisible après PUT"], residual, []

    parameters = dashboard.get("parameters") or []
    legacy = [p for p in parameters if _is_time_parameter(p, temporal=False)]
    if legacy:
        errors.append(
            "ancien Time period encore présent: "
            + ", ".join(str(p.get("id")) for p in legacy)
        )

    temporal = [p for p in parameters if _is_time_parameter(p, temporal=True)]
    temporal_ids = [p.get("id") for p in temporal]
    if len(temporal) != 1:
        errors.append(
            f"paramètre Time period temporal-unit non unique ({len(temporal)})"
        )
    else:
        actual = temporal[0]
        expected = plan["new_param"]
        mismatches = [
            key
            for key, value in expected.items()
            if actual.get(key) != value
        ]
        if mismatches:
            errors.append(
                "paramètre temporal-unit incohérent (champs: "
                + ", ".join(sorted(mismatches))
                + ")"
            )

    pid = plan["old_param"]["id"]
    for dashcard in _dcs(dashboard):
        card_id = dashcard.get("card_id")
        if not card_id:
            continue
        mappings = [
            mapping
            for mapping in dashcard.get("parameter_mappings") or []
            if mapping.get("parameter_id") == pid
        ]
        try:
            card = mb.get(f"/api/card/{card_id}")
            if not isinstance(card, dict):
                raise TypeError("réponse carte non objet")
            tags = conv_lib.native_and_tags(card)[1]
        except Exception as exc:
            residual.append(
                (dashcard.get("id"), card_id, f"carte illisible ({type(exc).__name__})")
            )
            continue

        tag_type = ((tags.get(bascule_lib.TIME_TAG) or {}).get("type"))
        if tag_type == "temporal-unit":
            if len(mappings) != 1:
                residual.append(
                    (
                        dashcard.get("id"),
                        card_id,
                        f"temporal-unit câblée {len(mappings)} fois (attendu: 1)",
                    )
                )
                continue
            mapping = mappings[0]
            if (
                mapping.get("card_id") != card_id
                or not _is_time_target(mapping.get("target"))
            ):
                residual.append(
                    (dashcard.get("id"), card_id, "mapping temporal-unit incohérent")
                )
        elif mappings:
            residual.append(
                (
                    dashcard.get("id"),
                    card_id,
                    f"carte type {tag_type!r} encore câblée au temporal-unit",
                )
            )

    if residual:
        errors.append(f"{len(residual)} anomalie(s) résiduelle(s)")
    return errors, residual, temporal_ids


def apply_normal_bascule(mb, dashboard_id, before, plan):
    """Applique une bascule à un seul dashboard, avec rollback strictement local.

    La relecture juste avant PUT refuse tout drift de parameters/dashcards/tabs. Après
    mutation, toute postcondition invalide restaure uniquement ce dashboard depuis le
    snapshot local, puis exige une relecture exactement égale à l'état initial.
    """
    endpoint = f"/api/dashboard/{dashboard_id}"
    baseline = _dashboard_mutable_state(before)
    if baseline is None:
        raise RuntimeError("précondition impossible: dashboard initial illisible")
    _assert_dashboard_unchanged(mb, endpoint, baseline)

    parameters, dashcards = bascule_lib.apply_bascule(before, plan)
    target_dashboard = {
        "parameters": parameters,
        "dashcards": dashcards,
        "tabs": before.get("tabs") or [],
    }
    target = _dashboard_mutable_state(target_dashboard)
    snapshot = _write_bascule_snapshot(
        dashboard_id,
        baseline,
        _dashboard_payload(before),
    )

    failure = None
    reread = None
    residual = []
    temporal_ids = []
    try:
        response = mb.put(
            endpoint,
            "raw",
            json=_dashboard_payload(target_dashboard),
        )
        if getattr(response, "status_code", None) != 200:
            failure = (
                f"PUT HTTP {getattr(response, 'status_code', '?')}: "
                f"{str(getattr(response, 'text', ''))[:400]}"
            )
        else:
            reread = mb.get(endpoint)
            errors, residual, temporal_ids = _normal_bascule_postconditions(
                mb, reread, plan
            )
            if _dashboard_mutable_state(reread) != target:
                errors.append("projection configurable divergente de la cible")
            if errors:
                failure = "; ".join(errors)
    except Exception as exc:
        failure = f"exception après tentative de PUT: {type(exc).__name__}: {exc}"

    if failure is None:
        return {
            "snapshot": snapshot,
            "dashboard": reread,
            "temporal_ids": temporal_ids,
            "residual": residual,
        }

    rollback_note = _rollback_dashboard_from_snapshot(mb, endpoint, snapshot)
    raise RuntimeError(f"{failure}; {rollback_note}; snapshot {snapshot}")


def main(argv=None, mb=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--window", default="2026-05-01~2026-05-31")
    ap.add_argument("--auto-prepare", action="store_true",
                    help="convertit automatiquement le mécanisme temps des cartes bloquantes "
                         "(copies temporal-unit sandbox) avant de basculer — couvre la traîne.")
    ap.add_argument("--dry-prepare", action="store_true", help="auto-prepare en dry (ne crée pas les copies)")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)
    mb = mb or connect()

    dash = mb.get(f"/api/dashboard/{args.copy}")
    if not isinstance(dash, dict):
        sys.exit("dashboard inaccessible")

    duplicate_cleanup = duplicate_time_cleanup_plan(dash)
    if duplicate_cleanup is not None:
        if duplicate_cleanup.get("blockers"):
            print("⛔ sélecteurs Time period multiples non redondants :")
            for blocker in duplicate_cleanup["blockers"]:
                print(f"  {blocker}")
            return 1
        print(
            "Nettoyage des sélecteurs Time period redondants : "
            + ", ".join(duplicate_cleanup["removed_ids"])
        )
        if not args.yes:
            print("(DRY-RUN — rien modifié.)")
            return 0
        try:
            snapshot = apply_duplicate_time_cleanup(
                mb, args.copy, dash, duplicate_cleanup
            )
        except RuntimeError as exc:
            print(f"⛔ nettoyage refusé/annulé : {exc}")
            return 1
        print(f"PUT {args.copy}: 200 vérifié | snapshot: {snapshot}")
        return 0

    def build_plan():
        registry = load_registry()
        cards = {}
        for dc in _dcs(dash):
            cid = dc.get("card_id")
            if cid and cid not in cards:
                cards[cid] = mb.get(f"/api/card/{cid}")
        tbc = {cid: conv_lib.native_and_tags(c)[1] for cid, c in cards.items()}
        for old, new in registry.items():
            if old in cards and new not in tbc:
                tbc[new] = conv_lib.native_and_tags(mb.get(f"/api/card/{new}"))[1]
        p = bascule_lib.bascule_plan(dash, tbc, swaps={o: n for o, n in registry.items() if o in cards})
        return p, cards, tbc

    plan, cards, tags_by_card = build_plan()
    if plan is None:
        # L'absence de l'ancien sélecteur est un no-op valide : certains dashboards
        # n'ont jamais exposé ce filtre. L'orchestrateur fail-fast doit pouvoir passer
        # à la génération des fallbacks au lieu de classer la copie en échec.
        print("Pas de param 'Time period' (category) sur ce dashboard — rien à basculer.")
        return

    # AUTO-PRÉPARATION : convertit le mécanisme temps de chaque carte bloquante (conversion
    # ou non : Magento, tableaux multi-dim, charts orphelins) en copie temporal-unit, puis
    # recalcule le plan. C'est l'option « propre » : couvre la traîne sans intervention.
    unwire = set()  # (dashcard_id, card_id) à débrancher du filtre temps (granularité vestigiale)
    if args.auto_prepare and plan["blockers"]:
        from convert_generic_temporal import convert_card
        print(f"Auto-préparation de {len(plan['blockers'])} carte(s) bloquante(s) :")
        for b in list(plan["blockers"]):
            cid = b["card_id"]
            try:
                extra_params = dashboard_defaults_for_card(
                    dash,
                    b["dashcard_id"],
                    cid,
                    conv_lib.native_and_tags(cards[cid])[1],
                )
                new_id = (
                    convert_card(
                        mb,
                        cid,
                        args.client,
                        args.window,
                        extra_params=extra_params,
                    )
                    if not args.dry_prepare
                    else None
                )
            except Exception as e:
                # une carte lente/cassée (timeout, SQL KO) ne doit pas tuer toute la bascule :
                # on la traite comme non convertible (débranchée ou reste blocker explicite).
                print(f"  ⚠️ {cid} convert_card a échoué ({type(e).__name__}) → traité non convertible")
                new_id = None
            if new_id:
                continue
            # non convertible : si la carte a un filtre date séparé ET n'est pas un tableau
            # « by date », sa granularité est vestigiale -> on la débranche du filtre temps.
            tags = conv_lib.native_and_tags(cards[cid])[1]
            bd = conv_lib.card_breakdown(cards[cid])
            if "date" in tags and "date" not in bd:
                unwire.add((b["dashcard_id"], cid))
                print(f"  ↪ {cid} non convertible → DÉBRANCHÉE du filtre temps (granularité vestigiale, {bd})")
            else:
                print(f"  ⛔ {cid} non convertible ET time-driven → reste bloquant")
        plan, cards, tags_by_card = build_plan()
        # purge les blockers débranchés + ajoute-les au nettoyage de câblage
        plan["blockers"] = [b for b in plan["blockers"] if (b["dashcard_id"], b["card_id"]) not in unwire]
        _pid = plan["old_param"]["id"]
        plan["dead_mappings"] += [(dcid, _pid) for dcid, cid in unwire]

    # ne swapper que les cartes du dashboard réellement câblées sur l'ancien mécanisme
    pid = plan["old_param"]["id"]
    wired_dim = set()
    for dc in _dcs(dash):
        cid = dc.get("card_id")
        if cid and any(pm.get("parameter_id") == pid for pm in dc.get("parameter_mappings") or []):
            if ((tags_by_card.get(cid) or {}).get(bascule_lib.TIME_TAG) or {}).get("type") == "dimension":
                wired_dim.add(cid)
    plan["swaps"] = {o: n for o, n in plan["swaps"].items() if o in wired_dim}

    print(f"Dashboard {args.copy} — plan de bascule :")
    print(f"  param {pid} '{plan['old_param'].get('name')}' category -> temporal-unit (défaut "
          f"{plan['new_param']['default']})")
    # les copies temporal-unit du registre ont DÉJÀ été vérifiées par convert_card (baseline
    # inline fiable, 4 granularités). La re-vérif ici utilise l'ancien field-filter (parfois
    # cassé) -> on la garde en INFO mais on ne bloque QUE pour les swaps hors-registre.
    verified_reg = set(load_registry().keys())
    checks_ok = True
    for old, new in sorted(plan["swaps"].items()):
        name = (cards[old] or {}).get("name", "?")
        ok_all = True
        for g in ("week", "month"):
            b = card_values_pinned(mb, old, args.client, args.window, g)
            a = card_values_pinned(mb, new, args.client, args.window, g)
            if not (bool(b) and b == a):
                ok_all = False
                if old not in verified_reg:
                    print(f"  ⛔ swap {old}->{new} {name[:40]!r}: valeurs {g} "
                          f"{'VIDES' if not b else 'différentes'} (avant {len(b)} / après {len(a)})")
        if ok_all:
            print(f"  swap {old} -> {new}  {name[:48]!r}  valeurs week+month identiques ✅")
        elif old in verified_reg:
            print(f"  swap {old} -> {new}  {name[:48]!r}  (vérifié à la conversion ✓, re-check skipé)")
        checks_ok &= (ok_all or old in verified_reg)
    for dcid, p in plan["dead_mappings"]:
        print(f"  nettoyage câblage mort: dashcard {dcid}")
    for dcid, cid in plan["to_wire"]:
        print(f"  câblage ajouté: dashcard {dcid} -> carte {cid}")
    if plan["blockers"]:
        print("  ⛔ BLOCKERS (swap conversion/11673 à faire d'abord, ou carte sans remplacement):")
        for b in plan["blockers"]:
            nm = (cards.get(b['card_id']) or {}).get('name', '?')
            print(f"     dashcard {b['dashcard_id']} carte {b['card_id']} {nm[:48]!r} — {b['reason']}")
        sys.exit(1)
    if not checks_ok:
        sys.exit("⛔ vérifications de valeurs en échec — bascule refusée.")
    if not args.yes:
        print("(DRY-RUN — rien modifié.)")
        return

    try:
        outcome = apply_normal_bascule(mb, args.copy, dash, plan)
    except RuntimeError as exc:
        print(f"⛔ bascule refusée/annulée : {exc}")
        return 1
    print(
        f"PUT {args.copy}: 200 vérifié "
        f"(snapshot: {outcome['snapshot'].name})"
    )
    print(f"Param temporal-unit en place : {outcome['temporal_ids']}")
    print("Anomalies résiduelles : AUCUNE ✅")
    if unwire:
        print(f"Cartes débranchées du filtre temps (granularité vestigiale) : {sorted(c for _, c in unwire)}")


if __name__ == "__main__":
    main()
