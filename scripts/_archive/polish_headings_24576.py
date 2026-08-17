#!/usr/bin/env python3
"""Uniformise les titres de section d'un dashboard vers le type `heading` natif.

Cible : les cartes texte AUTONOMES dont le contenu est une seule ligne commençant
par `#` (titres H1/H2 markdown). Elles sont converties en cartes `heading` natives
(taille moyenne unique, alignée sur les headings déjà présents). Les cartes Q&R
multi-lignes (FAQ `#### …` + corps) ne sont PAS touchées.

Réversible (snapshot). Workflow conseillé : --copy --yes pour tester, puis --yes.

Usage:
  python3 scripts/polish_headings_24576.py --dashboard 24576              # dry-run
  python3 scripts/polish_headings_24576.py --dashboard 24576 --copy --yes # test sur une copie
  python3 scripts/polish_headings_24576.py --dashboard 24576 --yes        # applique + snapshot
"""
import argparse, json, sys, copy, re
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

MIG = REPO / "migration"


def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])


def _dashcards(d):
    return d.get("dashcards") or d.get("ordered_cards") or []


def is_title_text_card(vs):
    """True si carte texte autonome = une seule ligne non vide commençant par '#'."""
    if not vs or vs.get("text") is None:
        return False
    vc = vs.get("virtual_card") or {}
    if vc.get("display") != "text":
        return False
    lines = [l for l in (vs["text"] or "").strip().splitlines() if l.strip()]
    return len(lines) == 1 and lines[0].lstrip().startswith("#")


def to_heading(vs):
    """Retourne une copie de vs convertie en carte heading native."""
    out = copy.deepcopy(vs)
    title = re.sub(r"^\s*#+\s*", "", out["text"].strip())
    out["text"] = title
    vc = out.get("virtual_card") or {}
    vc["display"] = "heading"
    out["virtual_card"] = vc
    out.setdefault("dashcard.background", False)
    out.pop("text.align_vertical", None)
    out.pop("text.align_horizontal", None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", type=int, required=True)
    ap.add_argument("--copy", action="store_true", help="opère sur une copie de test")
    ap.add_argument("--yes", action="store_true", help="applique réellement")
    args = ap.parse_args()

    mb = connect()
    src = args.dashboard
    if args.copy and args.yes:
        cp = mb.post(f"/api/dashboard/{src}/copy", json={"collection_id": None, "name": f"POLISH TEST {src}", "is_deep_copy": False})
        src = cp["id"]
        print(f"copie -> dashboard {src}")

    dash = mb.get(f"/api/dashboard/{src}")
    dcs = _dashcards(dash)

    targets = []
    for dc in dcs:
        vs = dc.get("visualization_settings") or {}
        if is_title_text_card(vs):
            targets.append(dc)

    print(f"{len(targets)} carte(s) titre à convertir :")
    for dc in targets:
        vs = dc["visualization_settings"]
        print(f"  tab={dc.get('dashboard_tab_id')} row={dc.get('row')} h={dc.get('size_y')} | {vs['text']!r} -> heading {to_heading(vs)['text']!r}")

    if not args.yes or not targets:
        print("\n(DRY-RUN ou rien à faire — aucune modification.)")
        return

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    MIG.mkdir(exist_ok=True)
    snap = MIG / f"polish-snapshot-{src}-{ts}.json"
    snap.write_text(json.dumps({"dashboard": src, "dashcards": dcs}, ensure_ascii=False, indent=2))
    print(f"snapshot: {snap}")

    new_dcs = copy.deepcopy(dcs)
    tids = {dc["id"] for dc in targets}
    for ndc in new_dcs:
        if ndc.get("id") in tids:
            ndc["visualization_settings"] = to_heading(ndc["visualization_settings"])
    # Dashboards à onglets : il FAUT renvoyer `tabs`, sinon FK violation (500).
    payload = {"dashcards": new_dcs}
    if dash.get("tabs"):
        payload["tabs"] = dash["tabs"]
    rc = mb.put(f"/api/dashboard/{src}", "raw", json=payload)
    print(f"PUT dashboard {src}: HTTP {rc.status_code} ({len(targets)} converties)")
    rc.raise_for_status()


if __name__ == "__main__":
    main()
