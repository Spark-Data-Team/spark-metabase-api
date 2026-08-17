#!/usr/bin/env python3
"""Fallback GÉNÉRATION (pour atteindre 100%) : pour chaque tuile encore sur l'ancien
système (colonnes positionnelles) APRÈS reuse+swap, génère une COPIE de la vieille
carte avec substitution des colonnes (conversions_N -> nouvelle colonne nommée via le
mapping client). Dédupliqué : 1 carte générée par (vieille carte × client), dans une
collection dédiée (13950). Repointe le dashcard. Onglets supportés.

Politique « génère tout » (user 2026-06-15) : si la carte n'existe pas (pas d'équivalent
11673), on la crée ; sinon on réutilise (le reuse a déjà fait ça en amont).

Usage : python3 scripts/generate_fallback.py --copy 25765 --client "Goodiespub" [--yes]
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib
import special_cards_lib as scl
from conv_paths import reg_dir
from migrate_dashboard_full import connect, load_inputs, generate_card, _dcs

GEN_COLL = 14115  # « Conversions migrées — étape 3 (A→Z) » sous 11673 = LISIBLE par les consultants
# (PAS le sandbox 13950/13851 : sinon tuiles VIDES côté conso — cf. leçon permissions)
REG = reg_dir() / "generated-cards.json"  # par-client si CONV_REG_DIR (parallèle), sinon migration/


def load_special_ids():
    """new_ids des cartes spéciales déjà migrées (#87->49788, #4854->49755…) -> à SKIPPER :
    elles affichent du nommé même si leur SQL référence encore des colonnes CONVERSIONS."""
    entries = []
    for f in (REPO / "migration").glob("tu-generic-*.json"):
        try:
            entries.append(json.loads(f.read_text()))
        except Exception:
            pass
    return scl.replacement_ids(entries)
DC_FIELDS = ("card_id", "row", "col", "size_x", "size_y", "series",
             "parameter_mappings", "visualization_settings", "dashboard_tab_id")


def load_reg():
    return json.loads(REG.read_text()) if REG.exists() else {}


def _clone(value):
    return json.loads(json.dumps(value))


def _reference_card_id(reference):
    """Id robuste aux formes Metabase ``id``, ``card_id`` et ``card.id``."""
    if not isinstance(reference, dict):
        return None
    return (
        reference.get("card_id")
        or reference.get("id")
        or (reference.get("card") or {}).get("id")
    )


def dashboard_card_references(dashboard):
    """Inventorie les cartes primaires ET les séries.

    Une entrée de série sans id est conservée avec ``card_id=None`` : l'ignorer
    permettrait à tort de déclarer le dashboard à 100 % sur une lecture incomplète.
    Les dashcards texte, elles, n'ont légitimement aucune carte primaire.
    """
    references = []
    for dashcard in _dcs(dashboard):
        dashcard_id = dashcard.get("id")
        primary_id = dashcard.get("card_id") or (dashcard.get("card") or {}).get("id")
        if primary_id:
            references.append({
                "dashcard_id": dashcard_id,
                "location": "primary",
                "card_id": primary_id,
            })
        for series_index, series in enumerate(dashcard.get("series") or []):
            references.append({
                "dashcard_id": dashcard_id,
                "location": f"series[{series_index}]",
                "card_id": _reference_card_id(series),
            })
    return references


def conversion_reference_issues(mb, dashboard, special_ids=None):
    """Retourne tout résidu positionnel ou contrôle impossible, sans faux 100 %.

    Les requêtes structurées sont inspectées via leur ``dataset_query`` sérialisée.
    Une carte illisible ou sans requête exploitable est explicitement inaccessible.
    """
    special_ids = set(special_ids or ())
    issues = []
    for reference in dashboard_card_references(dashboard):
        card_id = reference["card_id"]
        if card_id is None:
            issues.append({**reference, "status": "INACCESSIBLE", "reason": "SERIES_CARD_ID_MISSING"})
            continue
        if card_id in special_ids:
            continue
        try:
            card = mb.get(f"/api/card/{card_id}")
        except Exception as exc:
            issues.append({
                **reference,
                "status": "INACCESSIBLE",
                "reason": f"CARD_READ_FAILED:{exc}",
            })
            continue
        if not isinstance(card, dict):
            issues.append({**reference, "status": "INACCESSIBLE", "reason": "CARD_NOT_OBJECT"})
            continue
        sql, _tags = conv_lib.native_and_tags(card)
        dataset_query = card.get("dataset_query")
        legacy_query = card.get("legacy_query")
        if not sql and not dataset_query and not legacy_query:
            issues.append({**reference, "status": "INACCESSIBLE", "reason": "CARD_QUERY_MISSING"})
            continue
        scan_text = sql
        if not scan_text:
            try:
                scan_text = json.dumps(dataset_query or legacy_query, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                issues.append({
                    **reference,
                    "status": "INACCESSIBLE",
                    "reason": f"CARD_QUERY_UNREADABLE:{exc}",
                })
                continue
        old_columns = sorted(conv_lib.old_conversion_columns(scan_text))
        if old_columns:
            issues.append({
                **reference,
                "status": "POSITIONAL",
                "old_columns": old_columns,
            })
    return issues


def dashboard_payload(dashboard):
    """Payload de restauration construit à partir du snapshot complet."""
    payload = {"dashcards": _clone(_dcs(dashboard))}
    if "tabs" in dashboard:
        payload["tabs"] = _clone(dashboard.get("tabs") or [])
    return payload


def write_dashboard_snapshot(dashboard_id, dashboard, directory=None):
    """Écrit le dashboard complet avant toute mutation dashboard."""
    directory = directory or (reg_dir() / "fallback-snapshots")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = directory / f"dashboard-{dashboard_id}-{stamp}.json"
    path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n")
    return path


def _series_ids(dashcard):
    return [_reference_card_id(series) for series in dashcard.get("series") or []]


def dashboard_divergences(expected_dashcards, actual_dashboard, changed_ids):
    """Contrôle strict des références, du layout et des champs réellement réécrits."""
    if not isinstance(actual_dashboard, dict):
        return ["dashboard inaccessible après PUT"]
    expected_ids = [dc.get("id") for dc in expected_dashcards]
    actual_dashcards = _dcs(actual_dashboard)
    actual_ids = [dc.get("id") for dc in actual_dashcards]
    divergences = []
    if None in expected_ids:
        divergences.append("dashcard attendu sans id stable")
    if len(expected_ids) != len(set(expected_ids)):
        divergences.append("ids de dashcards attendus dupliqués")
    if len(actual_ids) != len(set(actual_ids)):
        divergences.append("ids de dashcards relus dupliqués")
    expected = {dc.get("id"): dc for dc in expected_dashcards if dc.get("id") is not None}
    actual = {dc.get("id"): dc for dc in actual_dashcards if dc.get("id") is not None}
    if set(expected) != set(actual):
        divergences.append(
            "dashcards manquantes=" + str(sorted(set(expected) - set(actual)))
            + ", supplémentaires=" + str(sorted(set(actual) - set(expected)))
        )
    for dashcard_id, wanted in expected.items():
        found = actual.get(dashcard_id)
        if found is None:
            continue
        wanted_card_id = wanted.get("card_id") or (wanted.get("card") or {}).get("id")
        found_card_id = found.get("card_id") or (found.get("card") or {}).get("id")
        if wanted_card_id != found_card_id:
            divergences.append(
                f"dashcard {dashcard_id}: card_id attendu {wanted_card_id}, relu {found_card_id}"
            )
        if _series_ids(wanted) != _series_ids(found):
            divergences.append(
                f"dashcard {dashcard_id}: séries attendues {_series_ids(wanted)}, "
                f"relues {_series_ids(found)}"
            )
        for field in ("row", "col", "size_x", "size_y", "dashboard_tab_id"):
            if wanted.get(field) != found.get(field):
                divergences.append(
                    f"dashcard {dashcard_id}: {field} attendu {wanted.get(field)!r}, "
                    f"relu {found.get(field)!r}"
                )
        if dashcard_id in changed_ids:
            if (wanted.get("parameter_mappings") or []) != (found.get("parameter_mappings") or []):
                divergences.append(f"dashcard {dashcard_id}: parameter_mappings divergents")
            if (wanted.get("visualization_settings") or {}) != (found.get("visualization_settings") or {}):
                divergences.append(f"dashcard {dashcard_id}: visualization_settings divergents")
    return divergences


def _http_ok(response):
    return getattr(response, "status_code", None) == 200


def rollback_dashboard(mb, dashboard_id, snapshot):
    """Rollback best-effort avec contrôle HTTP puis relecture de la restauration."""
    try:
        response = mb.put(
            f"/api/dashboard/{dashboard_id}", "raw", json=dashboard_payload(snapshot)
        )
        if not _http_ok(response):
            return False, f"rollback HTTP {getattr(response, 'status_code', '?')}"
        reread = mb.get(f"/api/dashboard/{dashboard_id}")
        stable_ids = {dc.get("id") for dc in _dcs(snapshot) if dc.get("id") is not None}
        divergences = dashboard_divergences(_dcs(snapshot), reread, stable_ids)
        if divergences:
            return False, "rollback divergent: " + "; ".join(divergences)
        return True, "rollback vérifié"
    except Exception as exc:
        return False, f"rollback impossible: {exc}"


def put_dashboard_verified(
    mb, dashboard_id, before, new_dashcards, changed_ids, snapshot_directory=None
):
    """Snapshot → PUT → relecture; rollback et échec au moindre doute."""
    if not isinstance(before, dict):
        raise RuntimeError("dashboard initial inaccessible; PUT refusé")
    if None in {dc.get("id") for dc in new_dashcards}:
        raise RuntimeError("dashcard sans id stable; PUT refusé")
    snapshot_path = write_dashboard_snapshot(
        dashboard_id, before, snapshot_directory
    )
    payload = {"dashcards": _clone(new_dashcards)}
    if "tabs" in before:
        payload["tabs"] = _clone(before.get("tabs") or [])

    try:
        response = mb.put(f"/api/dashboard/{dashboard_id}", "raw", json=payload)
    except Exception as exc:
        _ok, rollback_note = rollback_dashboard(mb, dashboard_id, before)
        raise RuntimeError(
            f"PUT a levé {exc}; {rollback_note}; snapshot {snapshot_path}"
        ) from exc
    if not _http_ok(response):
        _ok, rollback_note = rollback_dashboard(mb, dashboard_id, before)
        body = str(getattr(response, "text", ""))[:300]
        raise RuntimeError(
            f"PUT HTTP {getattr(response, 'status_code', '?')}: {body}; "
            f"{rollback_note}; snapshot {snapshot_path}"
        )
    try:
        reread = mb.get(f"/api/dashboard/{dashboard_id}")
        divergences = dashboard_divergences(new_dashcards, reread, set(changed_ids))
    except Exception as exc:
        _ok, rollback_note = rollback_dashboard(mb, dashboard_id, before)
        raise RuntimeError(
            f"relecture post-PUT impossible: {exc}; {rollback_note}; snapshot {snapshot_path}"
        ) from exc
    if divergences:
        _ok, rollback_note = rollback_dashboard(mb, dashboard_id, before)
        raise RuntimeError(
            "relecture post-PUT divergente: " + "; ".join(divergences)
            + f"; {rollback_note}; snapshot {snapshot_path}"
        )
    return snapshot_path


def render_check(mb, cid, client):
    """(ok, blank) de la carte générée, en UN rendu.

    - ok=True si la carte COMPILE : soit elle rend `completed`, soit elle échoue sur un paramètre
      REQUIS non fourni (« pick a value »… — structurellement cohérente, le dashboard la pilote).
      ok=False sur vraie erreur SQL, timeout, réponse illisible (fail-closed).
    - blank=True si elle rend `completed` MAIS sans aucune colonne métrique numérique : le drop a
      retiré la seule métrique -> carte BLANCHE (« clean » Iron Law mais vide, pire que le positionnel)
      -> le caller la refuse et garde l'ancienne. Sur param requis (pas de data) on ne peut pas juger
      le blanc -> blank=False (on ne refuse pas une carte que le dashboard remplira).
    """
    c = mb.get(f"/api/card/{cid}")
    _, tags = conv_lib.native_and_tags(c)
    params = []
    if "clients" in tags:
        params.append({"type": "string/=", "value": [client], "target": ["dimension", ["template-tag", "clients"]]})
    if "client" in tags:
        wt = (tags.get("client") or {}).get("widget-type") or "string/="
        params.append({"type": wt, "value": [client], "target": ["dimension", ["template-tag", "client"]]})
    for _ in range(2):
        # via /api/dataset (pas /api/card/<id>/query) : ne PAS imposer l'UI-required (ex. un
        # sélecteur 'breakdown' requis sans défaut bloquerait à tort) — on vérifie la VALIDITÉ
        # SQL de la substitution, pas l'ergonomie. Les params requis viennent du dashboard à l'usage.
        r = mb.post("/api/dataset", "raw", json={**c["dataset_query"], "parameters": params}, timeout=300)
        try:
            b = r.json() if r.text else {}
        except Exception:
            b = {}
        st = b.get("status") if isinstance(b, dict) else None
        if st == "completed":
            cols = (b.get("data") or {}).get("cols") if isinstance(b, dict) else None
            return True, not conv_lib.dataset_has_metric_column(cols)  # completed : blanc si 0 métrique
        if st == "failed":
            # param REQUIS non fourni (« pick a value », « before this query can run », « missing
            # required parameter X » — ex. tag 'bonus'/'breakdown' sans défaut) = PAS une erreur SQL
            # de la substitution -> on garde (structurellement cohérent ; le dashboard fournit le param).
            if conv_lib.is_required_param_error(b.get("error")):
                return True, False
            return False, False  # vraie erreur SQL
    return False, False  # timeout/incomplet/illisible -> contrôle impossible, donc blocage


VALUE_WINDOW = "2026-05-01~2026-05-31"  # fenêtre épinglée pour la vérif valeur (≈ swap_tables)


def _run_card(mb, card_obj, client, window=VALUE_WINDOW, extra_params=None):
    """Exécute une carte (params client + fenêtre + brand inerte + number requis=0) et renvoie
    (cols, rows) ou (None, None) si non exécutable (param requis manquant, KO) -> non vérifiable."""
    _, tags = conv_lib.native_and_tags(card_obj)
    params = []
    if "clients" in tags:
        params.append({"type": "string/=", "value": [client], "target": ["dimension", ["template-tag", "clients"]]})
    if "client" in tags:
        wt = (tags.get("client") or {}).get("widget-type") or "string/="
        params.append({"type": wt, "value": [client], "target": ["dimension", ["template-tag", "client"]]})
    if "date" in tags:
        params.append({"type": "date/all-options", "value": window, "target": ["dimension", ["template-tag", "date"]]})
    if "brand_included" in tags:
        params.append({"type": "category", "value": ["yes"], "target": ["dimension", ["template-tag", "brand_included"]]})
    for tn, t in (tags or {}).items():
        if (t or {}).get("type") == "number" and (t or {}).get("default") in (None, ""):
            params.append({"type": "number/=", "value": 0, "target": ["variable", ["template-tag", tn]]})
    params.extend(_clone(extra_params or []))
    r = mb.post("/api/dataset", "raw", json={**card_obj["dataset_query"], "parameters": params}, timeout=300)
    try:
        b = r.json() if r.text else {}
    except Exception:
        b = {}
    if not isinstance(b, dict) or b.get("status") != "completed":
        return None, None
    return [c["name"] for c in b["data"]["cols"]], b["data"]["rows"]


def value_review(mb, old_card, gen_id, client, sub_map, extra_params=None):
    """Garde-fou VALEUR (policy user « écart de valeur → revue »), absent jusqu'ici de generate_fallback :
    compare la carte GÉNÉRÉE (nommé) vs ORIGINALE (positionnel). Renvoie les écarts (conv_lib.value_diffs)
    — vide si fidèle, ``None`` si la comparaison est impossible.

    Deux familles de colonnes comparées : (1) les colonnes RENOMMÉES par la substitution (sub_map :
    CONVERSIONS→PURCHASES — cas des cartes simples) ; (2) les colonnes au nom PRÉSERVÉ communes aux deux
    (ex. `current_conversions` des cartes KPIs-evolution : l'alias garde `conversions` mais l'expression
    sous-jacente passe à purchases → seule la valeur change). Les colonnes non-conversion (cost, clicks…)
    sont identiques (même SQL) → somme égale → aucun faux positif."""
    ocols, orows = _run_card(mb, old_card, client, extra_params=extra_params)
    ncols, nrows = _run_card(
        mb, mb.get(f"/api/card/{gen_id}"), client, extra_params=extra_params
    )
    if ocols is None or ncols is None:
        return None
    common = {str(c).upper() for c in ocols} & {str(c).upper() for c in ncols}
    cmp_map = {c: c for c in common}   # noms préservés (KPIs-evolution: current_conversions…)
    cmp_map.update(sub_map)            # noms renommés (simples: CONVERSIONS→PURCHASES)
    return conv_lib.value_diffs(ocols, orows, ncols, nrows, cmp_map)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--accept-empty-target", action="store_true",
                    help="accepte un écart de valeur UNIQUEMENT s'il s'explique par un retard ETL sur un "
                         "mapping value-preserving (Custom N ← slot N, colonne cible encore vide). La "
                         "donnée sera correcte au prochain refresh. Ne relâche JAMAIS le garde-fou pour "
                         "les colonnes nommées (Purchases…) ni pour un vrai mismatch (cible non nulle).")
    ap.add_argument("--accept-diffs", action="store_true",
                    help="policy user explicite : ignore TOTALEMENT le contrôle de valeur (et ses requêtes) "
                         "et migre dès que le rendu est OK. À utiliser quand les écarts viennent d'un mapping "
                         "consultant incomplet, pas d'un bug outil. Le rendu reste vérifié (jamais de SQL cassé).")
    args = ap.parse_args()
    mb = connect()
    mapping_all, _ = load_inputs()
    cmap = {int(k): v for k, v in mapping_all.get(args.client, {}).items()}
    reg = load_reg()
    special = load_special_ids()  # cartes spéciales déjà migrées -> ne pas retraiter
    dash = mb.get(f"/api/dashboard/{args.copy}")
    from bascule_time_filter import dashboard_defaults_for_card

    new_dcs, report = [], []
    for dc in _dcs(dash):
        cid = dc.get("card_id")
        if not cid or cid in special:
            new_dcs.append(dc); continue
        card = mb.get(f"/api/card/{cid}")
        sql, _ = conv_lib.native_and_tags(card)
        old_cols = conv_lib.old_conversion_columns(sql)
        if not old_cols:
            new_dcs.append(dc); continue
        sub_map, unmapped = conv_lib.substitution_map(old_cols, cmap)
        # colonnes VISIBLES non substituées = vrai trou ; les cachées non mappées sont tolérées
        if not sub_map:
            # Aucun slot restant n'est mappable : la carte est DÉJÀ substituée en amont (slots mappés
            # nommés, il ne reste que du NON mappé), ou tout est conflit/absent. On ne génère une copie
            # « drop-only » QUE si le PRUNING des branches CASE non mappées, À LUI SEUL, nettoie tout
            # (famille distribution/sélecteur : le CASE survit avec ses branches mappées -> la carte
            # garde sa métrique). On NE retire JAMAIS d'item SELECT dans ce cas : ça viderait une carte
            # mono-métrique dont la conversion non mappée est l'unique métrique -> carte BLANCHE (pire
            # que le positionnel). Tout le reste (tables larges, smartscalars, sélecteurs à items CTE
            # positionnels) reste sur l'ancien système.
            if not conv_lib.case_branch_prune_cleans(sql):
                report.append((cid, card.get("name"), f"⛔ rien de substituable ni nettoyable par pruning CASE (non mappé: {sorted(old_cols)})"))
                new_dcs.append(dc); continue
        lossy_values = conv_lib.lossy_count_only_value_columns(unmapped, cmap)
        if lossy_values and not args.accept_diffs:
            # SANS --accept-diffs : une colonne de VALEUR positionnelle dont le slot est mappé à une
            # conversion COMPTAGE SEUL (Sign ups, Search visits… = pas de revenu) n'a pas de cible ->
            # on bloque (revue) pour ne pas supprimer une valeur en douce.
            report.append((
                cid,
                card.get("name"),
                "⛔ mapping count-only : valeur(s) sans cible "
                f"{lossy_values} — revue nécessaire, gardé sur l'ancien",
            ))
            new_dcs.append(dc); continue
        # AVEC --accept-diffs : ces colonnes de valeur sans cible (conversion comptage seul, donc pas
        # de revenu réel) sont DROPPÉES par le drop en aval (elles restent dans `unmapped` positionnel).
        # Le garde-fou anti-blanc (render_check) empêche quand même de vider une carte mono-métrique.
        # Réutilisation PAR CONTENU : si une carte au SQL identique existe déjà — même
        # fabriquée pour un autre client — on la repartage au lieu d'en créer une jumelle.
        gen_id, key = conv_lib.lookup_generated_card(reg, cid, sub_map)
        if not gen_id and args.yes:
            gen_id = generate_card(mb, card, sub_map, GEN_COLL, cmap)
            ok, blank = render_check(mb, gen_id, args.client) if gen_id else (False, False)
            if gen_id and not ok:
                # AUTO-SÛRETÉ : la cascade a cassé le SQL (carte très complexe). Plutôt que de laisser
                # une carte KO (= bug outil), on régénère SANS cascade (substitué-seul, qui REND) : les
                # slots non mappés restent en rab → la tuile reste « sur l'ancien » (trou de COUVERTURE,
                # pas un bug ; à finir via carte générique dédiée), mais NOTRE outil ne casse rien.
                mb.put(f"/api/card/{gen_id}", "raw", json={"archived": True})
                gen_id = generate_card(mb, card, sub_map, GEN_COLL, cmap, drop_unmapped=False)
                ok, blank = render_check(mb, gen_id, args.client) if gen_id else (False, False)
                if gen_id and not ok:
                    mb.put(f"/api/card/{gen_id}", "raw", json={"archived": True})
                    report.append((cid, card.get("name"), f"⛔ généré {gen_id} mais rendu KO → archivé (même sans cascade)"))
                    new_dcs.append(dc); continue
                report.append((cid, card.get("name"), "⚠️ cascade KO → substitué SANS drop (slots non mappés en rab — couverture, pas un bug)"))
            if gen_id and blank:
                # GARDE-FOU ANTI-BLANC : le drop a retiré la seule métrique -> la carte rend mais VIDE
                # (« clean » Iron Law, colonnes = dimensions seules). C'est PIRE que le positionnel :
                # on refuse, on archive la copie, et on GARDE l'ancienne carte (qui affiche sa métrique).
                mb.put(f"/api/card/{gen_id}", "raw", json={"archived": True})
                report.append((cid, card.get("name"), "⚠️ carte BLANCHIE par le drop (plus de métrique) → gardé sur l'ancien"))
                new_dcs.append(dc); continue
            if gen_id and args.accept_diffs:
                # Policy user explicite : « on s'en fout des écarts de valeur dus au mapping consultant
                # incomplet ». On saute complètement le contrôle de valeur (donc aussi ses requêtes
                # lentes) et on migre. Le rendu est déjà vérifié (render_ok) → jamais de SQL cassé.
                reg[key] = gen_id
                report.append((cid, card.get("name"), "✅ migré (--accept-diffs : contrôle de valeur ignoré)"))
            elif gen_id:
                # GARDE-FOU VALEUR (policy user) : nommé vs positionnel par slot mappé. Écart -> on NE
                # migre PAS (carte archivée, tuile gardée sur l'ancien) et on flague pour REVUE.
                extra_params = dashboard_defaults_for_card(
                    dash,
                    dc.get("id"),
                    cid,
                    conv_lib.native_and_tags(card)[1],
                )
                vd = value_review(
                    mb,
                    card,
                    gen_id,
                    args.client,
                    sub_map,
                    extra_params=extra_params,
                )
                if vd is None:
                    mb.put(f"/api/card/{gen_id}", "raw", json={"archived": True})
                    report.append((
                        cid,
                        card.get("name"),
                        "⛔ À REVOIR (comparaison de valeurs impossible) — "
                        "carte générée archivée, gardé sur l'ancien",
                    ))
                    new_dcs.append(dc)
                    continue
                if vd:
                    if args.accept_empty_target and conv_lib.diffs_are_etl_lag_value_preserving(vd, cmap):
                        # Retard ETL sur mapping value-preserving (Custom N ← slot N, cible vide) : on
                        # migre quand même ; la colonne sera peuplée au prochain refresh, égalité garantie.
                        reg[key] = gen_id
                        ex = vd[0]
                        report.append((cid, card.get("name"),
                                       f"✅ migré malgré cible vide (retard ETL, value-preserving : "
                                       f"{ex[0]}→{ex[1]}, {round(ex[2], 2)} vs {round(ex[3], 2)})"))
                    else:
                        mb.put(f"/api/card/{gen_id}", "raw", json={"archived": True})
                        ex = vd[0]
                        report.append((cid, card.get("name"),
                                       f"⚠️ À REVOIR (écart valeur {ex[0]}→{ex[1]} : {round(ex[2], 2)} vs {round(ex[3], 2)}) "
                                       f"— gardé sur l'ancien"))
                        new_dcs.append(dc); continue
                else:
                    reg[key] = gen_id
        if not gen_id:
            report.append((cid, card.get("name"), f"(dry) substituable: {sub_map}" + (f" | non mappé {unmapped}" if unmapped else "")))
            new_dcs.append(dc); continue
        nd = {k: json.loads(json.dumps(dc.get(k))) for k in DC_FIELDS if dc.get(k) is not None}
        nd["id"] = dc.get("id")
        nd["card_id"] = gen_id
        # la config de colonnes du DASHCARD (table.columns / column_settings / series) référence
        # les anciens noms -> substituer pareil pour que l'affichage (visibilité, ordre, titres) colle.
        if nd.get("visualization_settings"):
            # substitue les réfs de colonnes du DASHCARD (table.columns/column_settings/series)
            # en PRÉSERVANT les libellés humains (card.title, titres) ;
            nd["visualization_settings"] = conv_lib.substitute_viz(nd["visualization_settings"], sub_map)
            # titre OVERRIDE générique du dashcard -> conversion nommée (libellé métier préservé)
            if nd["visualization_settings"].get("card.title"):
                nd["visualization_settings"]["card.title"] = conv_lib.relabel_conversion_title(
                    nd["visualization_settings"]["card.title"],
                    conv_lib.conversion_display_names(sub_map, cmap))
            # puis dashcard « visualizer » : repointer les réfs "card:<old>" vers la carte générée
            # (sinon le visualizer source l'ancienne carte positionnelle = tuile VIDE).
            nd["visualization_settings"] = conv_lib.repoint_visualizer_source(
                nd["visualization_settings"], cid, gen_id)
        for pm in nd.get("parameter_mappings") or []:
            pm["card_id"] = gen_id
        new_dcs.append(nd)
        report.append((cid, card.get("name"), f"généré -> {gen_id}" + (f" | colonnes non mappées (cachées?): {unmapped}" if unmapped else "")))

    print(f"Dashboard {args.copy} — fallback génération ({args.client}) :")
    for cid, n, st in report:
        print(f"  {cid} {str(n)[:38]:38} {st}")
    gen = [r for r in report if str(r[2]).startswith("généré")]
    chk = None
    if args.yes and gen:
        before_by_id = {dc.get("id"): dc for dc in _dcs(dash)}
        changed_ids = {
            dc.get("id")
            for dc in new_dcs
            if (
                (before_by_id.get(dc.get("id"), {}).get("card_id")
                 or (before_by_id.get(dc.get("id"), {}).get("card") or {}).get("id"))
                != (dc.get("card_id") or (dc.get("card") or {}).get("id"))
            )
        }
        try:
            snap = put_dashboard_verified(mb, args.copy, dash, new_dcs, changed_ids)
        except RuntimeError as exc:
            print(f"⛔ {exc}", file=sys.stderr)
            return 1
        REG.write_text(json.dumps(reg, ensure_ascii=False, indent=0))
        print(f"PUT {args.copy}: 200 vérifié | snapshot: {snap}")
        chk = mb.get(f"/api/dashboard/{args.copy}")
    elif not args.yes:
        print("(DRY-RUN — rien généré.)")
    # Contrôle Iron Law : cartes primaires ET séries. Une lecture impossible est un
    # résidu de preuve, jamais une permission implicite de déclarer 100 %.
    if chk is None:
        chk = mb.get(f"/api/dashboard/{args.copy}")
    issues = conversion_reference_issues(mb, chk, special)
    if issues:
        print("Références non prouvées sur le nouveau système (primary + series) :")
        for issue in issues:
            location = f"dashcard {issue.get('dashcard_id')} {issue.get('location')}"
            if issue["status"] == "POSITIONAL":
                detail = ", ".join(issue.get("old_columns") or [])
                print(f"  ⛔ {location}: carte {issue.get('card_id')} positionnelle ({detail})")
            else:
                print(
                    f"  ⛔ {location}: carte {issue.get('card_id')} inaccessible "
                    f"({issue.get('reason')})"
                )
        # En dry-run, les résidus décrivent le plan. En mode appliqué, l'étape n'a
        # pas atteint son contrat et doit stopper l'orchestrateur.
        return 1 if args.yes else 0
    print("Tuiles encore sur l'ancien système : AUCUNE ✅ (100% primary + series vérifiées)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
