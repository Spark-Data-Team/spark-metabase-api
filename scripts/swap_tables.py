#!/usr/bin/env python3
"""Swap des tableaux multi-slot d'un dashboard COPIE vers la famille mixte 11673
(option b). Par tableau : repointe le dashcard vers la carte mixte, reconstruit
table.columns (colonnes mappées visibles, le reste masqué) + column_settings (titres
repris de l'ancien dashcard), recâble les filtres. Garde-fou : chaque colonne mappée
est vérifiée valeur-par-valeur (ancienne vs nouvelle, params épinglés) ; si une seule
colonne diffère, le tableau GARDE l'ancienne carte et est signalé.

Mapping de cible (démo Pro Nutrition 25632) : tableau ancien -> carte mixte + dimension.
Usage :
  python3 scripts/swap_tables.py --copy 25632 --client "Pro Nutrition"          # dry-run
  python3 scripts/swap_tables.py --copy 25632 --client "Pro Nutrition" --yes
"""
import argparse, json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import conv_lib
import bascule_lib
from migrate_dashboard_full import connect, load_inputs, _dcs

# famille mixte 11673/13884 : breakdown -> (carte « toutes conversions », dimension, temporal-unit ?)
MIXED_FAMILY = {
    "type":     (49098, "CURRENT_CAMPAIGN_TYPE", False),
    "channel":  (49100, "CURRENT_CAMPAIGN_CHANNEL", False),
    "location": (49101, "CURRENT_CAMPAIGN_LOCATION", False),
    "name":     (49102, "CURRENT_CAMPAIGN_NAME", False),
    "product":  (49103, "CURRENT_CAMPAIGN_PRODUCT", False),
    "date":     (49104, "CURRENT_TIME_PERIOD", True),
    "device":   (49105, "CURRENT_CAMPAIGN_DEVICE", False),
    "url":      (49106, "CURRENT_URL", False),
    "category": (49107, "CURRENT_CAMPAIGN_CATEGORY", False),
    "network":  (49129, "CURRENT_CAMPAIGN_NETWORK", False),
}


def resolve_table_target(card):
    """Détecte si la carte est un vieux tableau multi-slot et renvoie sa carte mixte
    cible (carte, dim, temporal) via le breakdown. None si pas un tableau conversion,
    breakdown multi-dimension, ou breakdown non couvert par la famille mixte."""
    if (card.get("display") or "") != "table":
        return None
    sql, _ = conv_lib.native_and_tags(card)
    if not conv_lib.old_conversion_columns(sql):
        return None
    bd = conv_lib.card_breakdown(card)
    if len(bd) != 1 or bd[0] not in MIXED_FAMILY:
        return None
    return MIXED_FAMILY[bd[0]]
# métriques nommées hors slots positionnels (best-effort, tranché par la vérif valeur)
NAMED_EXTRA = {"ADD_TO_CARTS": "CURRENT_ADD_TO_CARTS_NEW", "CAC_ATC": "CURRENT_ADD_TO_CARTS_NEW_CAC"}
DC_FIELDS = ("card_id", "row", "col", "size_x", "size_y", "series", "parameter_mappings", "visualization_settings", "dashboard_tab_id")


def card_rows(mb, cid, params, dim_col, norm=None):
    """{label -> {COL: valeur}} ; exclut la ligne 'Total'. Alignement par libellé insensible à la
    casse. `norm` (optionnel) canonicalise le libellé pour aligner des formats différents (ex.
    périodes '2026 - W22' vs '2026_22') → sinon le décalage de format empêche la compare cellule
    et masque les vrais écarts. dim_col=None (dashcard sans colonne visible) → None : non alignable
    donc non vérifiable → carte gardée sur l'ancien et signalée, au lieu de crasher tout le swap."""
    if dim_col is None:
        return None
    r = mb.post(f"/api/card/{cid}/query", json={"parameters": params}, timeout=300)
    if not isinstance(r, dict) or r.get("status") != "completed":
        return None
    cols = [c["name"].upper() for c in r["data"]["cols"]]
    if dim_col.upper() not in cols:
        return None
    di = cols.index(dim_col.upper())
    out = {}
    for row in r["data"]["rows"]:
        raw = str(row[di]).strip()
        if raw.upper() in ("TOTAL", "∅", "NONE"):
            continue
        out[norm(raw) if norm else raw.upper()] = {cols[i]: v for i, v in enumerate(row)}
    return out


def _close(a, b, tol=1e-6):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a == b
    return a == b or abs(a - b) <= tol * max(abs(a), abs(b), 1e-12)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--window", default="2026-05-01~2026-05-31")
    ap.add_argument("--accept-diffs", action="store_true",
                    help="swappe malgré des écarts de VALEURS connus/validés (cosmétique libellé/casse, "
                         "campagnes edge cost!=0 vs impressions>0). Bloque toujours sur exécution KO / "
                         "colonnes non mappées.")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()
    mapping_all, _ = load_inputs()
    cmap = {int(k): v for k, v in mapping_all.get(args.client, {}).items()}

    dash = mb.get(f"/api/dashboard/{args.copy}")
    base = [{"type": "category", "value": [args.client], "target": ["dimension", ["template-tag", "clients"]]},
            {"type": "date/all-options", "value": args.window, "target": ["dimension", ["template-tag", "date"]]}]

    brand_yes = {"type": "category", "value": ["yes"], "target": ["dimension", ["template-tag", "brand_included"]]}
    new_dcs, report = [], []
    for dc in _dcs(dash):
        cid = dc.get("card_id")
        old_card = mb.get(f"/api/card/{cid}") if cid else None
        target = resolve_table_target(old_card) if old_card else None
        if not target:
            new_dcs.append(dc)
            continue
        target_id, dim_new, is_temporal = target
        old_vsettings = dc.get("visualization_settings") or {}
        old_tc = old_vsettings.get("table.columns") or []
        old_vis = [c["name"] for c in old_tc if c.get("enabled")]
        # table SANS table.columns explicite -> elle affiche TOUTES ses colonnes. On part alors de ses
        # colonnes de RÉSULTAT : les conversions du client sont mappées, les slots positionnels inutilisés
        # restent non mappés et seront MASQUÉS (pas bloquants) -> « garder seulement les conv réelles ».
        implicit_cols = not old_vis
        if implicit_cols:
            old_vis = [x["name"] for x in (old_card.get("result_metadata") or [])]
        old_titles = {k: v.get("column_title") for k, v in (old_vsettings.get("column_settings") or {}).items()
                      if v.get("column_title")}
        target = mb.get(f"/api/card/{target_id}")
        new_cols = [x["name"] for x in target.get("result_metadata") or []]
        target_tc = {e["name"]: e for e in (target.get("visualization_settings") or {}).get("table.columns") or []}

        m, unmapped = conv_lib.map_table_columns(old_vis, cmap, new_cols, dim_new)
        for col in list(unmapped):  # métriques nommées : best-effort
            cand = NAMED_EXTRA.get(col.upper())
            if cand and cand in new_cols:
                m[col] = cand
                unmapped.remove(col)
        # dimension d'alignement = ancienne colonne mappant vers dim_new (sinon 1ère visible)
        old_dim = next((k for k, v in m.items() if v == dim_new), old_vis[0] if old_vis else None)

        # --- vérification cellule par cellule, alignée par libellé, brand=yes (inerte) ---
        old_params = list(base) + [brand_yes]
        _, old_tags = conv_lib.native_and_tags(old_card)
        # params NUMBER requis sans défaut (ex. 'bonus') -> valeur neutre 0, sinon la carte ne s'exécute
        # pas et la vérif est impossible (le dashboard les fournit à l'usage).
        for tname, t in (old_tags or {}).items():
            if (t or {}).get("type") == "number" and (t or {}).get("default") in (None, ""):
                old_params.append({"type": "number/=", "value": 0, "target": ["variable", ["template-tag", tname]]})
        if is_temporal:  # n'épingler la granularité que pour le tableau by-date
            tp = bascule_lib.time_param_payload(old_tags, "week")
            if tp:
                old_params.append(tp)
        new_params = list(base) + [brand_yes]
        if is_temporal:
            new_params.append({"type": "temporal-unit", "value": "week",
                               "target": ["dimension", ["template-tag", "time_period"]]})
        nfn = conv_lib.normalize_period_label if is_temporal else None  # aligne les formats de période
        orows = card_rows(mb, cid, old_params, old_dim, nfn)
        nrows = card_rows(mb, target_id, new_params, dim_new, nfn)
        bad = []
        if orows is None or nrows is None:
            bad.append(("(exécution)", "(exécution)", None, None))
        else:
            labels = set(orows) & set(nrows)
            extra_rows = sorted(set(orows) ^ set(nrows))
            for old_col, new_col in m.items():
                if old_dim and old_col.upper() == old_dim.upper():
                    continue  # la dimension est la clé d'alignement, pas une valeur (casse/format)
                diffs = sum(1 for lb in labels
                            if not _close(orows[lb].get(old_col.upper()), nrows[lb].get(new_col.upper())))
                if diffs:
                    ex = next(lb for lb in labels
                              if not _close(orows[lb].get(old_col.upper()), nrows[lb].get(new_col.upper())))
                    bad.append((old_col, new_col, f"{ex}: {orows[ex].get(old_col.upper())}",
                                f"{nrows[ex].get(new_col.upper())}", diffs))
            if extra_rows:
                bad.append(("(lignes)", "(lignes)", f"écart de lignes: {extra_rows[:6]}", "", len(extra_rows)))

        # blocage DUR : exécution KO toujours ; colonnes non mappées seulement pour une table à colonnes
        # CHOISIES (table implicite -> on MASQUE les non mappées = slots positionnels inutilisés).
        hard = (bool(unmapped) and not implicit_cols) or any(b[0] == "(exécution)" for b in bad)
        value_diffs = [b for b in bad if b[0] != "(exécution)"]
        # DÉCISION user : tout ÉCART DE VALEUR bloque -> REVUE (on ne force jamais un écart réel ;
        # --accept-diffs ne contourne plus les valeurs). unmapped d'une table implicite = colonnes
        # positionnelles masquées, pas un écart.
        blocked = bool(hard) or bool(value_diffs)
        status = "OK" if (not bad and not unmapped) else ("À REVOIR (écart valeur)" if value_diffs else "PARTIEL")
        report.append({"card": cid, "target": target_id, "mapped": len(m), "unmapped": unmapped,
                       "bad": bad, "status": status, "blocked": blocked, "name": old_card.get("name")})
        if blocked:
            new_dcs.append(dc)  # garde l'ancien tableau
            continue

        # --- construit le nouveau dashcard ---
        nd = {k: json.loads(json.dumps(dc.get(k))) for k in DC_FIELDS if dc.get(k) is not None}
        nd["id"] = dc.get("id")
        nd["card_id"] = target_id
        mapped_new = [m[c] for c in old_vis if c in m]
        seen = set(mapped_new)
        new_table_cols = []
        for c in old_vis:
            if c in m and m[c] in target_tc:
                e = dict(target_tc[m[c]]); e["enabled"] = True; new_table_cols.append(e)
        for name, e in target_tc.items():
            if name not in seen:
                e2 = dict(e); e2["enabled"] = False; new_table_cols.append(e2)
        col_settings = {f'["name","{m[c]}"]': old_titles[k]
                        for c in old_vis if c in m
                        for k in [f'["name","{c}"]'] if k in old_titles}
        nd["visualization_settings"] = {"table.columns": new_table_cols, "column_settings": col_settings}
        if old_vsettings.get("card.title"):
            nd["visualization_settings"]["card.title"] = old_vsettings["card.title"]
        # recâble les filtres vers la cible (drop les tags absents de la cible)
        _, ntags = conv_lib.native_and_tags(target)
        pms = []
        for pm in nd.get("parameter_mappings") or []:
            tgt = pm.get("target")
            try:
                tag = tgt[1][1] if tgt[1][0] == "template-tag" else None
            except Exception:
                tag = None
            if tag is None or tag in ntags:
                pm["card_id"] = target_id
                pms.append(pm)
        nd["parameter_mappings"] = pms
        new_dcs.append(nd)

    print(f"Dashboard {args.copy} — swap des tableaux :")
    for r in report:
        verb = ("SWAP -> {}".format(r["target"]) if not r["blocked"]
                else "GARDE ancien")
        flag = "  [écarts acceptés]" if r["status"] == "FORCÉ" else ""
        print(f"  {str(r['name'])[:34]:34} {verb}{flag}  ({r['mapped']} cols mappées)")
        if r["unmapped"]:
            print(f"        NON mappées (bloquant): {r['unmapped']}")
        for b in r["bad"]:
            print(f"        {'•' if r['status']=='FORCÉ' else '⛔'} {b[0]} -> {b[1]} : {b[4] if len(b)>4 else '?'} cellule(s) ≠  (ex. {b[2]} vs {b[3]})")
    swaps = [r for r in report if not r["blocked"]]
    if not args.yes:
        print(f"\n(DRY-RUN — {len(swaps)}/{len(report)} tableaux prêts à swapper. Rien modifié.)")
        return
    if not swaps:
        print("\nAucun tableau swappable — rien à faire."); return
    (REPO / "migration" / f"swap-tables-snapshot-{args.copy}.json").write_text(
        json.dumps(_dcs(dash), ensure_ascii=False))
    put_body = {"dashcards": new_dcs}
    if dash.get("tabs"):
        put_body["tabs"] = dash["tabs"]
    res = mb.put(f"/api/dashboard/{args.copy}", "raw", json=put_body)
    if res.status_code != 200:
        print(f"⛔ PUT échoué: {res.status_code} — {res.text[:300]}"); sys.exit(1)
    print(f"\nPUT {args.copy}: 200 OK ({len(swaps)} tableaux swappés, snapshot pris)")


if __name__ == "__main__":
    main()
