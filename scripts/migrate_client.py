#!/usr/bin/env python3
"""Orchestrateur : migre une liste de dashboards d'un client de bout en bout, sur des
COPIES. Pour chaque dashboard original : copie shallow → reuse (conversions) → swap_tables
(tableaux) → bascule_time_filter --auto-prepare (filtre temps). Politique d'écarts :
--accept-diffs partout (petit écart = nouveau mapping fait foi) ; les conflits / no-match
restent sur l'ancien (signalés par chaque étape).

Usage :
  python3 scripts/migrate_client.py --client "Father and Sons" --dashboards 11804,15963 --test-collection 13917
  ... ajouter --yes pour appliquer (sinon dry-run des 3 étapes).
"""
import argparse, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from archive_collections import connect_resilient
import conv_tracker
import conv_lib

PY = str(REPO / ".venv" / "bin" / "python")


def run_step(script, copy, client, extra, yes):
    cmd = [PY, str(REPO / "scripts" / script), "--copy", str(copy), "--client", client] + extra
    if yes:
        cmd.append("--yes")
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    tail = "\n".join((out.stdout or "").strip().splitlines()[-4:])
    # exit≠0 : remonter aussi le stderr (sys.exit bénin « Pas de param… » OU vrai traceback) —
    # sans ça, les deux sont indistinguables (sortie = juste la ligne d'auth). Levée du point aveugle.
    if out.returncode != 0 and (out.stderr or "").strip():
        tail += "\n  [stderr] " + "\n  [stderr] ".join((out.stderr).strip().splitlines()[-3:])
    return tail, (out.returncode == 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--dashboards", required=True, help="ids ORIGINAUX séparés par virgules")
    ap.add_argument("--test-collection", type=int, default=13917)
    ap.add_argument("--name-prefix", default="[TEST conv]")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    origs = [int(x) for x in args.dashboards.split(",") if x.strip()]
    mb = connect_resilient()

    for orig in origs:
        d = mb.get(f"/api/dashboard/{orig}")
        name = d.get("name", str(orig))
        copy_name = conv_tracker.apply_tag(f"{args.name_prefix} {name}")  # ancre de campagne
        # « Dashboard Questions » (cartes intégrées) → Metabase refuse la copie shallow → deep copy.
        deep = conv_lib.has_dashboard_questions(d)
        cp = mb.post(f"/api/dashboard/{orig}/copy",
                     json={"name": copy_name, "collection_id": args.test_collection,
                           "is_deep_copy": deep})
        copy = cp.get("id") if isinstance(cp, dict) else None
        print(f"\n### {orig} «{name}» → copie {copy}" + ("  [deep copy: Dashboard Questions]" if deep else ""))
        if not copy:
            print("  ⛔ copie échouée"); continue
        # consigne la paire ancien→copie dans le registre (pilote archive_superseded.py)
        tr = conv_tracker.upsert_entry(conv_tracker.load(), {
            "client": args.client, "dashboard": name, "copy_id": copy, "original_id": orig,
            "tagged": True, "status": "migré", "archive_old": False, "old_archived": False, "notes": ""})
        conv_tracker.save(tr); conv_tracker.render_to_file(tr)
        for script, extra in [
            ("migrate_dashboard_reuse.py", ["--source", str(orig), "--planned-temporal-unit", "--accept-diffs"]),
            ("swap_tables.py", ["--accept-diffs"]),
            ("deploy_special_cards.py", []),    # cartes sélecteur #87 -> 49788 (AVANT la bascule)
            ("bascule_time_filter.py", ["--auto-prepare"]),
            ("generate_fallback.py", []),       # génère les tuiles sans équivalent (objectif 100%)
            ("polish_generated_viz.py", []),    # repolit la viz des cartes générées
        ]:
            tail, ok = run_step(script, copy, args.client, extra, args.yes)
            print(f"  --- {script} {'' if ok else '(exit≠0)'}")
            for line in tail.splitlines():
                print(f"      {line}")


if __name__ == "__main__":
    main()
