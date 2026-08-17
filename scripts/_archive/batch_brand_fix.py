#!/usr/bin/env python3
"""Batch: applique la règle brand canonique (type LIKE + category=='brand' strict)
à toutes les cartes 11673 portant une clause d'exclusion brand.

Sécurité en couches :
1. GATE STATIQUE (gratuit, 100% des cartes) : strip_brand_atoms(old)==strip_brand_atoms(new)
   -> prouve que SEULE la clause brand change. Toute carte « dirty » est SAUTÉE.
2. SNAPSHOT JSONL de chaque carte avant PUT (restaurable).
3. RE-GET de chaque carte modifiée : le SQL persisté == SQL corrigé.
4. ÉCHANTILLON stratifié exécuté avant/après :
   - brand='yes' (défaut, clause inerte) : valeurs AVANT == APRÈS (gate dur) ;
   - brand='no' : les 2 runs s'exécutent (SQL valide) ; on rapporte l'ampleur du changement.

Usage :
  .venv/bin/python scripts/batch_brand_fix.py            # dry-run (scan + gate + plan)
  .venv/bin/python scripts/batch_brand_fix.py --yes      # applique
"""
import argparse, json, random, sys, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from archive_collections import connect_resilient
import conv_lib

WINDOW = "2026-05-01~2026-05-31"
BIG_TABLES = set(range(41335, 41355))  # tableaux génériques/custom (prod) = prioritaires à échantillonner
_lock = threading.Lock()


def _sql_of(card):
    dq = card["dataset_query"]
    st = dq["stages"][0] if "stages" in dq else dq["native"]
    return st, ("native" if "stages" in dq else "query")


def run_cells(mb, card, brand):
    """Cellules numériques au format card_values, params: date épinglée + brand_included=brand."""
    _, tags = conv_lib.native_and_tags(card)
    params = []
    if "date" in tags:
        params.append({"type": "date/all-options", "value": WINDOW, "target": ["dimension", ["template-tag", "date"]]})
    if "brand_included" in tags:
        params.append({"type": "category", "value": [brand], "target": ["dimension", ["template-tag", "brand_included"]]})
    r = mb.post(f"/api/card/{card['id']}/query", json={"parameters": params}, timeout=300)
    if not isinstance(r, dict) or r.get("status") != "completed":
        return None
    cols = [str(x.get("name")) for x in r["data"]["cols"]]
    return conv_lib.displayed_cells(cols, r["data"]["rows"], None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--sample", type=int, default=24)
    args = ap.parse_args()
    mb = connect_resilient()
    ids = json.loads(Path("/tmp/brand_batch_ids.json").read_text())
    print(f"cibles: {len(ids)} cartes")

    # --- Phase 1 : scan + gate statique (parallèle, lecture seule) ---
    def scan(cid):
        try:
            card = mb.get(f"/api/card/{cid}")
            if card.get("archived"):
                return {"id": cid, "klass": "archived"}
            st, key = _sql_of(card)
            sql = st[key]
            fixed = conv_lib.fix_brand_clause(sql)
            if fixed == sql:
                return {"id": cid, "klass": "noop"}
            if conv_lib.strip_brand_atoms(sql) != conv_lib.strip_brand_atoms(fixed):
                return {"id": cid, "klass": "dirty", "name": card.get("name")}
            return {"id": cid, "klass": "clean", "card": card, "fixed": fixed,
                    "collection": card.get("collection_id"), "display": card.get("display")}
        except Exception as e:
            return {"id": cid, "klass": "error", "err": str(e)[:120]}

    with ThreadPoolExecutor(8) as ex:
        scanned = list(ex.map(scan, ids))
    by = {}
    for s in scanned:
        by.setdefault(s["klass"], []).append(s)
    clean = by.get("clean", [])
    print(f"scan: clean={len(clean)} noop={len(by.get('noop',[]))} dirty={len(by.get('dirty',[]))} "
          f"archived={len(by.get('archived',[]))} error={len(by.get('error',[]))}")
    for d in by.get("dirty", []):
        print(f"  DIRTY (sauté): {d['id']} {str(d.get('name'))[:60]}")
    for e in by.get("error", []):
        print(f"  ERROR: {e['id']} {e['err']}")
    if not clean:
        print("rien à appliquer."); return

    # --- échantillon stratifié : tous les gros tableaux présents + tirage aléatoire ---
    rnd = random.Random(12)
    big = [c for c in clean if c["id"] in BIG_TABLES]
    rest = [c for c in clean if c["id"] not in BIG_TABLES]
    sample = big[:8] + rnd.sample(rest, min(args.sample, len(rest)))
    sample_ids = {c["id"] for c in sample}
    print(f"échantillon vérifié en exécution: {len(sample)} cartes (dont {len(big[:8])} gros tableaux)")

    if not args.yes:
        print("(DRY-RUN — scan + gate OK, rien modifié. Relancer avec --yes.)")
        return

    # --- before sur l'échantillon (avant tout PUT) ---
    def before(c):
        return c["id"], {"yes": run_cells(mb, c["card"], "yes"), "no": run_cells(mb, c["card"], "no")}
    with ThreadPoolExecutor(8) as ex:
        bef = dict(ex.map(before, sample))

    # --- Phase 2 : PUT (parallèle) + snapshot JSONL ---
    snap_path = REPO / "migration" / "snapshots" / "brand-batch-snapshots.jsonl"
    snap = open(snap_path, "a")

    def apply(c):
        try:
            card = c["card"]
            st, key = _sql_of(card)
            with _lock:
                snap.write(json.dumps(card) + "\n"); snap.flush()
            st[key] = c["fixed"]
            resp = mb.put(f"/api/card/{c['id']}", "raw", json={"dataset_query": card["dataset_query"]})
            return c["id"], (resp.status_code == 200), getattr(resp, "status_code", None)
        except Exception as e:
            return c["id"], False, str(e)[:120]

    with ThreadPoolExecutor(8) as ex:
        puts = list(ex.map(apply, clean))
    snap.close()
    ok = [p for p in puts if p[1]]
    fail = [p for p in puts if not p[1]]
    print(f"PUT: ok={len(ok)} fail={len(fail)}")
    for f in fail[:10]:
        print(f"  PUT FAIL {f[0]}: {f[2]}")

    # --- Phase 3 : re-GET de contrôle (le SQL corrigé a-t-il persisté ?) ---
    fixed_by_id = {c["id"]: c["fixed"] for c in clean}
    ok_ids = {p[0] for p in ok}

    def confirm(cid):
        card = mb.get(f"/api/card/{cid}")
        st, key = _sql_of(card)
        return cid, (st[key] == fixed_by_id[cid])
    with ThreadPoolExecutor(8) as ex:
        confs = list(ex.map(confirm, ok_ids))
    not_persisted = [c[0] for c in confs if not c[1]]
    print(f"persistance SQL: {len(confs)-len(not_persisted)}/{len(confs)} OK"
          + (f" — NON persistées: {not_persisted[:8]}" if not_persisted else ""))

    # --- Phase 4 : after sur l'échantillon + comparaison ---
    def after(c):
        card = mb.get(f"/api/card/{c['id']}")
        return c["id"], {"yes": run_cells(mb, card, "yes"), "no": run_cells(mb, card, "no")}
    with ThreadPoolExecutor(8) as ex:
        aft = dict(ex.map(after, sample))

    default_changed, no_broken, no_changed, no_same = [], [], 0, 0
    for cid in sample_ids:
        b, a = bef[cid], aft[cid]
        if b["yes"] is None or a["yes"] is None or a["yes"] != b["yes"]:
            default_changed.append(cid)
        if a["no"] is None:
            no_broken.append(cid)
        elif b["no"] != a["no"]:
            no_changed += 1
        else:
            no_same += 1
    print("\n=== ÉCHANTILLON ===")
    print(f"  défaut (brand=yes) AVANT==APRÈS : {len(sample_ids)-len(default_changed)}/{len(sample_ids)}"
          + (f"  ⛔ CHANGÉ: {default_changed}" if default_changed else "  ✅"))
    print(f"  brand=no s'exécute : {len(sample_ids)-len(no_broken)}/{len(sample_ids)}"
          + (f"  ⛔ CASSÉ: {no_broken}" if no_broken else "  ✅"))
    print(f"  brand=no comportement: {no_changed} cartes changent (correctif visible), {no_same} inchangées")
    verdict = not default_changed and not no_broken and not not_persisted and not fail
    print(f"\n=> {'✅ BATCH SAIN' if verdict else '⚠️ ANOMALIES — inspecter ci-dessus'} "
          f"({len(ok)} cartes corrigées, snapshots: {snap_path.name})")


if __name__ == "__main__":
    main()
