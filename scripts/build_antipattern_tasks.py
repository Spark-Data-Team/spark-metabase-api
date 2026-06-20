#!/usr/bin/env python3
"""Explose les candidats anti-patterns en fichiers .sql par tâche + index.json.

Chaque agent du workflow lit UN fichier .sql (petit) et rend un verdict.
Index = métadonnées légères (sans SQL) passées en `args` au workflow.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = REPO_ROOT / "migration" / "antipattern-tasks"


def fmt_dashboards(dl):
    if not dl:
        return "AUCUN dashboard"
    return ", ".join(f'{d["name"]}(#{d["id"]})' for d in dl)


def main():
    cand_path = sorted(glob.glob(str(REPO_ROOT / "migration" / "sql-antipattern-candidates-*.json")))[-1]
    blob = json.load(open(cand_path))
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    # clean stale task files
    for f in TASK_DIR.glob("*.sql"):
        f.unlink()

    index = []
    for c in blob["a_candidates"]:
        path = TASK_DIR / f'A-{c["id"]}.sql'
        header = (
            f'-- ANTI-PATTERN A (JOIN kp__* sans language/zone)\n'
            f'-- CARD #{c["id"]}: {c["name"]}\n'
            f'-- Collection: {c.get("collection_name")} (id {c.get("collection_id")})\n'
            f'-- Dashboards: {fmt_dashboards(c.get("dashboards"))}\n'
            f'-- Flags: has_join={c["has_join"]} mentions_airtable_record_id={c["mentions_airtable_record_id"]} '
            f'kp_tables={",".join(c["kp_tables"])}\n'
            f'-- view_count={c.get("view_count")} updated_at={c.get("updated_at")}\n'
            f'-- ============================== SQL ==============================\n'
        )
        path.write_text(header + c["sql"])
        index.append({"task_id": f'A-{c["id"]}', "antipattern": "A", "card_id": c["id"],
                      "name": c["name"], "path": str(path),
                      "has_join": c["has_join"],
                      "mentions_airtable_record_id": c["mentions_airtable_record_id"],
                      "kp_tables": c["kp_tables"],
                      "dashboards": [d["id"] for d in (c.get("dashboards") or [])]})

    for c in blob["b_candidates"]:
        path = TASK_DIR / f'B-{c["id"]}.sql'
        header = (
            f'-- ANTI-PATTERN B (\\. et meta-chars echappes d un seul backslash dans REGEXP Snowflake)\n'
            f'-- CARD #{c["id"]}: {c["name"]}\n'
            f'-- Collection: {c.get("collection_name")} (id {c.get("collection_id")})\n'
            f'-- Dashboards: {fmt_dashboards(c.get("dashboards"))}\n'
            f'-- Flags: regex_funcs={",".join(c["regex_funcs"])} escaped_metachars={" ".join(c["escaped_metachars"])}\n'
            f'-- view_count={c.get("view_count")} updated_at={c.get("updated_at")}\n'
            f'-- ============================== SQL ==============================\n'
        )
        path.write_text(header + c["sql"])
        index.append({"task_id": f'B-{c["id"]}', "antipattern": "B", "card_id": c["id"],
                      "name": c["name"], "path": str(path),
                      "regex_funcs": c["regex_funcs"],
                      "escaped_metachars": c["escaped_metachars"],
                      "dashboards": [d["id"] for d in (c.get("dashboards") or [])]})

    idx_path = TASK_DIR / "index.json"
    idx_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))
    print(f"{len(index)} tâches écrites dans {TASK_DIR}")
    print(f"  A: {sum(1 for t in index if t['antipattern']=='A')}  "
          f"B: {sum(1 for t in index if t['antipattern']=='B')}")
    print(f"Index: {idx_path}")


if __name__ == "__main__":
    main()
