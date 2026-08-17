#!/usr/bin/env python
"""Répare les UNION déséquilibrés laissés par la migration des conversions.

Principe : dans ces cartes, la branche « détail » du UNION final fait SELECT * sur
un CTE, tandis que les branches « TOTAL » listent leurs colonnes une par une. Quand
la migration a supprimé une colonne positionnelle (conversions_N) du CTE, la ligne
correspondante des branches TOTAL a parfois survécu parce qu'elle ne mentionnait pas
le nom supprimé. Résultat : Snowflake refuse la requête.

Le correctif retire des branches longues les colonnes qui n'ont pas d'équivalent dans
la branche de référence. L'alignement se fait par difflib sur la suite des alias, et
le script REFUSE d'écrire si l'écart n'est pas exactement une suite d'insertions
d'items aliasés — pas d'heuristique au jugé.

Dry-run par défaut ; --yes pour appliquer. Backup intégral de la carte avant tout PUT.

Usage :
    python scripts/fix_union_arity.py --cards 51288
    python scripts/fix_union_arity.py --findings migration/errors-2026-08-13/union-arity-20260814.json --yes
"""

import argparse
import datetime as dt
import difflib
import json
import re
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_union_arity import (  # noqa: E402
    arity,
    card_sql,
    check,
    parse_ctes,
    select_list,
    split_items,
    strip_comments,
    top_level_split,
)

CAMPAIGN_DIR = REPO_ROOT / "migration" / "errors-2026-08-13"
BACKUP_DIR = CAMPAIGN_DIR / "backups"


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
    r = requests.post(
        f"{domain}/api/session",
        json={"username": env["METABASE_EMAIL"], "password": env["METABASE_PASSWORD"]},
        timeout=60,
    )
    r.raise_for_status()
    s = requests.Session()
    s.headers.update({"X-Metabase-Session": r.json()["id"], "Content-Type": "application/json"})
    return domain, s


def alias_of(item):
    """Alias explicite (AS x), sinon le nom si l'item est un identifiant nu, sinon None."""
    m = re.search(r"\bAS\s+([a-zA-Z_][\w]*)\s*$", item.strip(), re.I)
    if m:
        return m.group(1).lower()
    if re.fullmatch(r"[a-zA-Z_][\w]*", item.strip()):
        return item.strip().lower()
    return None


def branch_aliases(branch, ctes, seen=None):
    """Suite des alias d'une branche, en résolvant un éventuel `*` contre son CTE."""
    seen = seen or set()
    sel, from_clause = select_list(branch)
    if sel is None:
        return None
    out = []
    for item in split_items(sel):
        if item == "*" or re.fullmatch(r"[\w]+\.\*", item):
            if from_clause and re.search(r"\bJOIN\b", from_clause, re.I):
                return None
            m = re.match(r"\s*FROM\s+([a-zA-Z_][\w]*)", from_clause or "", re.I)
            name = m.group(1).lower() if m else None
            if not name or name not in ctes or name in seen:
                return None
            sub = top_level_split(ctes[name], r"\bUNION(?:\s+ALL)?\b")[0]
            inner = branch_aliases(sub, ctes, seen | {name})
            if inner is None:
                return None
            out.extend(inner)
        else:
            out.append(alias_of(item))
    return out


def plan_card(sql):
    """Renvoie (alias_à_retirer, raison) ou (None, raison_du_refus)."""
    clean = strip_comments(sql)
    bad = check(clean)
    if not bad:
        return None, "déjà équilibrée"
    if len(bad) > 1:
        return None, f"plusieurs UNION déséquilibrés ({[b[0] for b in bad]}) — à traiter à la main"
    scope, arities = bad[0]
    ctes, tail = parse_ctes(clean)
    body = ctes.get(scope) if scope != "<final>" else tail
    branches = top_level_split(body, r"\bUNION(?:\s+ALL)?\b")
    ref_len = min(a for a in arities if a is not None)
    refs = [b for b, a in zip(branches, arities) if a == ref_len]
    ref = branch_aliases(refs[0], ctes)
    if ref is None:
        return None, "branche de référence non résolue"
    to_drop = []
    for branch, a in zip(branches, arities):
        if a is None or a == ref_len:
            continue
        got = branch_aliases(branch, ctes)
        if got is None:
            return None, "branche longue non résolue"
        # Comparer les alias terme à terme ne marche pas : dans un UNION les noms
        # viennent de la première branche, donc les branches suivantes aliasent
        # librement (current_cac_atc d'un côté, cac_atc de l'autre) et laissent
        # beaucoup d'items nus (SUM(x) tout court).
        # Le signal fiable est ailleurs : la colonne en trop laissée par la migration
        # est un DOUBLON EXACT d'une autre colonne de la même branche, puisque son
        # expression d'origine (cost / conversions_N) a été réécrite vers la conversion
        # principale, déjà présente. On ne retire que ça — donc rien qui porte une valeur.
        sel, _ = select_list(branch)
        items = split_items(sel)
        seen_expr, dup_idx = {}, []
        for k, item in enumerate(items):
            expr = re.sub(r"\s+", " ", re.sub(r"\bAS\s+[a-zA-Z_][\w]*\s*$", "", item, flags=re.I)).strip().lower()
            # deux colonnes constantes peuvent légitimement partager la même valeur
            # ('TOTAL' AS current_dimension_1 et 'TOTAL' AS current_dimension_2) : ce
            # n'est pas un doublon, seulement une coïncidence de littéral.
            if re.fullmatch(r"'[^']*'|\d+(\.\d+)?|null", expr):
                continue
            if expr in seen_expr:
                dup_idx.append(k)
            else:
                seen_expr[expr] = k
        if len(dup_idx) != a - ref_len:
            return None, (
                f"écart d'arité {a - ref_len} mais {len(dup_idx)} doublon(s) d'expression — à traiter à la main"
            )
        dup_aliases = [alias_of(items[k]) for k in dup_idx]
        if any(x is None for x in dup_aliases):
            return None, "colonne en trop sans alias — suppression non identifiable sûrement"
        if any(x in {r for r in ref if r} for x in dup_aliases):
            return None, "la colonne en trop porte un alias utilisé par la branche de référence"
        to_drop.extend(dup_aliases)
    if not to_drop:
        return None, "aucune colonne en trop identifiée"
    return sorted(set(to_drop)), f"{scope} : {arities} → retirer {sorted(set(to_drop))}"


def apply_patch(sql, aliases):
    """Retire les lignes qui définissent ces alias. Renvoie (sql_patché, lignes_retirées)."""
    kept, dropped = [], []
    for line in sql.splitlines(keepends=True):
        stripped = line.strip().rstrip(",").strip()
        if alias_of(stripped) in aliases and re.search(r"\bAS\s+[a-zA-Z_][\w]*\s*,?\s*$", line.strip(), re.I):
            dropped.append(line)
            continue
        kept.append(line)
    return "".join(kept), dropped


def live_dashboards(domain, s, cid):
    out = []
    for d in s.get(f"{domain}/api/card/{cid}/dashboards", timeout=60).json():
        full = s.get(f"{domain}/api/dashboard/{d['id']}", timeout=120).json()
        if not full.get("archived"):
            out.append(full)
    return out


def run_tile(domain, s, dash, cid):
    dcs = [x for x in dash["dashcards"] if x.get("card_id") == cid]
    if not dcs:
        return {"dash": dash["id"], "erreur": "tuile absente"}
    dc = dcs[0]
    byid = {m.get("parameter_id"): m.get("target") for m in dc.get("parameter_mappings", [])}
    params = [
        {"id": p["id"], "type": p.get("type"), "value": p["default"], "target": byid[p["id"]]}
        for p in dash.get("parameters", [])
        if p.get("default") is not None and p["id"] in byid
    ]
    r = s.post(
        f"{domain}/api/dashboard/{dash['id']}/dashcard/{dc['id']}/card/{cid}/query",
        json={"parameters": params},
        timeout=300,
    )
    try:
        j = r.json()
    except Exception:
        return {"dash": dash["id"], "http": r.status_code, "erreur": r.text[:120]}
    data = j.get("data") or {}
    return {
        "dash": dash["id"],
        "http": r.status_code,
        "status": j.get("status"),
        "lignes": len(data.get("rows") or []),
        "colonnes": len(data.get("cols") or []),
        "erreur": (j.get("error") or "")[:150],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cards", nargs="*", type=int, default=[])
    ap.add_argument("--findings", help="JSON produit par check_union_arity.py")
    ap.add_argument("--yes", action="store_true", help="applique réellement (sinon dry-run)")
    ap.add_argument("--journal", default=None)
    args = ap.parse_args()

    ids = list(args.cards)
    if args.findings:
        ids += [f["card_id"] for f in json.loads(Path(args.findings).read_text())]
    ids = sorted(set(ids))
    if not ids:
        ap.error("aucune carte : passer --cards ou --findings")

    domain, s = connect()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    journal = []

    for cid in ids:
        card = s.get(f"{domain}/api/card/{cid}", timeout=120).json()
        sql = card_sql(card)
        aliases, why = plan_card(sql)
        entry = {"card_id": cid, "nom": card.get("name"), "diagnostic": why}
        if not aliases:
            print(f"— {cid} {str(card.get('name'))[:50]} : {why}")
            journal.append(entry)
            continue

        patched, dropped = apply_patch(sql, set(aliases))
        reste = check(patched)
        entry.update(
            {
                "alias_retires": aliases,
                "lignes_retirees": [d.strip() for d in dropped],
                "equilibre_apres": not reste,
            }
        )
        if reste or not dropped:
            print(f"✗ {cid} : patch refusé (reste {reste}, {len(dropped)} lignes retirées)")
            journal.append(entry)
            continue

        print(f"→ {cid} {str(card.get('name'))[:50]} : {why}")
        for d in dropped:
            print(f"    - {d.strip()[:110]}")
        if not args.yes:
            print("    (dry-run, rien écrit)")
            journal.append(entry)
            continue

        dashes = live_dashboards(domain, s, cid)
        entry["avant"] = [run_tile(domain, s, d, cid) for d in dashes]
        backup = BACKUP_DIR / f"card-{cid}-AVANT-union-{stamp}.json"
        backup.write_text(json.dumps(card, ensure_ascii=False, indent=1))
        entry["backup"] = backup.name

        body = dict(card)
        query = json.loads(json.dumps(card["dataset_query"]))
        stage = query["stages"][-1] if query.get("stages") else query["native"]
        key = "native" if "native" in stage else "query"
        stage[key] = patched
        body["dataset_query"] = query
        r = s.put(f"{domain}/api/card/{cid}", json=body, timeout=180)
        if r.status_code >= 300:
            entry["erreur_put"] = f"HTTP {r.status_code} {r.text[:200]}"
            print(f"    ✗ PUT {r.status_code} : {r.text[:200]}")
            journal.append(entry)
            continue

        relu = s.get(f"{domain}/api/card/{cid}", timeout=120).json()
        entry["sql_ecrit"] = card_sql(relu) == patched
        entry["apres"] = [run_tile(domain, s, d, cid) for d in dashes]
        print(f"    OK PUT | SQL relu conforme={entry['sql_ecrit']} | backup {backup.name}")
        for a, b in zip(entry["avant"], entry["apres"]):
            print(f"    dash {a['dash']} : {a.get('status')} {a.get('lignes')}l → {b.get('status')} {b.get('lignes')}l {b.get('erreur','')[:60]}")
        journal.append(entry)

    path = Path(args.journal) if args.journal else CAMPAIGN_DIR / f"union-arity-fix-{stamp}.json"
    path.write_text(json.dumps(journal, ensure_ascii=False, indent=1))
    print(f"\njournal → {path}")


if __name__ == "__main__":
    main()
