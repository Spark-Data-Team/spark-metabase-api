#!/usr/bin/env python
"""Détecte statiquement les UNION dont les branches n'ont pas le même nombre de colonnes.

Motivation : la migration des conversions a régénéré des cartes en remplaçant les
colonnes positionnelles (conversions_1..6) par des colonnes nommées. Quand une
branche du UNION final liste ses colonnes explicitement et l'autre fait SELECT *,
la substitution peut désaligner les deux, et Snowflake refuse la requête avec
« invalid number of result columns for set operator input branches ».

Le contrôle est purement statique : aucune requête n'est exécutée, donc aucun
crédit Snowflake consommé.

Usage :
    python scripts/check_union_arity.py --collections 14115 13984 ...
    python scripts/check_union_arity.py --cards 51288 8614
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spark_metabase_api import Metabase_API


def load_env():
    env = {}
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v
    return env


def card_sql(card):
    query = card.get("dataset_query") or {}
    stages = query.get("stages")
    stage = stages[-1] if stages else query.get("native", {})
    return stage.get("native") or stage.get("query") or ""


def strip_comments(sql):
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"/\*.*?\*/", "", sql, flags=re.S)


def matching_paren(sql, start):
    """start = index juste après la parenthèse ouvrante ; renvoie l'index de la fermante."""
    depth = 1
    i = start
    while i < len(sql) and depth > 0:
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
        i += 1
    return i - 1


def parse_ctes(sql):
    """({nom: corps}, requête_finale) en parcourant la clause WITH de gauche à droite."""
    ctes = {}
    m = re.search(r"\bWITH\b", sql, re.I)
    if not m:
        return ctes, sql
    pos = m.end()
    while True:
        head = re.match(r"\s*,?\s*([a-zA-Z_][\w]*)\s+AS\s*\(", sql[pos:], re.I)
        if not head:
            break
        start = pos + head.end()
        end = matching_paren(sql, start)
        ctes[head.group(1).lower()] = sql[start:end]
        pos = end + 1
        if not re.match(r"\s*,", sql[pos:]):
            break
    return ctes, sql[pos:]


def top_level_split(body, pattern):
    """Découpe body sur les occurrences de pattern situées à profondeur 0."""
    parts = []
    last = 0
    for m in re.finditer(pattern, body, re.I):
        head = body[: m.start()]
        if head.count("(") == head.count(")"):
            parts.append(body[last : m.start()])
            last = m.end()
    parts.append(body[last:])
    return parts


def select_list(branch):
    """Renvoie (liste_texte, clause_from) pour une branche."""
    m = re.search(r"\bSELECT\b(\s+DISTINCT\b)?", branch, re.I)
    if not m:
        return None, None
    rest = branch[m.end() :]
    depth = 0
    end = len(rest)
    for mm in re.finditer(r"\(|\)|\bFROM\b", rest, re.I):
        tok = mm.group(0)
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth -= 1
        elif depth == 0:
            end = mm.start()
            break
    return rest[:end], rest[end:]


def split_items(sel):
    """Découpe une liste de SELECT sur les virgules de niveau 0."""
    items = []
    cur = ""
    depth = 0
    for ch in sel:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += ch
    items.append(cur)
    return [it.strip() for it in items]


def count_cols(sel):
    return len(split_items(sel))


def arity(branch, ctes, seen=None):
    """Colonnes d'une branche ; résout les `*` contre le CTE source. None = indécidable."""
    seen = seen or set()
    sel, from_clause = select_list(branch)
    if sel is None:
        return None
    items = split_items(sel)
    stars = [it for it in items if it == "*" or re.fullmatch(r"[\w]+\.\*", it or "")]
    if not stars:
        return len(items)
    # une jointure rend l'expansion de `*` indécidable
    if from_clause and re.search(r"\bJOIN\b", from_clause, re.I):
        return None
    if len(stars) > 1:
        return None
    src = re.match(r"\s*FROM\s+([a-zA-Z_][\w]*)", from_clause or "", re.I)
    name = src.group(1).lower() if src else None
    if not name or name not in ctes or name in seen:
        return None
    sub = ctes[name]
    vals = [arity(b, ctes, seen | {name}) for b in top_level_split(sub, r"\bUNION(?:\s+ALL)?\b")]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return len(items) - 1 + vals[0]


def check(sql):
    """Renvoie la liste des UNION déséquilibrés : [(portée, [arités])]."""
    sql = strip_comments(sql)
    ctes, tail = parse_ctes(sql)
    scopes = dict(ctes)
    scopes["<final>"] = tail
    bad = []
    for name, body in scopes.items():
        branches = top_level_split(body, r"\bUNION(?:\s+ALL)?\b")
        if len(branches) < 2:
            continue
        vals = [arity(b, ctes) for b in branches]
        known = [v for v in vals if v is not None]
        if len(known) >= 2 and len(set(known)) > 1:
            bad.append((name, vals))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collections", nargs="*", type=int, default=[])
    ap.add_argument("--cards", nargs="*", type=int, default=[])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    env = load_env()
    mb = Metabase_API(env["METABASE_DOMAIN"], env.get("METABASE_EMAIL"), env.get("METABASE_PASSWORD"))

    card_ids = list(args.cards)
    for cid in args.collections:
        page = mb.get(f"/api/collection/{cid}/items?models=card&limit=2000")
        for it in page.get("data", []):
            if not it.get("archived"):
                card_ids.append(it["id"])
    card_ids = sorted(set(card_ids))
    print(f"{len(card_ids)} cartes à contrôler", flush=True)

    findings, skipped = [], 0
    for i, cid in enumerate(card_ids, 1):
        try:
            card = mb.get(f"/api/card/{cid}")
        except Exception as exc:  # carte supprimée entre-temps
            skipped += 1
            print(f"  ! {cid} illisible : {exc}", flush=True)
            continue
        sql = card_sql(card)
        if not sql:
            continue
        bad = check(sql)
        if bad:
            findings.append(
                {
                    "card_id": cid,
                    "name": card.get("name"),
                    "collection_id": card.get("collection_id"),
                    "scopes": [{"scope": s, "arities": a} for s, a in bad],
                }
            )
            print(f"  ✗ {cid} {card.get('name')[:55]} → {bad}", flush=True)
        if i % 100 == 0:
            print(f"  … {i}/{len(card_ids)} ({len(findings)} trouvées)", flush=True)

    print(f"\n{len(findings)} cartes déséquilibrées sur {len(card_ids)} contrôlées ({skipped} illisibles)")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(findings, fh, ensure_ascii=False, indent=1)
        print(f"→ {args.out}")


if __name__ == "__main__":
    main()
