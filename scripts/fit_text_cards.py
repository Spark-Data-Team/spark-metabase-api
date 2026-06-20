#!/usr/bin/env python3
"""Ajuste la hauteur des cartes texte à leur contenu (supprime le blanc) + reflow.

Estimation CONSERVATRICE des lignes (on surestime un peu pour ne JAMAIS tronquer).
SHRINK uniquement : new_h = min(current_h, estimate). Jamais d'agrandissement.
Les cartes vides (espaceurs de section) et les headings (h=1) sont laissés tels quels.
Reflow : quand une carte rétrécit de delta, on remonte de delta les cartes du même
onglet situées dessous.

Usage:
  python3 scripts/fit_text_cards.py --dashboard 24576           # dry-run (tableau)
  python3 scripts/fit_text_cards.py --dashboard 24576 --yes     # applique + snapshot
"""
import argparse, json, sys, copy, math, requests
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
MIG = REPO / "migration"

CPR = 100        # caractères par ligne en pleine largeur (24 col)
CAP = 1.6        # lignes visuelles par rangée de grille
PAD = 0.4        # marge interne (rangée)


def content_rows(text):
    visual = 0.0
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if not s:
            visual += 0.5            # saut de paragraphe
            continue
        visual += max(1, math.ceil(len(s) / CPR))
    return max(1, math.ceil((visual + PAD) / CAP))


def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", type=int, required=True)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    mb = connect()
    d = mb.get(f"/api/dashboard/{args.dashboard}")
    dcs = copy.deepcopy(d.get("dashcards") or [])
    tabname = {t["id"]: t["name"] for t in (d.get("tabs") or [])}

    orig_row = {dc["id"]: dc.get("row") for dc in dcs}
    shrinks = []  # (tab_id, boundary_row, delta)
    print(f"{'tab':10} {'row':>3} {'cur':>3} {'fit':>3} {'slack':>5}  text")
    for dc in dcs:
        vs = dc.get("visualization_settings") or {}
        vc = vs.get("virtual_card") or {}
        if vc.get("display") != "text":
            continue
        txt = (vs.get("text") or "").strip()
        if not txt:
            continue  # espaceur volontaire
        cur = dc.get("size_y")
        fit = content_rows(txt)
        new_h = min(cur, fit)
        slack = cur - new_h
        if slack > 0:
            print(f"{tabname.get(dc['dashboard_tab_id'],'?'):10} {dc['row']:>3} {cur:>3} {new_h:>3} {slack:>5}  {txt[:50]!r}")
            shrinks.append((dc["dashboard_tab_id"], dc["row"] + cur - 1, slack))
            dc["size_y"] = new_h

    if not shrinks:
        print("\nAucun slack détecté.")
        return

    # reflow : remonter les cartes situées sous chaque carte rétrécie (coords figées)
    for dc in dcs:
        tab = dc.get("dashboard_tab_id")
        up = sum(delta for tb, b, delta in shrinks if tb == tab and b < orig_row[dc["id"]])
        dc["row"] -= up

    print(f"\n{len(shrinks)} carte(s) rétrécie(s).")
    if not args.yes:
        print("(DRY-RUN — aucune modification.)")
        return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    MIG.mkdir(exist_ok=True)
    (MIG / f"fit-snapshot-{args.dashboard}-{ts}.json").write_text(
        json.dumps({"dashboard": args.dashboard, "dashcards": d.get("dashcards"), "tabs": d.get("tabs")}, ensure_ascii=False, indent=2))
    payload = {"dashcards": dcs}
    if d.get("tabs"):
        payload["tabs"] = d["tabs"]
    r = requests.put(mb.domain + f"/api/dashboard/{args.dashboard}", headers=mb.header, auth=mb.auth, json=payload, timeout=120)
    print("PUT:", r.status_code); r.raise_for_status()


if __name__ == "__main__":
    main()
