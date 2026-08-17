#!/usr/bin/env python3
"""Répare les mappings de filtres cassés sur les dashboards (campagne erreurs 2026-08-13).

Deux défauts traités, tous deux détectés statiquement (aucune exécution de requête) :
  - orphelin : un filtre de dashboard pointe un template-tag qui n'existe plus sur la carte
               (tag renommé côté carte, dashboard jamais recâblé) ;
  - deletion : ce même filtre n'a aucun successeur plausible sur la carte, le mapping est
               inerte mais casse quand même la requête, on le retire.

Le plan est explicite (migration/errors-2026-08-13/wiring_plan.json) : on ne devine rien à
l'exécution. Chaque dashboard est sauvegardé en entier avant écriture.

    python scripts/fix_dashboard_wiring.py --build-plan
    python scripts/fix_dashboard_wiring.py --dash 768            # dry-run
    python scripts/fix_dashboard_wiring.py --dash 768 --yes      # applique
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

CAMPAIGN_DIR = REPO_ROOT / "migration" / "errors-2026-08-13"
PLAN_PATH = CAMPAIGN_DIR / "wiring_plan.json"
BACKUP_DIR = CAMPAIGN_DIR / "backups"

# Successeurs explicites : tag disparu -> tag actuel de la carte. Volontairement hard-codé
# plutôt que déduit d'une heuristique de préfixe : « campaign » préfixe à la fois
# campaign_name et campaign_network, une heuristique choisirait au hasard.
RENAMES = {
    "account": "account_name",
    "campaign": "campaign_name",
    "client": "client_id",
    "client_id": "client",
}


def load_env():
    env = {}
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def connect():
    env = load_env()
    domain = env["METABASE_DOMAIN"].rstrip("/")
    if not domain.startswith("http"):
        domain = "https://" + domain
    sid = env.get("METABASE_SESSION_ID")
    if not sid or requests.get(
        f"{domain}/api/user/current", headers={"X-Metabase-Session": sid}, timeout=30
    ).status_code != 200:
        r = requests.post(
            f"{domain}/api/session",
            json={"username": env["METABASE_EMAIL"], "password": env["METABASE_PASSWORD"]},
            timeout=60,
        )
        r.raise_for_status()
        sid = r.json()["id"]
    s = requests.Session()
    s.headers.update({"X-Metabase-Session": sid, "Content-Type": "application/json"})
    return domain, s


def card_tags(card):
    """{nom: tag} pour les deux formats : native.template-tags (dict) et MBQL5 stages[] (liste)."""
    out = {}

    def add(tt):
        if isinstance(tt, dict):
            out.update(tt)
        elif isinstance(tt, list):
            for x in tt:
                if isinstance(x, dict) and x.get("name"):
                    out[x["name"]] = x

    dq = card.get("dataset_query") or {}
    if isinstance(dq.get("native"), dict):
        add(dq["native"].get("template-tags"))
    for st in dq.get("stages") or []:
        add((st or {}).get("template-tags"))
    return out


def target_tag(target):
    """Nom du template-tag visé par un target de parameter_mapping, sinon None."""
    if not isinstance(target, list) or len(target) < 2:
        return None
    inner = target[1]
    if not (isinstance(inner, list) and len(inner) > 1 and inner[0] == "template-tag"):
        return None
    name = inner[1]
    return name[1] if isinstance(name, list) and len(name) > 1 else name


def build_plan(domain, s, dash_ids):
    """Construit le plan à partir de l'état live, sans rien écrire."""
    plan = []
    for did in dash_ids:
        d = s.get(f"{domain}/api/dashboard/{did}", timeout=90).json()
        if d.get("archived"):
            print(f"  #{did} archivé, ignoré")
            continue
        params = {p["id"]: p for p in d.get("parameters") or []}
        cards = {}
        for dc in d.get("dashcards") or []:
            for pm in dc.get("parameter_mappings") or []:
                cid = pm.get("card_id")
                if cid is None:
                    continue
                if cid not in cards:
                    cards[cid] = card_tags(s.get(f"{domain}/api/card/{cid}", timeout=60).json())
                tags = cards[cid]
                tag = target_tag(pm.get("target"))
                if tag is None or tag in tags:
                    continue
                successor = RENAMES.get(tag)
                if successor is not None and successor not in tags:
                    successor = None
                plan.append(
                    {
                        "dash": did,
                        "dash_name": d.get("name"),
                        "dashcard": dc["id"],
                        "card": cid,
                        "parameter_id": pm["parameter_id"],
                        "param_name": (params.get(pm["parameter_id"]) or {}).get("name"),
                        "from_tag": tag,
                        "action": "repoint" if successor else "delete",
                        "to_tag": successor,
                    }
                )
    return plan


def apply_dash(domain, s, did, entries, dry_run=True):
    d = s.get(f"{domain}/api/dashboard/{did}", timeout=90).json()
    if d.get("archived"):
        print(f"  #{did} archivé, on ne touche pas")
        return None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"dashboard-{did}-{stamp}.json"
    backup.write_text(json.dumps(d, ensure_ascii=False, indent=1))

    by_dashcard = {}
    for e in entries:
        by_dashcard.setdefault(e["dashcard"], []).append(e)

    changed = 0
    for dc in d.get("dashcards") or []:
        todo = by_dashcard.get(dc["id"])
        if not todo:
            continue
        keep = []
        for pm in dc.get("parameter_mappings") or []:
            match = next(
                (
                    e
                    for e in todo
                    if e["parameter_id"] == pm["parameter_id"]
                    and e["card"] == pm.get("card_id")
                    and target_tag(pm.get("target")) == e["from_tag"]
                ),
                None,
            )
            if match is None:
                keep.append(pm)
                continue
            changed += 1
            if match["action"] == "delete":
                print(f'    - tuile {dc["id"]} : retire «{match["param_name"]}» → {match["from_tag"]}')
                continue
            new_pm = json.loads(json.dumps(pm))
            new_pm["target"][1][1] = match["to_tag"]
            print(
                f'    ~ tuile {dc["id"]} : «{match["param_name"]}» {match["from_tag"]} → {match["to_tag"]}'
            )
            keep.append(new_pm)
        dc["parameter_mappings"] = keep

    if dry_run:
        print(f"  DRY-RUN #{did} : {changed} mappings seraient modifiés (backup {backup.name})")
        return changed

    body = {"dashcards": d["dashcards"]}
    if d.get("tabs"):
        # PUT /api/dashboard sur un dashboard à onglets doit inclure `tabs`, sinon 500 (FK).
        body["tabs"] = d["tabs"]
    r = s.put(f"{domain}/api/dashboard/{did}", json=body, timeout=180)
    if r.status_code >= 300:
        print(f"  ÉCHEC #{did} : HTTP {r.status_code} {r.text[:300]}")
        return None
    print(f"  OK #{did} : {changed} mappings corrigés (backup {backup.name})")
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--build-plan", action="store_true", help="reconstruit le plan depuis le live")
    ap.add_argument("--dash", type=int, action="append", help="limite aux dashboards donnés")
    ap.add_argument(
        "--action",
        choices=["repoint", "delete"],
        help="ne traite qu'un type d'action. repoint = rebranche un filtre sur le tag renommé "
        "(seul geste qui remet une tuile en vert) ; delete = hygiène, retire un mapping inerte "
        "que Metabase ignore déjà en silence.",
    )
    ap.add_argument("--yes", action="store_true", help="applique réellement (sinon dry-run)")
    args = ap.parse_args()

    domain, s = connect()

    if args.build_plan:
        src = json.loads((CAMPAIGN_DIR / "wiring_live_plan.json").read_text())
        dash_ids = sorted({e["dash"] for e in src})
        plan = build_plan(domain, s, dash_ids)
        PLAN_PATH.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
        print(f"plan écrit : {len(plan)} actions dans {PLAN_PATH}")
        for e in plan:
            print(
                f'  #{e["dash"]:6} tuile {e["dashcard"]:7} carte {e["card"]:6} '
                f'{e["action"]:8} «{e["param_name"]}» {e["from_tag"]}'
                + (f' → {e["to_tag"]}' if e["to_tag"] else "")
            )
        return

    plan = json.loads(PLAN_PATH.read_text())
    if args.dash:
        plan = [e for e in plan if e["dash"] in args.dash]
    if args.action:
        plan = [e for e in plan if e["action"] == args.action]
    if not plan:
        sys.exit("Rien à faire pour ce périmètre.")

    by_dash = {}
    for e in plan:
        by_dash.setdefault(e["dash"], []).append(e)
    for did, entries in sorted(by_dash.items()):
        print(f'\nDASH #{did} «{entries[0]["dash_name"]}» : {len(entries)} actions')
        apply_dash(domain, s, did, entries, dry_run=not args.yes)


if __name__ == "__main__":
    main()
