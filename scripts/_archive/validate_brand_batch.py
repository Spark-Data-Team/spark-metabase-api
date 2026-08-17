#!/usr/bin/env python3
"""Validation exhaustive post-batch brand : exécute les 1967 cartes, et pour chaque
ÉCHEC rejoue le SQL d'AVANT (snapshot) pour trancher :
  - OLD échoue aussi  -> casse PRÉEXISTANTE (pas nous)
  - OLD réussit       -> RÉGRESSION introduite par le batch -> à restaurer

Lecture seule (aucune modif). Sortie : migration/brand-batch-validation.json.
"""
import json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from archive_collections import connect_resilient
import conv_lib

mb = connect_resilient()
ids = json.loads(Path("/tmp/brand_batch_ids.json").read_text())
SNAP = {}
for line in (REPO / "migration" / "snapshots" / "brand-batch-snapshots.jsonl").read_text().splitlines():
    c = json.loads(line)
    SNAP[c["id"]] = c  # dernière occurrence = état juste avant PUT


def _params(tags):
    p = []
    if "date" in tags:
        p.append({"type": "date/all-options", "value": "2026-05-01~2026-05-31",
                  "target": ["dimension", ["template-tag", "date"]]})
    return p


def run_live(cid, tags):
    r = mb.post(f"/api/card/{cid}/query", "raw", json={"parameters": _params(tags)})
    try:
        b = r.json()
    except Exception:
        b = {}
    return b.get("status") == "completed", str((b or {}).get("error") or "")[:140]


def run_snapshot(card, tags):
    """exécute le dataset_query d'AVANT via /api/dataset (sans toucher la carte)."""
    body = json.loads(json.dumps(card["dataset_query"]))
    body["parameters"] = _params(tags)
    r = mb.post("/api/dataset", "raw", json=body)
    try:
        b = r.json()
    except Exception:
        b = {}
    return b.get("status") == "completed"


def check(cid):
    card = mb.get(f"/api/card/{cid}")
    _, tags = conv_lib.native_and_tags(card)
    ok, err = run_live(cid, tags)
    if ok:
        return {"id": cid, "verdict": "ok"}
    snap = SNAP.get(cid)
    old_ok = run_snapshot(snap, tags) if snap else None
    return {"id": cid, "verdict": "REGRESSION" if old_ok else "preexisting_broken",
            "name": card.get("name"), "err": err, "old_ran": old_ok}


def main():
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(check, ids))
    ok = [r for r in res if r["verdict"] == "ok"]
    regr = [r for r in res if r["verdict"] == "REGRESSION"]
    pre = [r for r in res if r["verdict"] == "preexisting_broken"]
    (REPO / "migration" / "brand-batch-validation.json").write_text(json.dumps(res, ensure_ascii=False))
    print(f"OK: {len(ok)}/{len(res)} | RÉGRESSIONS: {len(regr)} | casse préexistante: {len(pre)}")
    if regr:
        print("\n⛔ RÉGRESSIONS (restaurer depuis snapshot) :")
        for r in regr:
            print(f"  {r['id']} {str(r['name'])[:55]} — {r['err']}")
    if pre:
        print(f"\nℹ️ cartes déjà cassées AVANT le batch (à signaler, pas nous) : {len(pre)}")
        for r in pre[:25]:
            print(f"  {r['id']} {str(r['name'])[:50]} — {r['err'][:70]}")
    print("\nrapport: migration/brand-batch-validation.json")


if __name__ == "__main__":
    main()
