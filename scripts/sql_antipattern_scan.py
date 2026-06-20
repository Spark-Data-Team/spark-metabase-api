#!/usr/bin/env python3
"""Inventaire + présélection pour l'audit de deux anti-patterns SQL (lecture seule).

Anti-pattern A — JOIN sur tables kp__* sans (language, zone) => produit cartésien.
Anti-pattern B — `\\.` (et autres méta-chars échappés d'un seul backslash) dans les
                 REGEXP Snowflake : l'échappement est mangé, le point devient « . »
                 (n'importe quel caractère).

Source SQL : payload frais de GET /api/card/ (format MBQL nouveau -> stages[].native,
puis fallback legacy_query). Aucune écriture (no PUT/POST/DELETE).

Sortie : migration/sql-antipattern-candidates-<ts>.json
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env  # noqa: E402

MIGRATION_DIR = REPO_ROOT / "migration"

# --- Tables ciblées (présélection) ------------------------------------------
KP_TABLES = ["kp__keyword_monthly_metrics", "kp__keyword_aggregated_metrics"]
SERP_TABLES = ["serp__keyword_metrics", "serp_requests", "serp_history", "serp_refresh_runs"]
PRESELECT_TABLES = KP_TABLES + SERP_TABLES

REGEX_FUNCS = ["REGEXP_REPLACE", "REGEXP_LIKE", "REGEXP_SUBSTR", "REGEXP_COUNT",
               "REGEXP_INSTR", "REGEXP", "RLIKE"]

# méta-chars qui, échappés d'un seul backslash, sont des candidats au bug B
_ESCAPED_META_RE = re.compile(r"\\[.?+(){}\[\]|^$*]")


def extract_sql(card) -> str | None:
    """SQL natif d'une carte, tolérant aux 3 formats rencontrés sur l'instance."""
    dq = card.get("dataset_query") or {}
    for st in (dq.get("stages") or []):           # format MBQL « stages »
        nat = st.get("native")
        if isinstance(nat, str) and nat.strip():
            return nat
    nat = dq.get("native") or {}                  # format natif classique
    if isinstance(nat.get("query"), str) and nat["query"].strip():
        return nat["query"]
    lq = card.get("legacy_query")                 # legacy_query (string JSON)
    if isinstance(lq, str):
        try:
            lq = json.loads(lq)
        except Exception:
            lq = None
    if isinstance(lq, dict):
        q = (lq.get("native") or {}).get("query")
        if isinstance(q, str) and q.strip():
            return q
    return None


def main():
    env = _load_env()
    mb = Metabase_API(domain=env["METABASE_DOMAIN"], email=env["METABASE_EMAIL"],
                      password=env["METABASE_PASSWORD"])
    cards = mb.get("/api/card/")
    if cards is False or cards is None:
        sys.exit("GET /api/card/ a échoué (auth/perm) — arrêt (garde-fou 401/403).")

    n_total = len(cards)
    natives = [c for c in cards if c.get("query_type") == "native" and not c.get("archived")]
    n_native = len(natives)

    no_sql = []           # natives dont on n'a pas pu extraire le SQL
    a_candidates = []
    b_candidates = []
    regex_no_escape = []  # regex présent mais aucun méta-char échappé suspect (probable OK)

    for c in natives:
        sql = extract_sql(c)
        if not sql:
            no_sql.append({"id": c["id"], "name": c.get("name")})
            continue
        sql_l = sql.lower()
        coll = c.get("collection") or {}
        base = {
            "id": c["id"],
            "name": c.get("name"),
            "collection_id": c.get("collection_id"),
            "collection_name": coll.get("name") if isinstance(coll, dict) else None,
            "collection_path": coll.get("effective_ancestors") if isinstance(coll, dict) else None,
            "view_count": c.get("view_count") or 0,
            "last_used_at": c.get("last_used_at"),
            "updated_at": c.get("updated_at"),
        }

        # ---- Anti-pattern A : tables kp__* ----
        kp_hits = [t for t in KP_TABLES if t.lower() in sql_l]
        if kp_hits:
            has_join = bool(re.search(r"\bjoin\b", sql_l))
            has_airtable = "airtable_record_id" in sql_l
            a_candidates.append({**base, "kp_tables": kp_hits, "has_join": has_join,
                                 "mentions_airtable_record_id": has_airtable, "sql": sql})

        # ---- Anti-pattern B : REGEXP + méta-char échappé ----
        funcs = [f for f in ("REGEXP_REPLACE", "REGEXP_LIKE", "REGEXP_SUBSTR",
                             "REGEXP_COUNT", "REGEXP_INSTR", "RLIKE") if f.lower() in sql_l]
        # 'REGEXP(' générique sans capter les noms ci-dessus déjà comptés
        if not funcs and re.search(r"\bregexp\s*\(", sql_l):
            funcs = ["REGEXP"]
        if funcs:
            escapes = sorted(set(_ESCAPED_META_RE.findall(sql)))
            if escapes:
                b_candidates.append({**base, "regex_funcs": funcs,
                                     "escaped_metachars": escapes, "sql": sql})
            else:
                regex_no_escape.append({"id": c["id"], "name": c.get("name"),
                                        "regex_funcs": funcs})

    # union présélectionnée (pour le compte « N présélectionnées »)
    preselect_ids = {x["id"] for x in a_candidates} | {x["id"] for x in b_candidates}

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = MIGRATION_DIR / f"sql-antipattern-candidates-{ts}.json"
    MIGRATION_DIR.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "meta": {
            "generated_at": ts,
            "n_total_cards": n_total,
            "n_native_active": n_native,
            "n_native_no_sql": len(no_sql),
            "n_preselected_union": len(preselect_ids),
            "n_a_candidates": len(a_candidates),
            "n_a_with_join": sum(1 for x in a_candidates if x["has_join"]),
            "n_b_candidates": len(b_candidates),
            "n_regex_present_no_suspicious_escape": len(regex_no_escape),
        },
        "a_candidates": a_candidates,
        "b_candidates": b_candidates,
        "regex_no_escape": regex_no_escape,
        "native_no_sql": no_sql,
    }, indent=2, ensure_ascii=False))

    m = json.loads(out.read_text())["meta"]
    print(json.dumps(m, indent=2, ensure_ascii=False))
    print("\nÉcrit :", out)


if __name__ == "__main__":
    main()
