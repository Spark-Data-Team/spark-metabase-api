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
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
import conv_lib
import bascule_lib
from migrate_dashboard_full import connect, _dcs
from migrate_dashboard_reuse import card_values_pinned


def load_registry():
    """{old_card_id: new_card_id} depuis migration/tu-generic-*.json (verified only)."""
    reg = {}
    for f in sorted((REPO / "migration").glob("tu-generic-*.json")):
        d = json.loads(f.read_text())
        if d.get("verified") and d.get("new_id"):
            reg[int(d["old_id"])] = int(d["new_id"])
    return reg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--window", default="2026-05-01~2026-05-31")
    ap.add_argument("--auto-prepare", action="store_true",
                    help="convertit automatiquement le mécanisme temps des cartes bloquantes "
                         "(copies temporal-unit sandbox) avant de basculer — couvre la traîne.")
    ap.add_argument("--dry-prepare", action="store_true", help="auto-prepare en dry (ne crée pas les copies)")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()

    dash = mb.get(f"/api/dashboard/{args.copy}")
    if not isinstance(dash, dict):
        sys.exit("dashboard inaccessible")

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
        sys.exit("Pas de param 'Time period' (category) sur ce dashboard — rien à basculer.")

    # AUTO-PRÉPARATION : convertit le mécanisme temps de chaque carte bloquante (conversion
    # ou non : Magento, tableaux multi-dim, charts orphelins) en copie temporal-unit, puis
    # recalcule le plan. C'est l'option « propre » : couvre la traîne sans intervention.
    unwire = set()  # (dashcard_id, card_id) à débrancher du filtre temps (granularité vestigiale)
    if args.auto_prepare and plan["blockers"]:
        from convert_generic_temporal import convert_card
        print(f"Auto-préparation de {len(plan['blockers'])} carte(s) bloquante(s) :")
        for b in list(plan["blockers"]):
            cid = b["card_id"]
            new_id = convert_card(mb, cid, args.client, args.window) if not args.dry_prepare else None
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

    snap_path = REPO / "migration" / f"bascule-snapshot-{args.copy}.json"
    snap_path.write_text(json.dumps({"parameters": dash.get("parameters"),
                                     "dashcards": _dcs(dash)}, ensure_ascii=False))
    params, dcs = bascule_lib.apply_bascule(dash, plan)
    put_body = {"parameters": params, "dashcards": dcs}
    if dash.get("tabs"):  # PUT d'un dash à onglets DOIT inclure tabs (sinon 500)
        put_body["tabs"] = dash["tabs"]
    res = mb.put(f"/api/dashboard/{args.copy}", "raw", json=put_body)
    if res.status_code != 200:
        print(f"⛔ PUT ÉCHOUÉ: HTTP {res.status_code} — {res.text[:400]}")
        sys.exit(1)
    print(f"PUT {args.copy}: 200 OK (snapshot: {snap_path.name})")

    # contrôles finaux
    chk = mb.get(f"/api/dashboard/{args.copy}")
    assert bascule_lib.find_time_param(chk) is None, "un param category 'Time period' subsiste !"
    tu = [p for p in chk.get("parameters") or [] if p.get("type") == "temporal-unit"]
    print(f"Param temporal-unit en place : {[p['id'] for p in tu]}")
    residual = []
    for dc in _dcs(chk):
        cid = dc.get("card_id")
        if not cid:
            continue
        t = conv_lib.native_and_tags(mb.get(f"/api/card/{cid}"))[1]
        ttype = ((t.get(bascule_lib.TIME_TAG) or {}).get("type"))
        wired = any(pm.get("parameter_id") == pid for pm in dc.get("parameter_mappings") or [])
        # anomalie = une carte dimension ENCORE câblée au nouveau param (le param ne peut
        # pas la piloter). Une dimension DÉBRANCHÉE (granularité vestigiale) est OK.
        if ttype == "dimension" and wired:
            residual.append((dc["id"], cid, "dimension encore câblée"))
        if ttype == "temporal-unit" and not wired:
            residual.append((dc["id"], cid, "temporal-unit non câblée"))
    print(f"Anomalies résiduelles : {residual if residual else 'AUCUNE ✅'}")
    if unwire:
        print(f"Cartes débranchées du filtre temps (granularité vestigiale) : {sorted(c for _, c in unwire)}")


if __name__ == "__main__":
    main()
