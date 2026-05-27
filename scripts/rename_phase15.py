#!/usr/bin/env python3
"""CLI de normalisation des noms de cartes — collection Metabase 215.

Sous-commandes : snapshot | propose | apply | verify | rollback.
Voir docs/superpowers/specs/2026-05-21-card-naming-normalization-phase1.5-design.md
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from rename_lib import (  # noqa: E402
    capture_snapshot, propose_renames, verify_invariant,
    CardRecord, ROOT_COLLECTION_ID,
)

MIGRATION_DIR = REPO_ROOT / "migration"


def _load_env() -> dict:
    env = {}
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def connect() -> Metabase_API:
    env = _load_env()
    domain = env.get("METABASE_DOMAIN") or os.environ.get("METABASE_DOMAIN")
    session_id = env.get("METABASE_SESSION_ID") or os.environ.get("METABASE_SESSION_ID")
    email = env.get("METABASE_EMAIL") or os.environ.get("METABASE_EMAIL")
    password = env.get("METABASE_PASSWORD") or os.environ.get("METABASE_PASSWORD")
    if not domain:
        sys.exit("METABASE_DOMAIN manquant.")
    if session_id:
        mb = Metabase_API(domain=domain, session_id=session_id)
        if mb.is_session_valid():
            return mb
        print("session_id expiré — bascule sur email/password.")
    if not (email and password):
        sys.exit("Aucune session valide et METABASE_EMAIL/PASSWORD manquants.")
    return Metabase_API(domain=domain, email=email, password=password)


def _snapshot_to_dict(snap: dict[int, CardRecord]) -> dict:
    return {"cards": [asdict(r) for r in snap.values()]}


def _snapshot_from_dict(data: dict) -> dict[int, CardRecord]:
    return {c["id"]: CardRecord(**c) for c in data["cards"]}


def cmd_snapshot(args):
    mb = connect()
    print(f"Capture du sous-arbre de la collection {ROOT_COLLECTION_ID} "
          f"(hors Nouvelles Conversions)...")
    snap = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = MIGRATION_DIR / f"rename-snapshot-{ts}.json"
    out.write_text(json.dumps(_snapshot_to_dict(snap), indent=2, ensure_ascii=False))
    print(f"  {len(snap)} cartes capturées")
    print(f"Snapshot écrit : {out}")


def cmd_propose(args):
    snap = _snapshot_from_dict(json.loads(Path(args.snapshot).read_text()))
    rows = propose_renames(snap)
    # Tri : décisions d'abord, puis par nom courant
    rows.sort(key=lambda r: (0 if r.status == "décision" else 1, r.current_name))
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["card_id", "current_name", "proposed_name",
                    "rule", "status", "notes"])
        for r in rows:
            w.writerow([r.card_id, r.current_name, r.proposed_name,
                        r.rule, r.status, r.notes])
    by_status = {"auto": 0, "décision": 0}
    by_rule: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_rule[r.rule] = by_rule.get(r.rule, 0) + 1
    print(f"Proposition écrite : {out}")
    print(f"  {len(rows)} lignes — auto: {by_status['auto']}, "
          f"décision: {by_status['décision']}")
    print(f"  par règle : " + ", ".join(f"{k}={v}" for k, v in sorted(by_rule.items())))
    print("\n→ Relis et édite le CSV avant `apply`.")


def _check(status, what):
    """`mb.put` renvoie un code HTTP — on échoue fort si non-2xx."""
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"{what} a échoué — HTTP {status}")


def _load_proposal(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cmd_apply(args):
    baseline = _snapshot_from_dict(json.loads(Path(args.snapshot).read_text()))
    proposal = _load_proposal(Path(args.proposal))
    # Filtrer : ne renommer que les lignes où proposed != current ET proposed non vide
    to_apply = [r for r in proposal
                if r["proposed_name"] and r["proposed_name"] != r["current_name"]]
    if not to_apply:
        print("Aucun renommage à appliquer.")
        return

    print(f"\n=== Renommages à appliquer : {len(to_apply)} ===")
    for r in to_apply[:20]:
        print(f"  #{r['card_id']:>6} : {r['current_name']!r} -> {r['proposed_name']!r}  "
              f"[{r['rule']}/{r['status']}]")
    if len(to_apply) > 20:
        print(f"  ... ({len(to_apply) - 20} de plus)")
    if not args.yes:
        if input(f"\nAppliquer ces {len(to_apply)} renommages ? [tape 'oui'] "
                 ).strip() != "oui":
            sys.exit("Annulé.")

    mb = connect()
    for r in to_apply:
        cid = int(r["card_id"])
        new_name = r["proposed_name"]
        _check(mb.put(f"/api/card/{cid}", json={"name": new_name}),
               f"renommage carte {cid}")
        print(f"  #{cid} -> {new_name!r}")

    print("\nVérification d'invariant post-batch...")
    current = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    divergences = verify_invariant(baseline, current)
    if divergences:
        print("DIVERGENCES DÉTECTÉES — ARRÊT :")
        for d in divergences:
            print(f"  [{d.kind}] carte {d.card_id} : {d.detail}")
        sys.exit(1)
    print(f"OK — {len(current)} cartes intactes (hors changement de nom), "
          f"0 divergence.")


def cmd_verify(args):
    baseline = _snapshot_from_dict(json.loads(Path(args.snapshot).read_text()))
    mb = connect()
    current = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    divergences = verify_invariant(baseline, current)
    if divergences:
        print(f"{len(divergences)} divergence(s) :")
        for d in divergences:
            print(f"  [{d.kind}] carte {d.card_id} : {d.detail}")
        sys.exit(1)
    print(f"OK — {len(current)} cartes, 0 divergence vs snapshot.")


def cmd_rollback(args):
    baseline = _snapshot_from_dict(json.loads(Path(args.snapshot).read_text()))
    if not args.yes:
        if input("Restaurer tous les noms du snapshot ? [tape 'oui'] "
                 ).strip() != "oui":
            sys.exit("Annulé.")
    mb = connect()
    current = capture_snapshot(mb.get, root_id=ROOT_COLLECTION_ID)
    restored = 0
    for cid, base in baseline.items():
        cur = current.get(cid)
        if cur and cur.name != base.name:
            _check(mb.put(f"/api/card/{cid}", json={"name": base.name}),
                   f"restauration carte {cid}")
            print(f"  carte {cid} -> nom d'origine {base.name!r}")
            restored += 1
    print(f"Rollback terminé. {restored} carte(s) restaurée(s).")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Normalisation des noms — Phase 1.5")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="Capturer l'état des cartes du sous-arbre 215")

    p_prop = sub.add_parser("propose", help="Générer rename-proposal.csv")
    p_prop.add_argument("--snapshot", required=True)
    p_prop.add_argument("--out", default=str(MIGRATION_DIR / "rename-proposal.csv"))

    p_apply = sub.add_parser("apply", help="Appliquer le CSV de renommage")
    p_apply.add_argument("--snapshot", required=True)
    p_apply.add_argument("--proposal", default=str(MIGRATION_DIR / "rename-proposal.csv"))
    p_apply.add_argument("--yes", action="store_true")

    p_verify = sub.add_parser("verify", help="Comparer l'état live au snapshot")
    p_verify.add_argument("--snapshot", required=True)

    p_rb = sub.add_parser("rollback", help="Restaurer les noms d'origine")
    p_rb.add_argument("--snapshot", required=True)
    p_rb.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    {"snapshot": cmd_snapshot, "propose": cmd_propose, "apply": cmd_apply,
     "verify": cmd_verify, "rollback": cmd_rollback}[args.command](args)


if __name__ == "__main__":
    main()
