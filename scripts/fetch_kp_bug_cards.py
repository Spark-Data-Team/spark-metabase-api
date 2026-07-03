#!/usr/bin/env python3
"""Étape read-only du fix anti-pattern A : récupère le SQL LIVE des 8 cartes BUG,
le compare au snapshot d'audit, et montre les lignes de JOIN kp__* + les colonnes
exposées par l'alias amont. N'écrit RIEN (ni API, ni fichiers hors /tmp session).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from archive_collections import connect_resilient  # noqa: E402

OUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/kp-bug-cards-live")

A_BUG_IDS = [28512, 28551, 28549, 28550, 28206, 16708, 34378, 28547]


def main():
    mb = connect_resilient()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    audit = {r["card_id"]: r for r in json.load(open(REPO / "migration" / "antipattern-audit-results.json"))["results"]}

    for cid in A_BUG_IDS:
        card = mb.get(f"/api/card/{cid}")
        if not isinstance(card, dict):
            print(f"### {cid} : GET KO -> {card!r}")
            continue
        dq = card.get("dataset_query") or {}
        if "stages" in dq:  # format MBQL-lib (Metabase récent) : SQL dans stages[0].native
            sql = dq["stages"][0].get("native") or ""
        else:  # format legacy : dataset_query.native.query
            sql = (dq.get("native") or {}).get("query") or ""
        (OUT_DIR / f"{cid}.json").write_text(json.dumps(card, ensure_ascii=False, indent=1))
        (OUT_DIR / f"{cid}.sql").write_text(sql)

        snap_path = REPO / "migration" / "antipattern-tasks" / f"A-{cid}.sql"
        snap = snap_path.read_text().split("=" * 30 + "\n", 1)[-1] if snap_path.exists() else ""
        drift = "IDENTIQUE au snapshot audit" if sql.strip() == snap.strip() else "*** DRIFT vs snapshot audit ***"

        print(f"\n### {cid} — {card.get('name')} [{drift}] archived={card.get('archived')}")
        for i, line in enumerate(sql.splitlines(), 1):
            if re.search(r"kp__keyword_(aggregated|monthly)_metrics", line, re.I):
                print(f"  L{i}: {line.strip()[:180]}")


if __name__ == "__main__":
    main()
