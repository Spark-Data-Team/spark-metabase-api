#!/usr/bin/env python3
"""Re-migre un dashboard COPIE en réutilisant les cartes de 11673 (AUCUNE génération).

Repart de l'ORIGINAL (--source) pour retrouver les anciennes cartes, et écrit sur la
COPIE (--copy) en conservant les ids de dashcard de la copie. Par tuile de conversion :
- `migrée`  : carte 11673 résolue + TOUS les garde-fous verts ->
    garde-fous : résolution unique (mapping client + colonne + breakdown + KPIs + brand
    + même table source) ; types de tags câblés compatibles (ex. time_period
    dimension->temporal-unit = REFUS) ; aucun filtre câblé orphelin après renommage ;
    rendu cohérent (graph.metrics ⊆ colonnes, hors scalaires, insensible casse) ;
    valeurs avant==après NON vides.
- sinon     : on GARDE l'ancienne carte, statut explicite (à décider / à vérifier).
JAMAIS de génération de carte. PUT vérifié (raw). Dashboards à onglets refusés (pilotes
sans onglets ; support tabs à ajouter avant la généralisation).

Usage:
  python3 scripts/migrate_dashboard_reuse.py --copy 25566 --source 14118 --client "Pro Nutrition"        # dry-run
  python3 scripts/migrate_dashboard_reuse.py --copy 25566 --source 14118 --client "Pro Nutrition" --yes
"""
import argparse, json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib
import bascule_lib
from migrate_dashboard_full import connect, load_inputs, card_values, _dcs

def _client_date_params(tags, client, window):
    """Params client/date robustes : gère 'clients' (pluriel) ET 'client' (singulier,
    magento), avec le bon type (widget-type du tag : string/=, category…)."""
    p = []
    for ct in ("clients", "client"):
        if ct in tags:
            wt = (tags.get(ct) or {}).get("widget-type") or "string/="
            p.append({"type": wt, "value": [client], "target": ["dimension", ["template-tag", ct]]})
    if "date" in tags:
        wt = (tags.get("date") or {}).get("widget-type") or "date/all-options"
        p.append({"type": wt, "value": window, "target": ["dimension", ["template-tag", "date"]]})
    return p


def card_values_pinned(mb, card_id, client, window, gran):
    """card_values + granularité épinglée selon le mécanisme du tag de LA carte
    (category pour l'ancien field-filter, temporal-unit pour le nouveau).
    Nécessaire pour comparer avant/après à travers la bascule du filtre temps."""
    c = mb.get(f"/api/card/{card_id}"); _, tags = conv_lib.native_and_tags(c)
    params = _client_date_params(tags, client, window)
    tp = bascule_lib.time_param_payload(tags, gran)
    if tp:
        params.append(tp)
    r = mb.post(f"/api/card/{card_id}/query", json={"parameters": params}, timeout=180)
    rows = (r or {}).get("data", {}).get("rows", []) or []
    return sorted(round(float(x), 4) for row in rows for x in row if isinstance(x, (int, float)))

def card_cells(mb, card_id, client, window, gran, metrics):
    """Cellules AFFICHÉES seulement (colonnes `metrics`), params épinglés
    (client/date, + granularité si gran). Pour comparer deux cartes dont l'une
    sort des colonnes supplémentaires masquées au niveau du dashcard."""
    c = mb.get(f"/api/card/{card_id}"); _, tags = conv_lib.native_and_tags(c)
    params = _client_date_params(tags, client, window)
    if gran:
        tp = bascule_lib.time_param_payload(tags, gran)
        if tp:
            params.append(tp)
    r = mb.post(f"/api/card/{card_id}/query", json={"parameters": params}, timeout=180)
    data = (r or {}).get("data", {})
    cols = [str(x.get("name")) for x in data.get("cols", []) or []]
    return conv_lib.displayed_cells(cols, data.get("rows", []) or [], metrics)

# viz du dashcard conservée sur tuile migrée : titre, comparaisons, navigation au clic.
# graph.metrics / column_settings / series_settings sont jetés (clés sur anciens alias)
# -> la carte 11673 affiche avec SA viz propre.
KEEP_VIZ = {"card.title", "scalar.comparisons", "click_behavior"}

# Champs du payload PUT (whitelist : jamais d'entity_id/card/timestamps d'un autre dashboard)
DC_FIELDS = ("card_id", "row", "col", "size_x", "size_y", "series",
             "parameter_mappings", "visualization_settings", "dashboard_tab_id")

def render_coherent(mb, card_id, client):
    """(ok: bool|None, raison) — None = la requête de contrôle a échoué (≠ rendu cassé)."""
    c = mb.get(f"/api/card/{card_id}")
    if not isinstance(c, dict):
        return None, "carte inaccessible"
    if (c.get("display") or "") in conv_lib._SCALAR_DISPLAYS:
        return True, ""
    gm = (c.get("visualization_settings") or {}).get("graph.metrics") or []
    if not gm:
        return True, ""
    r = mb.post(f"/api/card/{card_id}/query", json={"parameters": [{"type": "string/=", "value": [client],
                "target": ["dimension", ["template-tag", "clients"]]}]}, timeout=120)
    if not isinstance(r, dict):
        return None, "échec requête de contrôle"
    cols = {str(x.get("name")).upper() for x in r.get("data", {}).get("cols", []) or []}
    miss = [m for m in gm if str(m).upper() not in cols]
    return (False, f"séries absentes: {miss}") if miss else (True, "")

def wired_tags_of(dc):
    tags = set()
    for pm in dc.get("parameter_mappings") or []:
        tgt = pm.get("target")
        try:
            if tgt[1][0] == "template-tag":
                tags.add(tgt[1][1])
        except Exception:
            pass
    return tags

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", type=int, required=True)
    ap.add_argument("--source", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--window", default="2026-05-01~2026-05-31")
    ap.add_argument("--planned-temporal-unit", action="store_true",
                    help="bascule du filtre temps planifiée sur ce dashboard : le passage d'un tag "
                         "time_period dimension->temporal-unit n'est plus bloquant ; les valeurs "
                         "avant/après sont alors comparées à granularité épinglée (week).")
    ap.add_argument("--accept-diffs", action="store_true",
                    help="migre même si les valeurs avant/après diffèrent (écart connu/validé, "
                         "ex. ancien mapping erroné corrigé). Les autres garde-fous restent actifs.")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()
    mapping_all, index = load_inputs()
    cmap = {int(k): v for k, v in mapping_all.get(args.client, {}).items()}
    if not cmap:
        sys.exit(f"Aucun mapping pour {args.client!r}.")

    source = mb.get(f"/api/dashboard/{args.source}")
    copy = mb.get(f"/api/dashboard/{args.copy}")
    if not isinstance(source, dict) or not isinstance(copy, dict):
        sys.exit("dashboard source/copie inaccessible")
    # ONGLETS supportés : la copie shallow garde l'ordre des onglets de la source -> on
    # apparie par (index d'onglet, row, col). Les ids d'onglet de la copie diffèrent de la
    # source, d'où l'appariement par INDEX, et on garde l'id d'onglet de la COPIE.
    src_tab_idx = {t["id"]: i for i, t in enumerate(source.get("tabs") or [])}
    copy_tab_idx = {t["id"]: i for i, t in enumerate(copy.get("tabs") or [])}
    if len(src_tab_idx) != len(copy_tab_idx):
        sys.exit("⛔ source et copie n'ont pas le même nombre d'onglets — appariement impossible")

    def _pos(dc, idx):
        return (idx.get(dc.get("dashboard_tab_id")), dc.get("row"), dc.get("col"))

    # appariement par position (onglet, row, col), avec détection de collision
    src_by_pos = {}
    for d in _dcs(source):
        key = _pos(d, src_tab_idx)
        if key in src_by_pos:
            sys.exit(f"⛔ position ambiguë dans la source {key} — appariement impossible")
        src_by_pos[key] = d

    new_dcs, report = [], []
    for cdc in _dcs(copy):
        sdc = src_by_pos.get(_pos(cdc, copy_tab_idx))
        if not sdc:
            new_dcs.append(cdc)
            if cdc.get("card_id"):
                report.append((f"dashcard {cdc.get('id')}", "sans équivalent source — inchangée"))
            continue
        nd = {k: json.loads(json.dumps(sdc.get(k))) for k in DC_FIELDS}
        nd["dashboard_tab_id"] = cdc.get("dashboard_tab_id")  # garder l'onglet de la COPIE
        nd["id"] = cdc.get("id")
        cid = sdc.get("card_id")
        card = mb.get(f"/api/card/{cid}") if cid else None
        if cid and not isinstance(card, dict):
            report.append((f"carte #{cid}", "⛔ carte source inaccessible — tuile inchangée"))
            new_dcs.append(nd); continue

        # series jamais migrées automatiquement : si une carte de series est sur l'ancien système -> on signale
        series_old = []
        for s in nd.get("series") or []:
            sc = mb.get(f"/api/card/{s.get('id') or s.get('card_id')}")
            if isinstance(sc, dict) and conv_lib.old_conversion_columns(conv_lib.native_and_tags(sc)[0]):
                series_old.append(sc.get("id"))
        if series_old:
            report.append((card.get("name") if card else f"dashcard {cdc.get('id')}",
                           f"À DÉCIDER — series sur ancien système: {series_old}"))
            new_dcs.append(nd); continue

        if not cid:
            new_dcs.append(nd); continue
        sql, _ = conv_lib.native_and_tags(card)
        old_cols = conv_lib.old_conversion_columns(sql)
        if not old_cols:
            if conv_lib.has_opaque_refs(sql):
                report.append((card.get("name"), "À VÉRIFIER — snippet/carte source (contenu invisible)"))
            new_dcs.append(nd); continue

        # --- résolution + garde-fous ---
        res = conv_lib.resolve_new_card(card, cmap, index)
        decision = None
        mask_keep = None  # séries 11673 à afficher (override dashcard) si masquage
        diff_note = ""    # écart de valeurs avant/après accepté (--accept-diffs)
        if res.get("status") != "ok":
            decision = f"À DÉCIDER ({res.get('status')}: {str(res.get('reason') or res.get('candidates') or '')[:70]})"
        else:
            newc_id = res["new_card_id"]
            new_card = mb.get(f"/api/card/{newc_id}")
            renames = conv_lib.tag_rename_map(card, new_card)
            _, otags = conv_lib.native_and_tags(card)
            # seuls les câbles VIVANTS sur l'ancienne carte comptent : un mapping vers un tag
            # que l'ancienne carte n'a pas était déjà mort (toléré par Metabase) — ne bloque pas.
            wired = wired_tags_of(sdc) & set(otags)
            _, ntags = conv_lib.native_and_tags(new_card)
            orphans = {renames.get(t, t) for t in wired} - set(ntags)
            incompat = conv_lib.incompatible_wired_tags(card, new_card, wired, renames)
            time_exception = False
            if args.planned_temporal_unit:
                kept = {t: v for t, v in incompat.items() if tuple(v) != ("dimension", "temporal-unit")}
                time_exception = len(kept) < len(incompat)
                incompat = kept
            rc_ok, rc_reason = render_coherent(mb, newc_id, args.client)
            if orphans:
                decision = f"À DÉCIDER (filtres orphelins sur 11673: {sorted(orphans)})"
            elif incompat:
                decision = f"À DÉCIDER (type de tag incompatible: {incompat})"
            elif rc_ok is None:
                decision = f"À VÉRIFIER ({rc_reason})"
            elif not rc_ok:
                decision = f"À DÉCIDER (rendu 11673 incohérent: {rc_reason})"
            else:
                if time_exception:
                    before = card_values_pinned(mb, cid, args.client, args.window, "week")
                    after = card_values_pinned(mb, newc_id, args.client, args.window, "week")
                else:
                    before = card_values(mb, cid, args.client, args.window)
                    after = card_values(mb, newc_id, args.client, args.window)
                if not before:
                    decision = "À VÉRIFIER (fenêtre de validation VIDE — aucune preuve)"
                elif before != after:
                    # la carte 11673 affiche-t-elle simplement des séries EN PLUS ?
                    # -> mapper les séries de l'ancienne par nature, masquer le reste
                    #    au niveau du dashcard, et comparer sur les séries affichées.
                    old_m = (card.get("visualization_settings") or {}).get("graph.metrics") or []
                    new_m = (new_card.get("visualization_settings") or {}).get("graph.metrics") or []
                    mapped = None
                    if ((card.get("display") or "") not in conv_lib._SCALAR_DISPLAYS
                            and old_m and new_m and len(new_m) > len(old_m)):
                        mapped = conv_lib.series_display_map(old_m, new_m)
                    if mapped:
                        g = "week" if time_exception else None
                        b2 = card_cells(mb, cid, args.client, args.window, g, old_m)
                        a2 = card_cells(mb, newc_id, args.client, args.window, g, mapped)
                        if b2 and b2 == a2:
                            mask_keep = mapped
                        else:
                            decision = ("À DÉCIDER (valeurs ≠ même restreintes aux séries affichées : "
                                        f"avant {b2[-1] if b2 else None} / après {a2[-1] if a2 else None})")
                    if not mapped and not decision:
                        if args.accept_diffs:
                            diff_note = f" [écart accepté: avant {before[-1] if before else None} / après {after[-1] if after else None}]"
                        else:
                            decision = f"À DÉCIDER (valeurs ≠ : avant {before[-1] if before else None} / après {after[-1] if after else None})"
        if decision:
            report.append((card.get("name"), f"{decision} — reste ancien #{cid}"))
            new_dcs.append(nd); continue

        # --- tuile migrée : repointage + recâblage + viz nettoyée ---
        nd["card_id"] = newc_id
        for pm in nd.get("parameter_mappings") or []:
            pm["card_id"] = newc_id
            tgt = pm.get("target")
            try:
                if tgt[1][0] == "template-tag" and tgt[1][1] in renames:
                    tgt[1][1] = renames[tgt[1][1]]
            except Exception:
                pass
        nd["visualization_settings"] = {k: v for k, v in (sdc.get("visualization_settings") or {}).items() if k in KEEP_VIZ}
        note = f" (renames {renames})" if renames else ""
        if mask_keep:
            nd["visualization_settings"]["graph.metrics"] = mask_keep
            hidden = [m for m in ((new_card.get("visualization_settings") or {}).get("graph.metrics") or [])
                      if m not in mask_keep]
            note += f" (séries masquées: {hidden})"
        report.append((card.get("name"), f"migrée -> 11673 #{newc_id}" + note + diff_note))
        new_dcs.append(nd)

    print(f"Dashboard {args.copy} (source {args.source}) :")
    for n, st in report:
        print(f"  {str(n)[:46]:46} {st}")
    n_mig = sum(1 for _, s in report if s.startswith("migrée"))
    print(f"\n=> {n_mig} migrée(s), {len(report) - n_mig} autre(s)")
    if not args.yes:
        print("(DRY-RUN — rien modifié.)"); return

    (REPO / "migration" / f"reuse-snapshot-{args.copy}.json").write_text(
        json.dumps(_dcs(copy), ensure_ascii=False))
    put_body = {"dashcards": new_dcs}
    if copy.get("tabs"):  # PUT d'un dash à onglets DOIT inclure tabs (sinon 500)
        put_body["tabs"] = copy["tabs"]
    res_put = mb.put(f"/api/dashboard/{args.copy}", "raw", json=put_body)
    if res_put.status_code != 200:
        print(f"⛔ PUT {args.copy} ÉCHOUÉ: HTTP {res_put.status_code} — {res_put.text[:400]}")
        sys.exit(1)
    print(f"PUT {args.copy}: 200 OK")

    # contrôles finaux
    chk = mb.get(f"/api/dashboard/{args.copy}")
    gen_left, old_left = [], []
    for dc in _dcs(chk):
        c = dc.get("card_id")
        if not c:
            continue
        cc = mb.get(f"/api/card/{c}")
        if not isinstance(cc, dict):
            continue
        if str(cc.get("name", "")).startswith(("[migré]", "[généré]")):
            gen_left.append(c)
        if conv_lib.old_conversion_columns(conv_lib.native_and_tags(cc)[0]):
            old_left.append(c)
    print(f"Cartes générées encore référencées : {gen_left if gen_left else 'AUCUNE ✅'}")
    print(f"Tuiles restées sur l'ancien système (attendues = les 'À DÉCIDER') : {old_left if old_left else 'AUCUNE ✅'}")

if __name__ == "__main__":
    main()
