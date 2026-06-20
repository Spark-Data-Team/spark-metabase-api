#!/usr/bin/env python3
"""Applique les correctifs anti-patterns aux cartes Metabase, avec preuve avant/après.

Procédure par carte (cf. [[feedback-metabase-card-changes]]) :
  1. GET + extrait le SQL actuel (legacy_query.native.query).
  2. Calcule le SQL corrigé (find/replace exacts issus de l'audit) — abort si le
     find n'est pas trouvé exactement.
  3. PREUVE LECTURE SEULE : exécute OLD et NEW via /api/dataset (mêmes substitutions
     de tags, scope client Tradis multi-zones) et diff. Gate : NEW compile ; pour A,
     lignes(NEW) <= lignes(OLD) (le fix ne peut que retirer le fan-out).
  4. --apply seulement : backup JSON, PUT (format natif classique, "raw"), puis
     re-GET + run live ; revert (PUT backup) si la carte casse.

Usage :
  python3 scripts/fix_antipatterns.py 28512                 # preuve seule (dry-run)
  python3 scripts/fix_antipatterns.py 28512 --apply         # applique + vérifie
  python3 scripts/fix_antipatterns.py --all-a --apply
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT))
import spark_metabase_api.main_methods as MM
MM.DEFAULT_TIMEOUT = 180
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env

DB = 144
HTTP_TIMEOUT = 240
TEST_CLIENT = "Tradis"            # client multi-zones (preuve d'inflation A)
BACKUP_DIR = ROOT / "migration" / "fix-backups"


def connect():
    e = _load_env()
    for a in range(6):
        try:
            mb = Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])
            mb.get("/api/user/current"); return mb
        except Exception as ex:
            print(f"  retry {a+1}: {type(ex).__name__}"); time.sleep(5)
    sys.exit("conn failed")


def get_card(mb, cid):
    """Retourne (carte, dataset_query, sql_natif_canonique, index_stage).

    La source de vérité est dataset_query.stages[i].native (format MBQL courant) ;
    legacy_query est un champ dérivé qui ne se régénère pas après un PUT.
    """
    d = mb.get(f"/api/card/{cid}")
    dq = d.get("dataset_query") or {}
    for i, st in enumerate(dq.get("stages") or []):
        if isinstance(st.get("native"), str):
            return d, dq, st["native"], i
    # repli format classique
    if isinstance(dq.get("native"), dict) and isinstance(dq["native"].get("query"), str):
        return d, dq, dq["native"]["query"], -1
    raise RuntimeError(f"#{cid}: SQL natif introuvable dans dataset_query")


def put_native(mb, cid, d, dq, stage_idx, sql):
    """PUT en réécrivant le SQL natif IN PLACE dans le dataset_query (format courant)."""
    import copy
    new_dq = copy.deepcopy(dq)
    if stage_idx >= 0:
        new_dq["stages"][stage_idx]["native"] = sql
    else:
        new_dq["native"]["query"] = sql
    payload = {
        "name": d.get("name"), "collection_id": d.get("collection_id"),
        "dataset_query": new_dq,
        "display": d.get("display"), "visualization_settings": d.get("visualization_settings"),
        "parameters": d.get("parameters"), "description": d.get("description"),
    }
    r = mb.put(f"/api/card/{cid}", "raw", json=payload, timeout=180)
    return getattr(r, "status_code", "?")


def run_dataset(mb, sql):
    r = mb.post("/api/dataset", "raw", json={"database": DB, "type": "native", "native": {"query": sql}}, timeout=HTTP_TIMEOUT)
    j = r.json() if hasattr(r, "json") else r
    if isinstance(j, dict) and j.get("error"):
        return None, None, str(j.get("error"))[:400]
    dd = j.get("data", {})
    return [c.get("name") for c in dd.get("cols", [])], dd.get("rows", []), None


def subst(sql):
    """Substitutions de tags Metabase, IDENTIQUES pour OLD et NEW (scope Tradis).

    Le but est UNIQUEMENT de rendre les deux requêtes exécutables pour isoler
    l'effet du fix ; toutes les substitutions sont identiques OLD/NEW.
    """
    sql = re.sub(r"\[\[.*?\]\]", "", sql, flags=re.S)          # blocs optionnels
    client_col = "utils.clients.name" if "utils.clients" in sql else "serp_requests.client_name"
    sql = sql.replace("{{client}}", f"{client_col} = '{TEST_CLIENT}'")
    sql = sql.replace("{{date}}", "TRUE")
    sql = re.sub(r"\{\{\w+\}\}", "TRUE", sql)                   # ctr_scenario/time_period/corpus/... -> TRUE
    return sql


def numeric_sums(cols, rows):
    sums = {}
    for i, c in enumerate(cols):
        vals = [r[i] for r in rows if isinstance(r[i], (int, float))]
        if vals:
            sums[c] = round(sum(vals), 2)
    return sums


def apply_fixes(sql, fixes):
    new = sql
    applied = []
    for find, repl in fixes:
        n = new.count(find)
        if n == 0:
            return None, f"FIND introuvable: {find[:80]!r}"
        new = new.replace(find, repl)
        applied.append((find, repl, n))
    if new == sql:
        return None, "aucun changement après application"
    return new, applied


def process(mb, card, fixes, antipattern, apply=False):
    cid = card["card_id"]
    name = card["name"]
    print(f"\n{'='*70}\n#{cid} [{antipattern}] {name}")
    d, dq, old_sql, sidx = get_card(mb, cid)
    new_sql, info = apply_fixes(old_sql, fixes)
    if new_sql is None:
        # déjà corrigé ? (les replace présents, les find absents)
        if all(repl in old_sql for _, repl in fixes) and all(find not in old_sql for find, _ in fixes):
            print("  ✓ déjà corrigé (no-op)"); return {"id": cid, "status": "already_fixed"}
        print("  ✗ ABORT:", info); return {"id": cid, "status": "abort_find", "detail": info}
    for find, repl, n in info:
        print(f"  fix ×{n}: …{find[-55:]!r} -> …{repl[-55:]!r}")

    # ---- Stage 1 : preuve lecture seule (diff OLD vs NEW via /api/dataset) ----
    co, ro, eo = run_dataset(mb, subst(old_sql))
    cn, rn, en = run_dataset(mb, subst(new_sql))
    if en:
        print("  ✗ NEW NE COMPILE PAS:", en); return {"id": cid, "status": "new_compile_fail", "detail": en}
    n_old = len(ro) if ro is not None else None
    n_new = len(rn)
    print(f"  lignes  OLD={n_old}  NEW={n_new}" + ("  ⚠OLD-no-compile" if eo else ""))
    so, sn = (numeric_sums(co, ro) if ro else {}), numeric_sums(cn, rn)
    changed = [(k, so.get(k), sn.get(k)) for k in sn if so.get(k) != sn.get(k)]
    for k, a, b in changed[:8]:
        delta = f"{(b-a)/a*100:+.1f}%" if isinstance(a, (int, float)) and a else "—"
        print(f"    Σ {k}: {a} -> {b}  ({delta})")
    if antipattern == "A" and not eo and n_old is not None and n_new > n_old:
        print(f"  ✗ GATE A: NEW lignes ({n_new}) > OLD ({n_old}) — abort")
        return {"id": cid, "status": "gate_rows", "n_old": n_old, "n_new": n_new}
    print(f"  ✓ gate {antipattern} OK (NEW compile)")

    res = {"id": cid, "antipattern": antipattern, "n_old": n_old, "n_new": n_new,
           "changed_sums": changed, "status": "proven"}
    if not apply:
        print("  (dry-run : pas de PUT)"); return res

    # ---- Stage 2 : backup + PUT (réécriture in-place du dataset_query) ----
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    (BACKUP_DIR / f"card-{cid}-backup-{ts}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2))
    sc = put_native(mb, cid, d, dq, sidx, new_sql)
    print(f"  backup ok · PUT status: {sc}")

    # ---- Stage 3 : vérif persistance (champ canonique) + compile, SANS params ----
    _, _, srv_sql, _ = get_card(mb, cid)
    persisted = (srv_sql == new_sql)
    _, _, srv_err = run_dataset(mb, subst(srv_sql))
    if persisted and not srv_err:
        print(f"  ✓ APPLIQUÉ & vérifié (SQL serveur == corrigé, compile OK)")
        res["status"] = "applied_ok"
    else:
        why = "non persisté" if not persisted else f"ne compile pas: {srv_err}"
        print(f"  ✗ ÉCHEC post-PUT ({why}) — REVERT")
        rb = put_native(mb, cid, d, dq, sidx, old_sql)
        print(f"  revert PUT status: {rb}")
        res["status"] = "reverted"
    return res


def load_bugs():
    full = json.load(open(sorted(glob.glob(str(ROOT / "migration" / "antipattern-audit-full-*.json")))[-1]))
    return {r["card_id"]: r for r in full["results"] if r["corrected"] == "BUG"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", type=int)
    ap.add_argument("--all-a", action="store_true")
    ap.add_argument("--all-b", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    bugs = load_bugs()
    ids = list(args.ids)
    if args.all_a: ids += [c for c, r in bugs.items() if r["antipattern"] == "A"]
    if args.all_b: ids += [c for c, r in bugs.items() if r["antipattern"] == "B"]
    ids = sorted(set(ids))
    if not ids:
        sys.exit("aucun id (passe des ids, --all-a ou --all-b)")
    mb = connect(); print("connected.", "MODE:", "APPLY" if args.apply else "DRY-RUN (preuve seule)")
    out = []
    for cid in ids:
        if cid not in bugs:
            print(f"\n#{cid}: pas dans la liste BUG, skip"); continue
        r = bugs[cid]
        out.append(process(mb, r, r["fixes"], r["antipattern"], apply=args.apply))
    print(f"\n{'='*70}\nRÉSUMÉ")
    for o in out:
        print(f"  #{o['id']}: {o['status']}" + (f"  OLD={o.get('n_old')} NEW={o.get('n_new')}" if o.get('n_new') is not None else ""))


if __name__ == "__main__":
    main()
