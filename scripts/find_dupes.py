#!/usr/bin/env python3
"""Détecte les cartes fonctionnellement identiques dans la collection 215.

Pour chaque carte (hors Nouvelles Conversions), calcule une empreinte de sa
requête (`dataset_query`) normalisée :
- native : SQL minuscule, espaces compactés.
- MBQL   : JSON trié.
L'empreinte inclut la base de données. Regroupe ensuite :
- même requête + même display  -> vrais doublons fonctionnels (consolidables).
- même requête, displays ≠      -> même logique déclinée en plusieurs viz.

Lecture seule. Écrit un rapport JSON dans migration/.

Usage : python3 scripts/find_dupes.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env  # noqa: E402

ROOT_COLLECTION_ID = 215
EXCLUDE_COLLECTION_ID = 11673
MIGRATION_DIR = REPO_ROOT / "migration"


def connect_resilient() -> Metabase_API:
    env = _load_env()
    domain, email, password = (env.get("METABASE_DOMAIN"),
                               env.get("METABASE_EMAIL"),
                               env.get("METABASE_PASSWORD"))
    if not (domain and email and password):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env.")
    return Metabase_API(domain=domain, email=email, password=password)


def query_fingerprint(card: dict) -> str:
    """Empreinte normalisée de la requête, basée sur `legacy_query` (format classique).

    Les versions récentes de Metabase stockent `dataset_query` au nouveau format
    `lib/type`/`stages` (souvent vide via l'API) ; `legacy_query` (string JSON)
    contient la requête classique fiable.
    """
    lq = card.get("legacy_query")
    if isinstance(lq, str):
        try:
            lq = json.loads(lq)
        except Exception:
            lq = None
    if not isinstance(lq, dict) or not lq:
        # repli : sérialiser le dataset_query nouveau format
        dq = card.get("dataset_query", {}) or {}
        return "ds|" + hashlib.md5(
            json.dumps(dq, sort_keys=True).encode("utf-8")).hexdigest()
    db = lq.get("database")
    if lq.get("type") == "native":
        sql = (lq.get("native", {}) or {}).get("query", "") or ""
        norm = re.sub(r"\s+", " ", sql.strip().lower())
        payload = f"native|{db}|{norm}"
    else:
        payload = f"mbql|{db}|" + json.dumps(lq.get("query", {}), sort_keys=True)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def main():
    mb = connect_resilient()
    print(f"Scan complet de la collection {ROOT_COLLECTION_ID} (hors Conversions)...")
    cards = []

    def walk(cid):
        items = mb.get(f"/api/collection/{cid}/items?limit=2000").get("data", [])
        for it in items:
            if it["model"] == "collection":
                if it["id"] != EXCLUDE_COLLECTION_ID:
                    walk(it["id"])
            elif it["model"] in ("card", "dataset"):
                d = mb.get(f"/api/card/{it['id']}")
                if d.get("archived"):
                    continue
                cards.append({
                    "id": d["id"], "name": d["name"],
                    "collection_id": d.get("collection_id"),
                    "dashboard_count": d.get("dashboard_count", 0),
                    "display": d.get("display") or "",
                    "fp": query_fingerprint(d),
                })

    walk(ROOT_COLLECTION_ID)
    print(f"  {len(cards)} cartes actives scannées")

    # Groupe par (empreinte requête)
    by_query = defaultdict(list)
    for c in cards:
        by_query[c["fp"]].append(c)

    # Niveau 1 : même requête + même display
    pure_dups = []        # groupes [cartes] partageant fp ET display
    same_q_diff_disp = [] # groupes partageant fp mais displays variés
    for fp, group in by_query.items():
        if len(group) < 2:
            continue
        by_disp = defaultdict(list)
        for c in group:
            by_disp[c["display"]].append(c)
        for disp, sub in by_disp.items():
            if len(sub) >= 2:
                pure_dups.append(sub)
        if len(by_disp) >= 2:
            same_q_diff_disp.append(group)

    pure_dups.sort(key=len, reverse=True)
    same_q_diff_disp.sort(key=len, reverse=True)

    n_pure_cards = sum(len(g) for g in pure_dups)
    n_redundant = sum(len(g) - 1 for g in pure_dups)  # cartes "en trop"
    print(f"\n=== Vrais doublons fonctionnels (même requête + même viz) ===")
    print(f"  {len(pure_dups)} groupes, {n_pure_cards} cartes, "
          f"dont {n_redundant} redondantes (consolidables)")
    for g in pure_dups[:20]:
        total_dash = sum(c["dashboard_count"] for c in g)
        print(f"\n  Groupe de {len(g)} (total {total_dash} dashboards) :")
        for c in sorted(g, key=lambda x: -x["dashboard_count"]):
            print(f"    #{c['id']:>6}  dash={c['dashboard_count']:>4}  "
                  f"[{c['display']}]  {c['name']}")

    print(f"\n=== Même requête, viz différentes (logique déclinée) ===")
    print(f"  {len(same_q_diff_disp)} groupes")

    # Rapport JSON complet
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = MIGRATION_DIR / f"dupes-report-{ts}.json"
    report.write_text(json.dumps({
        "scanned": len(cards),
        "pure_dups": [[c for c in g] for g in pure_dups],
        "same_query_diff_display": [[c for c in g] for g in same_q_diff_disp],
    }, indent=2, ensure_ascii=False))
    print(f"\nRapport complet : {report}")


if __name__ == "__main__":
    main()
