#!/usr/bin/env python3
"""Déploie les cartes « sélecteur » de conversion sur un dashboard COPIE.

Cas #87 « Social ad metric (filter choice) by date » -> carte 49788 : swap dashcard,
RETARGET du mapping Metric `dimension`->`variable`, et custom list (conversions
nommées) posée sur le filtre Metric du DASHBOARD (logique pure : special_cards_lib).

CLIENT-AGNOSTIQUE (la custom list = colonnes nommées de global.social_ad_daily_metrics ;
l'utilisateur choisit la métrique au dropdown, pas de slot-mapping). NE touche PAS au
filtre temps (bascule = étape séparée). Ne swappe QUE les tuiles « sélecteur » (metric
piloté par un filtre) ; les tuiles à métrique fixe restent sur l'ancienne carte (cible
nommée client-spécifique) et sont reportées.

Garde-fou : si un filtre Metric pilote AUSSI une carte non-sélecteur, on REFUSE.

Vérif live (avant/après, au niveau DASHBOARD, chaque tuile avec SON filtre Metric) :
- cost : somme avant (carte 87) == somme après (49788)        [additif -> fidélité] ;
- purchases : somme après > 0 et != cost                       [injection nommée] ;
- clicks : != cost et != purchases                             [3 valeurs distinctes ->
  la variable sélectionne vraiment des colonnes différentes, pas du code mort].

Usage :
  python3 scripts/deploy_special_cards.py --copy 26xxx                 # dry-run
  python3 scripts/deploy_special_cards.py --copy 26xxx --yes
"""
import argparse, json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib
import special_cards_lib as scl
from archive_collections import connect_resilient
from spark_metabase_api import validate

# carte sélecteur -> remplacement (text-variable). Extensible (famille segment plus tard).
SPECS = [{"old": 87, "new": 49788, "label": "#87 Social ad metric (filter choice)", "variable_tag": "metric"}]
PROBE = ["cost", "purchases", "clicks"]  # cost=fidélité, purchases=injection, clicks=distinction


def _dcs(d):
    return d.get("dashcards") or d.get("ordered_cards") or []


def card_metric_param(card, tag):
    for p in card.get("parameters") or []:
        tgt = p.get("target") or [None, [None, None]]
        # target mal formé (liste < 2, ou tgt[1] non-liste/vide) -> pas d'IndexError : on retombe
        # sur le seul match par slug plutôt que de crasher tout le préflight sur un param douteux.
        sub = tgt[1] if isinstance(tgt, list) and len(tgt) > 1 else None
        if p.get("slug") == tag or (isinstance(sub, list) and sub and sub[-1] == tag):
            return p
    return None


def validate_new_card(new_card, new_tags, src_param, vtag):
    """Préflight de la carte de remplacement : structure attendue, sinon on refuse net
    (évite de propager une carte mal configurée sur des dashboards prod)."""
    errs = []
    if vtag not in new_tags:
        errs.append(f"template-tag '{vtag}' absent de la carte")
    if not src_param:
        errs.append(f"param '{vtag}' (custom list source) introuvable")
    else:
        if src_param.get("values_source_type") != "static-list":
            errs.append(f"values_source_type={src_param.get('values_source_type')!r} (attendu static-list)")
        toks = scl.source_tokens(src_param)
        if not toks:
            errs.append("custom list vide")
        dflt = src_param.get("default")
        dflt = dflt[0] if isinstance(dflt, (list, tuple)) and dflt else dflt
        if dflt is not None and dflt not in set(toks):
            errs.append(f"défaut {dflt!r} hors de la liste")
    return errs


def metric_col_index(names):
    """Index de la colonne métrique dans un résultat de carte 87/49788. Robuste : préfère une
    colonne 'METRIC*', sinon l'unique colonne hors DATE/DIMENSION_*. None si ambigu/absent."""
    up = [n.upper() for n in names]
    cand = [i for i, n in enumerate(up) if n.startswith("METRIC")]
    if len(cand) == 1:
        return cand[0]
    other = [i for i, n in enumerate(up) if n != "DATE" and not n.startswith("DIMENSION")]
    return other[0] if len(other) == 1 else None


def dash_query_sum(mb, dash_id, dcid, card_id, metric_pid, metric_value):
    """Exécute un dashcard DANS le dashboard avec son filtre Metric=<value> ; somme la colonne
    métrique. (error, total). Les autres params = défauts du dashboard (avant/après identiques)."""
    r = mb.post(f"/api/dashboard/{dash_id}/dashcard/{dcid}/card/{card_id}/query", "raw",
                json={"parameters": [{"id": metric_pid, "value": metric_value}]})
    if not hasattr(r, "status_code"):
        return ("no response", None)
    j = r.json()
    if j.get("error"):
        return (str(j["error"])[:160], None)
    data = j.get("data") or {}
    names = [c.get("name") for c in data.get("cols") or []]
    idx = metric_col_index(names)
    if idx is None:
        return (f"colonne métrique introuvable ({names})", None)
    nums = [row[idx] for row in (data.get("rows") or [])
            if isinstance(row[idx], (int, float)) and not isinstance(row[idx], bool)]
    return (None, sum(nums))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", type=int, required=True)
    ap.add_argument("--client", default=None, help="ignoré (compat orchestrateur ; #87 est client-agnostique)")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect_resilient()

    dash = mb.get(f"/api/dashboard/{args.copy}")
    if not isinstance(dash, dict):
        sys.exit("dashboard inaccessible")
    print(f"Dashboard {args.copy} — {dash.get('name')!r}  ({len(_dcs(dash))} dashcards, "
          f"{len(dash.get('tabs') or [])} onglets)")

    working = {"parameters": dash.get("parameters") or [], "dashcards": _dcs(dash), "tabs": dash.get("tabs")}
    before = {}   # (old, dcid) -> (metric_pid, err, sum_cost)
    old_defaults = {}  # param_id -> default avant (pour signaler un changement)
    for p in working["parameters"]:
        old_defaults[p.get("id")] = p.get("default")
    plan_lines, applied, leftovers = [], [], []

    for spec in SPECS:
        old, new, vtag = spec["old"], spec["new"], spec["variable_tag"]
        if not scl.selector_dashcards(working, old):
            continue
        new_card = mb.get(f"/api/card/{new}")
        new_tags = set(conv_lib.native_and_tags(new_card)[1].keys())
        src_param = card_metric_param(new_card, vtag)
        errs = validate_new_card(new_card, new_tags, src_param, vtag)
        if errs:
            sys.exit(f"⛔ carte de remplacement {new} invalide : {errs}")
        driven = scl.metric_driven_dashcards(working, old, vtag)
        fixed = scl.fixed_metric_dashcards(working, old, vtag)
        pids = scl.metric_param_ids(working, old, vtag)
        foreign = scl.foreign_metric_consumers(working, pids, old)
        plan_lines.append(f"  {spec['label']}: {len(driven)} tuile(s) sélecteur {old}->{new} ; "
                          f"filtre(s) Metric={sorted(pids)}"
                          + (f" ; {len(fixed)} tuile(s) à MÉTRIQUE FIXE laissées sur {old} (passe par client)" if fixed else ""))
        if fixed:
            leftovers.extend((dc["id"], old) for dc in fixed)
        if not driven:
            plan_lines.append(f"     ↪ aucune tuile sélecteur (metric non piloté) — SKIP {spec['label']}.")
            continue
        if foreign:
            print("\n".join(plan_lines))
            print(f"  ⛔ STOP : filtre(s) Metric {sorted(pids)} pilote(nt) aussi des cartes "
                  f"non-sélecteur {foreign} — équiper la liste les casserait. À traiter à la main/Gaby.")
            sys.exit(1)
        # baseline AVANT : chaque tuile avec SON propre filtre Metric (multi-filtres OK)
        for dc in driven:
            pid = scl.dashcard_metric_pid(dc, vtag)
            err, tot = dash_query_sum(mb, args.copy, dc["id"], old, pid, PROBE[0])
            before[(old, dc["id"])] = (pid, err, tot)
        params, dcs = scl.apply_selector_deploy(working, old, new, new_tags, src_param, vtag)
        working = {"parameters": params, "dashcards": dcs, "tabs": working.get("tabs")}
        applied.append(spec)

    print("Plan :"); print("\n".join(plan_lines))
    if leftovers:
        print(f"  ⚠️ {len(leftovers)} tuile(s) à métrique fixe NON migrées (restent sur l'ancien) : {leftovers}")
    # signale les VRAIS changements de défaut (filtre Metric) : ancien token hors nouvelle
    # liste -> repli sur cost (comparé en dé-listant : ['x'] vs 'x' = inchangé).
    for p in working["parameters"]:
        pid = p.get("id")
        if pid in old_defaults and scl._unwrap(old_defaults[pid]) != scl._unwrap(p.get("default")):
            print(f"  ⚠️ filtre Metric {pid!r} : défaut {scl._unwrap(old_defaults[pid])!r} -> "
                  f"{scl._unwrap(p.get('default'))!r} (ancien hors nouvelle liste -> repli)")
    if not applied:
        # no-op propre (pas d'erreur) : pas de carte sélecteur, ou seulement des tuiles à
        # métrique fixe -> l'orchestrateur enchaîne (exit 0). Les blocages réels (foreign,
        # carte invalide) ont déjà fait sys.exit(1) ; les anomalies post-déploiement -> exit 2.
        print("(rien à déployer ici — pas de tuile sélecteur migrable.)")
        return

    if not args.yes:
        print("(DRY-RUN — rien modifié.)")
        return

    snap = REPO / "migration" / f"special-cards-snapshot-{args.copy}.json"
    snap.write_text(json.dumps({"parameters": dash.get("parameters"), "dashcards": _dcs(dash),
                                "tabs": dash.get("tabs")}, ensure_ascii=False))
    body = {"parameters": working["parameters"], "dashcards": working["dashcards"]}
    if working.get("tabs"):
        body["tabs"] = working["tabs"]
    res = mb.put(f"/api/dashboard/{args.copy}", "raw", json=body)
    if getattr(res, "status_code", 0) != 200:
        sys.exit(f"⛔ PUT échoué: HTTP {getattr(res,'status_code','?')} — {getattr(res,'text','')[:400]}")
    print(f"PUT {args.copy}: 200 OK (snapshot {snap.name})")

    # ---- vérifications APRÈS ----
    chk = mb.get(f"/api/dashboard/{args.copy}")
    ok = True
    for spec in applied:
        old, new, vtag = spec["old"], spec["new"], spec["variable_tag"]
        sel_new = [dc for dc in _dcs(chk) if scl._card_id(dc) == new]
        print(f"\n[{spec['label']}] {len(sel_new)} dashcard(s) -> {new}")
        # structure : plus aucune tuile metric-DRIVEN sur l'ancienne carte (les fixes restent OK)
        if scl.metric_driven_dashcards(chk, old, vtag):
            print(f"  ⛔ une tuile sélecteur reste sur la carte {old}"); ok = False
        for dc in sel_new:
            mpm = [pm for pm in dc.get("parameter_mappings") or [] if scl._target_tag(pm.get("target")) == vtag]
            if mpm and mpm[0]["target"][0] != "variable":
                print(f"  ⛔ dashcard {dc['id']} : mapping metric encore {mpm[0]['target'][0]}"); ok = False
        # param(s) Metric équipé(s) de la custom list
        pids = scl.metric_param_ids(chk, new, vtag)
        for p in chk.get("parameters") or []:
            if p.get("id") in pids:
                good = (p.get("values_query_type") == "list" and p.get("values_source_type") == "static-list"
                        and p.get("isMultiSelect") is False
                        and len((p.get("values_source_config") or {}).get("values") or []) > 0)
                print(f"  filtre Metric {p['id']!r} : custom list={'OK' if good else 'KO'} "
                      f"(default={p.get('default')!r}, {len((p.get('values_source_config') or {}).get('values') or [])} valeurs)")
                ok &= good
        # exécution : chaque tuile avec SON filtre Metric -> 3 sondes distinctes
        for dc in sel_new:
            pid = scl.dashcard_metric_pid(dc, vtag)
            sums, errs = {}, []
            for m in PROBE:
                e, t = dash_query_sum(mb, args.copy, dc["id"], new, pid, m)
                if e:
                    errs.append(f"{m}:{e}")
                sums[m] = t
            if errs:
                print(f"  ⛔ dc {dc['id']} exec KO : {errs}"); ok = False; continue
            b = before.get((old, dc["id"]))
            fid = "n/a"
            if b and b[2] is not None and sums["cost"] is not None:
                f = validate.check_values(f"dc{dc['id']}", [b[2]], [sums["cost"]], mode="identical", tolerance=1e-6)
                fid = "✅" if f and f[0].level == "ok" else f"⛔ {f[0].message}"
                ok &= bool(f and f[0].level == "ok")
            distinct = len({round(v, 4) for v in sums.values() if v is not None}) == len([v for v in sums.values() if v is not None])
            inj = (sums.get("purchases") or 0) > 0 and distinct
            print(f"  dc {dc['id']} (filtre {pid}): cost={sums['cost']:.2f} (avant={b[2] if b else '?'}) "
                  f"fidélité {fid} | purchases={sums['purchases']:.2f} clicks={sums['clicks']:.2f} "
                  f"injection {'✅' if inj else '⛔'}")
            ok &= bool(inj)
    print(f"\n{'✅ DÉPLOIEMENT VÉRIFIÉ' if ok else '⛔ ANOMALIES — à inspecter'} (copie {args.copy})")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
