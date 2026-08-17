#!/usr/bin/env python3
"""Ajoute une note (disclaimer) sur la donnée "joueurs" issue de l'API Quiz Room.

Ciblage par (onglet, préfixe de texte). Append d'une note en italique + hauteur
réglée pour qu'elle soit entièrement visible. Reflow des cartes en dessous.
Snapshot + réversible.

  python3 scripts/add_quizroom_disclaimer.py --dashboard 24576         # dry-run
  python3 scripts/add_quizroom_disclaimer.py --dashboard 24576 --yes   # applique
"""
import argparse, json, sys, copy, requests
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
MIG = REPO / "migration"

NOTE_FR = ("\n\n_ℹ️ La fréquentation (nombre de joueurs) provient de l'API Quiz Room. "
           "Elle peut être temporairement indisponible lors d'une mise à jour technique côté Quiz Room ; "
           "le suivi reprend automatiquement une fois celle-ci terminée._")
NOTE_EN = ("\n\n_ℹ️ Footfall (player count) comes from the Quiz Room API. "
           "It may be temporarily unavailable during a technical update on the Quiz Room side; "
           "tracking resumes automatically once it is completed._")

# (tab, prefix, note, new_h)
TARGETS = [
    ("Global", "Le nombre de joueurs", NOTE_FR, 4),
    ("Global", "The player count is your center's", NOTE_EN, 4),
    ("SEO", "Combien de personnes trouvent", NOTE_FR, 3),
    ("SEO", "How many people find", NOTE_EN, 3),
]


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

    deltas = []
    for dc in dcs:
        vs = dc.get("visualization_settings") or {}
        if (vs.get("virtual_card") or {}).get("display") != "text":
            continue
        txt = (vs.get("text") or "").lstrip()
        tab = tabname.get(dc.get("dashboard_tab_id"))
        for ttab, prefix, note, new_h in TARGETS:
            if tab == ttab and txt.startswith(prefix):
                if "Quiz Room" in (vs.get("text") or "") and "API" in (vs.get("text") or ""):
                    print(f"[{tab}] row={dc['row']} note déjà présente, skip")
                    break
                cur = dc.get("size_y")
                vs["text"] = (vs.get("text") or "") + note
                if new_h != cur:
                    deltas.append((dc["dashboard_tab_id"], dc["row"] + cur - 1, new_h - cur))
                    dc["size_y"] = new_h
                print(f"[{tab}] row={dc['row']} h {cur}->{new_h} + note")
                break

    if not deltas:
        print("Rien à faire."); return
    for dc in dcs:
        tab = dc.get("dashboard_tab_id")
        shift = sum(delta for tb, b, delta in deltas if tb == tab and b < orig_row[dc["id"]])
        dc["row"] += shift

    if not args.yes:
        print("\n(DRY-RUN.)"); return
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    MIG.mkdir(exist_ok=True)
    (MIG / f"disclaimer-snapshot-{args.dashboard}-{ts}.json").write_text(
        json.dumps({"dashboard": args.dashboard, "dashcards": d.get("dashcards"), "tabs": d.get("tabs")}, ensure_ascii=False, indent=2))
    payload = {"dashcards": dcs}
    if d.get("tabs"):
        payload["tabs"] = d["tabs"]
    r = requests.put(mb.domain + f"/api/dashboard/{args.dashboard}", headers=mb.header, auth=mb.auth, json=payload, timeout=120)
    print("PUT:", r.status_code); r.raise_for_status()


if __name__ == "__main__":
    main()
