#!/usr/bin/env python3
"""Migration COMPLÈTE d'un dashboard : AUCUNE tuile ne reste sur l'ancien système.
Par tuile : carte nouvelle pré-existante si elle correspond exactement (avant==après),
sinon on GÉNÈRE une copie exacte (substitution des colonnes de conversion). Chaque tuile
est classée `identique ✅` ou `valeur changée ⚠️` (ex. Main conversion -> Purchases).
Copy-first, snapshot, réversible.

Usage:
  python3 scripts/migrate_dashboard_full.py --dashboard 14016 --client "Pro Nutrition"           # dry-run (rapport)
  python3 scripts/migrate_dashboard_full.py --dashboard 14016 --client "Pro Nutrition" --copy --yes
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
import swap_lib, conv_lib
MIG = REPO / "migration"

def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])

def _dcs(d): return d.get("dashcards") or d.get("ordered_cards") or []

def load_inputs():
    mapping = json.loads((MIG / "conv-client-mapping.json").read_text())
    raw = json.loads((MIG / "conv-new-index.json").read_text())
    index = {}
    for k, v in raw.items():
        col, bd = json.loads(k); index[(col, tuple(bd))] = v
    return mapping, index

def card_values(mb, card_id, client, window):
    c = mb.get(f"/api/card/{card_id}"); _, tags = conv_lib.native_and_tags(c)
    params = []
    if "clients" in tags: params.append({"type": "string/=", "value": [client], "target": ["dimension", ["template-tag", "clients"]]})
    if "date" in tags: params.append({"type": "date/all-options", "value": window, "target": ["dimension", ["template-tag", "date"]]})
    r = mb.post(f"/api/card/{card_id}/query", json={"parameters": params}, timeout=180)
    rows = (r or {}).get("data", {}).get("rows", []) or []
    return sorted(round(float(x), 4) for row in rows for x in row if isinstance(x, (int, float)))

def generate_card(mb, old_card, sub_map, coll_id, cmap=None):
    dq = json.loads(json.dumps(old_card["dataset_query"]))
    for st in dq.get("stages", []) or []:
        if st.get("lib/type") == "mbql.stage/native":
            st["native"] = conv_lib.apply_substitution(st["native"], sub_map)
    if dq.get("type") == "native":
        dq["native"]["query"] = conv_lib.apply_substitution(dq["native"]["query"], sub_map)
    viz = conv_lib.substitute_viz(old_card.get("visualization_settings") or {}, sub_map)  # préserve les libellés humains
    # titre générique (« Conversions ») -> conversion nommée (« Purchases ») ; libellé métier préservé
    if cmap and viz.get("card.title"):
        viz["card.title"] = conv_lib.relabel_conversion_title(
            viz["card.title"], conv_lib.conversion_display_names(sub_map, cmap))
    # nom propre (pas de préfixe « [migré] » : la tuile l'afficherait au consultant) ; la provenance
    # vient de la collection dédiée 14115 + du registre generated-cards.json.
    r = mb.post("/api/card", json={"name": old_card["name"], "dataset_query": dq,
                                   "display": old_card.get("display"), "visualization_settings": viz,
                                   "collection_id": coll_id})
    return r.get("id") if isinstance(r, dict) else None

def head(vals): return vals[-1] if vals else None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--copy", action="store_true"); ap.add_argument("--yes", action="store_true")
    ap.add_argument("--window", default="2026-05-01~2026-05-31")
    ap.add_argument("--gen-collection", type=int, default=13851)
    args = ap.parse_args()
    mb = connect()
    mapping_all, index = load_inputs()
    cmap = {int(k): v for k, v in mapping_all.get(args.client, {}).items()}
    if not cmap: sys.exit(f"Aucun mapping pour {args.client!r}.")

    src = args.dashboard
    if args.copy and args.yes:
        cp = mb.post(f"/api/dashboard/{src}/copy", json={"collection_id": None, "name": f"[TEST nouvelles conversions] {src}", "is_deep_copy": False})
        src = cp["id"]; print(f"copie -> dashboard {src}")
    dash = mb.get(f"/api/dashboard/{src}"); dcs = _dcs(dash)

    gen_cache, plan, report = {}, [], []
    for dc in dcs:
        cid = dc.get("card_id")
        if not cid: continue
        card = mb.get(f"/api/card/{cid}"); sql, _ = conv_lib.native_and_tags(card)
        old_cols = conv_lib.old_conversion_columns(sql)
        if not old_cols: continue
        # On GÉNÈRE une copie exacte (mêmes alias/colonnes que l'ancienne -> rendu garanti).
        sub_map, unmapped = conv_lib.substitution_map(old_cols, cmap)
        if not sub_map:
            report.append({"tile": card.get("name"), "status": "BLOQUÉ", "reason": f"slots non mappés: {sorted(unmapped)}"}); continue
        key = (cid, tuple(sorted(sub_map.items())))
        chosen = gen_cache.get(key) or generate_card(mb, card, sub_map, args.gen_collection)
        gen_cache[key] = chosen
        new_sql, _ = conv_lib.native_and_tags(mb.get(f"/api/card/{chosen}"))
        residual = sorted(conv_lib.old_conversion_columns(new_sql))
        before, after = card_values(mb, cid, args.client, args.window), card_values(mb, chosen, args.client, args.window)
        report.append({"tile": card.get("name"), "method": "générée", "old_card": cid, "new_card": chosen,
                       "identical": before == after, "before": head(before), "after": head(after),
                       "unmapped": sorted(unmapped), "residual_old": residual})
        plan.append((dc, cid, chosen, sub_map, {}))

    # rapport
    print(f"\n{'TUILE':42} {'MÉTHODE':12} {'AVANT':>12} {'APRÈS':>12}  ÉTAT")
    for r in report:
        if r.get("status") == "BLOQUÉ":
            print(f"{r['tile'][:42]:42} {'—':12} {'':>12} {'':>12}  ⛔ {r['reason']}"); continue
        flag = "✅ identique" if r["identical"] else "⚠️ VALEUR CHANGÉE"
        warn = (f" · slots non mappés {r['unmapped']}" if r["unmapped"] else "") + (f" · ancien restant {r['residual_old']}" if r["residual_old"] else "")
        print(f"{r['tile'][:42]:42} {r['method']:12} {str(r['before']):>12} {str(r['after']):>12}  {flag}{warn}")
    MIG.mkdir(exist_ok=True)
    (MIG / f"conv-full-report-{src}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    if not args.yes or not plan:
        print("\n(DRY-RUN — aucune modification du dashboard.)"); return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = MIG / f"conv-full-snapshot-{src}-{ts}.json"
    snap.write_text(json.dumps({"dashboard": src, "dashcards": dcs}, ensure_ascii=False, indent=2))
    new_dcs = dcs
    for dc, old_cid, new_cid, sub_map, renames in plan:
        new_dcs, _ = swap_lib.rewrite_dashcards(new_dcs, old_cid, new_cid)
        for ndc in new_dcs:
            if ndc.get("id") == dc.get("id"):
                if ndc.get("visualization_settings"):
                    ndc["visualization_settings"] = json.loads(conv_lib.apply_substitution(json.dumps(ndc["visualization_settings"]), sub_map))
                for pm in ndc.get("parameter_mappings") or []:
                    tg = pm.get("target")
                    try:
                        if tg[1][0] == "template-tag" and tg[1][1] in renames: tg[1][1] = renames[tg[1][1]]
                    except Exception: pass
    rc = mb.put(f"/api/dashboard/{src}", json={"dashcards": new_dcs})
    print(f"\nPUT dashboard {src}: {rc} | snapshot: {snap}")
    # contrôle final : plus aucune tuile sur l'ancien système ?
    chk = mb.get(f"/api/dashboard/{src}"); left, broken = [], []
    for dc in _dcs(chk):
        c = dc.get("card_id")
        if not c:
            continue
        card = mb.get(f"/api/card/{c}")
        if conv_lib.old_conversion_columns(conv_lib.native_and_tags(card)[0]):
            left.append(c)
        gm = (dc.get("visualization_settings") or {}).get("graph.metrics") or []
        # contrôle rendu (graphes uniquement — les scalaires ignorent graph.metrics ; insensible casse)
        if gm and card.get("display") not in conv_lib._SCALAR_DISPLAYS:
            r = mb.post(f"/api/card/{c}/query", json={"parameters": [{"type": "string/=", "value": [args.client],
                        "target": ["dimension", ["template-tag", "clients"]]}]}, timeout=120)
            cols = {str(x.get("name")).upper() for x in (r or {}).get("data", {}).get("cols", []) or []}
            miss = [m for m in gm if str(m).upper() not in cols]
            if miss:
                broken.append({"dashcard": dc.get("id"), "card": c, "missing": miss})
    print(f"Tuiles encore sur ANCIEN système (slots non mappés cachés): {left if left else 'AUCUNE ✅'}")
    print(f"Graphes au RENDU cassé (série inexistante): {broken if broken else 'AUCUNE ✅'}")

if __name__ == "__main__":
    main()
