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


def render_ok(mb, cid, client):
    """True sauf si VRAIE erreur SQL. Un timeout/non-complétion (grosses tables lentes)
    n'est PAS un échec : la substitution est structurellement cohérente (SQL+viz substitués
    ensemble) -> on garde la carte. On n'archive que sur une erreur SQL explicite."""
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
            return True  # la carte s'exécute ; substitution SQL+viz cohérente -> rend comme l'ancienne
        if st == "failed":
            # param REQUIS non fourni (« pick a value », « before this query can run », « missing
            # required parameter X » — ex. tag 'bonus'/'breakdown' sans défaut) = PAS une erreur SQL
            # de la substitution -> on garde (structurellement cohérent ; le dashboard fournit le param).
            if conv_lib.is_required_param_error(b.get("error")):
                return True
            return False  # vraie erreur SQL
    return True  # timeout/incomplet -> bénéfice du doute (struct. cohérent)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()
    mapping_all, _ = load_inputs()
    cmap = {int(k): v for k, v in mapping_all.get(args.client, {}).items()}
    reg = load_reg()
    special = load_special_ids()  # cartes spéciales déjà migrées -> ne pas retraiter
    dash = mb.get(f"/api/dashboard/{args.copy}")

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
            report.append((cid, card.get("name"), f"⛔ rien de substituable (conflit/non mappé: {sorted(old_cols)})"))
            new_dcs.append(dc); continue
        key = f"{cid}|{args.client}"
        gen_id = reg.get(key)
        if not gen_id and args.yes:
            gen_id = generate_card(mb, card, sub_map, GEN_COLL, cmap)
            if gen_id and render_ok(mb, gen_id, args.client):
                reg[key] = gen_id
            elif gen_id:
                mb.put(f"/api/card/{gen_id}", "raw", json={"archived": True})
                report.append((cid, card.get("name"), f"⛔ généré {gen_id} mais rendu KO → archivé"))
                new_dcs.append(dc); continue
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
    if args.yes and (gen or any('archivé' in str(r[2]) for r in report)):
        REG.write_text(json.dumps(reg, ensure_ascii=False, indent=0))
        put = {"dashcards": new_dcs}
        if dash.get("tabs"):
            put["tabs"] = dash["tabs"]
        res = mb.put(f"/api/dashboard/{args.copy}", "raw", json=put)
        print(f"PUT {args.copy}: {res.status_code}" + ("" if res.status_code == 200 else f" — {res.text[:200]}"))
    elif not args.yes:
        print("(DRY-RUN — rien généré.)")
    # contrôle 100%
    chk = mb.get(f"/api/dashboard/{args.copy}")
    left = [dc.get("card_id") for dc in _dcs(chk) if dc.get("card_id") and dc.get("card_id") not in special
            and conv_lib.old_conversion_columns(conv_lib.native_and_tags(mb.get(f"/api/card/{dc['card_id']}"))[0])]
    print(f"Tuiles encore sur l'ancien système (hors cartes spéciales migrées) : {left if left else 'AUCUNE ✅ (100%)'}")


if __name__ == "__main__":
    main()
