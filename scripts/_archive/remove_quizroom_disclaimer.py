#!/usr/bin/env python3
"""Retire la note disclaimer Quiz Room (données revenues) + remet les hauteurs + reflow.
Inverse de add_quizroom_disclaimer.py. Snapshot + réversible.

  python3 scripts/remove_quizroom_disclaimer.py --dashboard 24576         # dry-run
  python3 scripts/remove_quizroom_disclaimer.py --dashboard 24576 --yes
"""
import argparse, json, sys, copy, requests
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
MIG = REPO / "migration"

MARK = "\n\n_ℹ️"  # début de la note appondue

# (tab, prefix, hauteur d'origine sans la note)
TARGETS = [
    ("Global", "Le nombre de joueurs", 2),
    ("Global", "The player count is your center's", 2),
    ("SEO", "Combien de personnes trouvent", 1),
    ("SEO", "How many people find", 1),
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
        txt = vs.get("text") or ""
        tab = tabname.get(dc.get("dashboard_tab_id"))
        for ttab, prefix, new_h in TARGETS:
            if tab == ttab and txt.lstrip().startswith(prefix):
                if MARK not in txt:
                    print(f"[{tab}] row={dc['row']} pas de note, skip")
                    break
                cur = dc.get("size_y")
                vs["text"] = txt.split(MARK)[0].rstrip()
                if new_h != cur:
                    deltas.append((dc["dashboard_tab_id"], dc["row"] + cur - 1, new_h - cur))
                    dc["size_y"] = new_h
                print(f"[{tab}] row={dc['row']} note retirée, h {cur}->{new_h}")
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
    (MIG / f"rmdisclaimer-snapshot-{args.dashboard}-{ts}.json").write_text(
        json.dumps({"dashboard": args.dashboard, "dashcards": d.get("dashcards"), "tabs": d.get("tabs")}, ensure_ascii=False, indent=2))
    payload = {"dashcards": dcs}
    if d.get("tabs"):
        payload["tabs"] = d["tabs"]
    r = requests.put(mb.domain + f"/api/dashboard/{args.dashboard}", headers=mb.header, auth=mb.auth, json=payload, timeout=120)
    print("PUT:", r.status_code); r.raise_for_status()


if __name__ == "__main__":
    main()
