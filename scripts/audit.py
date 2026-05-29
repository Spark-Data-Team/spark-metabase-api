#!/usr/bin/env python3
"""Audit instance-wide Metabase : scan (large) → deep (profond) → report.

Lecture seule. Voir :
  docs/superpowers/specs/2026-05-28-metabase-instance-audit-design.md
  docs/superpowers/plans/2026-05-28-metabase-instance-audit.md

Usage :
  python3 scripts/audit.py scan
  python3 scripts/audit.py deep [--limit N]
  python3 scripts/audit.py report
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env  # noqa: E402
import audit_lib  # noqa: E402
from audit_report import render_report  # noqa: E402

MIGRATION_DIR = REPO_ROOT / "migration"
CACHE_DIR = MIGRATION_DIR / "audit-cache"
DOCS_DIR = REPO_ROOT / "docs" / "audits"


def connect_resilient():
    """Connexion email/password (résiste à l'expiration de session sur run long)."""
    env = _load_env()
    domain, email, password = (env.get("METABASE_DOMAIN"),
                               env.get("METABASE_EMAIL"),
                               env.get("METABASE_PASSWORD"))
    if not (domain and email and password):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env (run long).")
    return Metabase_API(domain=domain, email=email, password=password)


def _safe_get(mb, endpoint):
    """GET tolérant : retourne [] sur erreur réseau/HTTP au lieu de tuer le run.

    L'endpoint des archivées est volumineux et l'instance renvoie parfois un
    ConnectionError transitoire (constaté lors de la conception).
    """
    try:
        r = mb.get(endpoint)
    except Exception as e:  # ConnectionError, Timeout, ...
        print(f"  ⚠️  {endpoint} a échoué ({type(e).__name__}) — ignoré.")
        return []
    return r or []


def _latest(prefix):
    files = sorted(MIGRATION_DIR.glob(f"{prefix}-*.json"))
    return files[-1] if files else None


def _template_card_ids(collections, cards):
    """Ids des cartes sous l'arbre du template (215), via location."""
    root = audit_lib.TEMPLATE_ROOT_ID
    tpl_cols = {c.get("id") for c in collections
                if c.get("id") == root or f"/{root}/" in (c.get("location") or "")}
    tpl_cols.add(root)
    return {c["id"] for c in cards if c.get("collection_id") in tpl_cols}


def cmd_scan(args):
    mb = connect_resilient()
    print("Passe large : collections, cartes, dashboards (+ archivés)...")
    collections = _safe_get(mb, "/api/collection/")
    arch_cols = _safe_get(mb, "/api/collection/?archived=true")
    cards = _safe_get(mb, "/api/card/")
    arch_cards = _safe_get(mb, "/api/card/?f=archived")
    dashboards = _safe_get(mb, "/api/dashboard/")

    template_ids = _template_card_ids(collections, cards)

    findings = {}
    empty = audit_lib.find_empty_collections(collections, cards, dashboards)
    findings["empty_collections"] = {"count": len(empty), "items": empty}
    junk = audit_lib.find_junk_collections(collections)
    findings["junk_collections"] = {"count": len(junk), "items": junk}
    dn = audit_lib.find_duplicate_collection_names(collections)
    findings["dup_collection_names"] = {"count": len(dn), "items": dn}
    sprawl = audit_lib.find_personal_sprawl(collections, cards)
    findings["personal_sprawl"] = {"count": len(sprawl), "items": sprawl}
    naming = audit_lib.find_naming_issues(cards, template_ids)
    findings["naming_issues"] = {"count": len(naming), "items": naming}
    findings["archived_backlog"] = {
        "count": len(arch_cards) + len(arch_cols),
        "items": [{"archived_cards": len(arch_cards), "archived_collections": len(arch_cols)}],
    }
    # #5 inutilisées : compte provisoire (sans graphe de sources), affiné en `deep`
    prelim = [c for c in cards if c.get("dashboard_count", 0) == 0 and not c.get("archived")]
    findings["unused_cards"] = {"count": len(prelim),
                                "items": [{"id": c["id"], "name": c.get("name")} for c in prelim],
                                "preliminary": True}
    # patterns enrichis par la passe profonde
    for k in ("pure_dups", "variant_families", "template_drift", "expensive_cards"):
        findings.setdefault(k, {"count": 0, "items": []})

    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = MIGRATION_DIR / f"audit-findings-{ts}.json"
    out.write_text(json.dumps({
        "meta": {"scanned_collections": len(collections), "scanned_cards": len(cards),
                 "archived_cards": len(arch_cards), "archived_collections": len(arch_cols),
                 "template_card_ids": sorted(template_ids), "deep_done": False},
        "findings": findings,
    }, indent=2, ensure_ascii=False))
    print(f"  {len(collections)} collections, {len(cards)} cartes, {len(dashboards)} dashboards")
    print(f"  vides:{len(empty)} fourre-tout:{len(junk)} noms-dupes:{len(dn)} "
          f"sprawl:{len(sprawl)} nommage:{len(naming)} archivées:{len(arch_cards)}/{len(arch_cols)}")
    print(f"Findings écrits : {out}")


def _card_detail(mb, cid):
    """Fetch /api/card/{id} avec cache disque (reprenable). 3 essais espacés."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"card-{cid}.json"
    if f.exists():
        return json.loads(f.read_text())
    for attempt in range(3):
        try:
            d = mb.get(f"/api/card/{cid}")
        except Exception:
            d = None
        if d:
            f.write_text(json.dumps(d, ensure_ascii=False))
            return d
        time.sleep(1.5 * (attempt + 1))
    return None


def cmd_deep(args):
    mb = connect_resilient()
    findings_file = _latest("audit-findings")
    if not findings_file:
        sys.exit("Aucun audit-findings : lancer `scan` d'abord.")
    blob = json.loads(findings_file.read_text())

    cards = _safe_get(mb, "/api/card/")
    if args.limit:
        cards = cards[:args.limit]
    print(f"Passe profonde : fetch de {len(cards)} requêtes (cache {CACHE_DIR})...")
    details = []
    for i, c in enumerate(cards, 1):
        d = _card_detail(mb, c["id"])
        if d:
            details.append(d)
        if i % 200 == 0:
            print(f"  {i}/{len(cards)}")

    groups = audit_lib.classify_query_groups(details)
    source_ids = audit_lib.build_source_ids(details)
    unused = audit_lib.find_unused_cards(details, source_ids)

    tpl_ids = set(blob["meta"].get("template_card_ids", []))
    tpl_cards = [d for d in details if d["id"] in tpl_ids]
    other_cards = [d for d in details if d["id"] not in tpl_ids]
    drift = audit_lib.find_template_drift(tpl_cards, other_cards)

    f = blob["findings"]
    f["pure_dups"] = {"count": len(groups["pure_dups"]),
                      "items": [[{"id": c["id"], "name": c.get("name"), "display": c.get("display")}
                                 for c in g] for g in groups["pure_dups"]]}
    f["variant_families"] = {"count": len(groups["variant_families"]),
                             "items": [[{"id": c["id"], "name": c.get("name")} for c in g]
                                       for g in groups["variant_families"]]}
    now_iso = datetime.now().strftime("%Y-%m-%d")
    unused_items = [{
        "id": c["id"], "name": c.get("name"),
        "last_used_at": c.get("last_used_at"),
        "view_count": c.get("view_count") or 0,
        "days_since_used": audit_lib.days_since(c.get("last_used_at"), now_iso),
        "stale": audit_lib.is_stale(c, now_iso),
    } for c in unused]
    # plus périmées d'abord : jamais utilisées (None) en tête, puis ancienneté, puis vues
    unused_items.sort(key=lambda x: (-(x["days_since_used"] if x["days_since_used"] is not None else 10**9),
                                      x["view_count"]))
    stale_count = sum(1 for u in unused_items if u["stale"])
    f["unused_cards"] = {"count": len(unused_items), "stale_count": stale_count, "items": unused_items}

    # #11 perf : cartes les plus lentes (average_query_time en ms)
    exp = [c for c in details if (c.get("average_query_time") or 0) >= 10000 and not c.get("archived")]
    exp.sort(key=lambda c: -(c.get("average_query_time") or 0))
    f["expensive_cards"] = {"count": len(exp),
                            "items": [{"id": c["id"], "name": c.get("name"),
                                       "avg_query_ms": round(c.get("average_query_time") or 0),
                                       "view_count": c.get("view_count") or 0} for c in exp]}

    f["template_drift"] = {"count": len(drift), "items": drift}
    blob["meta"]["deep_done"] = True
    findings_file.write_text(json.dumps(blob, indent=2, ensure_ascii=False))
    print(f"  doublons:{len(groups['pure_dups'])} variantes:{len(groups['variant_families'])} "
          f"inutilisées:{len(unused)} (périmées≥6mois:{stale_count}) lentes:{len(exp)} dérive:{len(drift)}")
    print(f"Findings enrichis : {findings_file}")


def cmd_report(args):
    findings_file = _latest("audit-findings")
    if not findings_file:
        sys.exit("Aucun audit-findings : lancer `scan` d'abord.")
    blob = json.loads(findings_file.read_text())
    if not blob["meta"].get("deep_done"):
        print("⚠️  passe profonde non exécutée — doublons/variantes/dérive seront à 0. "
              "Lancer `deep` pour un rapport complet.")
    md = render_report(blob["findings"],
                       scanned_cards=blob["meta"].get("scanned_cards", 0),
                       scanned_collections=blob["meta"].get("scanned_collections", 0),
                       date=datetime.now().strftime("%Y-%m-%d"))
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = DOCS_DIR / f"audit-{datetime.now().strftime('%Y%m%d')}.md"
    out.write_text(md)
    print(f"Rapport écrit : {out}")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    d = sub.add_parser("deep")
    d.add_argument("--limit", type=int, default=0, help="ne traiter que les N premières cartes (test)")
    sub.add_parser("report")
    args = p.parse_args()
    {"scan": cmd_scan, "deep": cmd_deep, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
