#!/usr/bin/env python3
"""Extracteur de cards Metabase "check" -> backlog de portage dbt (audit engine, phase 2).

Lecture seule. Pour chaque card Metabase d'une regle d'audit, on dump :
  - le SQL natif (format MLv2 `dataset_query.stages[0].native`, fallback legacy `native.query`),
  - les template-tags (params de scope/seuil),
  - les colonnes de sortie (result_metadata) -> doit matcher audit_check/ratio/target/value,
  - les tables sources (schema.table) reperees dans le SQL -> a mapper en ref() dbt.

Sortie : un fichier .sql par card + un manifest.json + un BACKLOG.md (checklist de port).

Sources d'ids :
  --backlog <alert_cards.json>   lit les check_card_id / details_card_id du fichier de survey Airtable
  --ids 11089,11090,11088        liste explicite d'ids de cards
  --details                      inclut aussi les details_card_id du backlog

Usage :
  python3 scripts/audit_extract_checks.py --backlog ~/Downloads/audit-engine-redesign/metabase-cards/alert_cards.json
  python3 scripts/audit_extract_checks.py --ids 11089,11088 --out /tmp/cards
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT))

from spark_metabase_api import Metabase_API  # noqa: E402
from reorg_phase1 import _load_env  # noqa: E402

DEFAULT_OUT = Path.home() / "Downloads" / "audit-engine-redesign" / "metabase-cards"


def connect() -> Metabase_API:
    """Connexion email/password (resiste a l'expiration de session)."""
    e = _load_env()
    missing = [k for k in ("METABASE_DOMAIN", "METABASE_EMAIL", "METABASE_PASSWORD") if not e.get(k)]
    if missing:
        sys.exit(f"Creds manquants dans .env : {', '.join(missing)}")
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])


def extract_native(dataset_query: dict) -> tuple[str, dict]:
    """Renvoie (sql, template_tags) en gerant MLv2 (stages) et le format legacy."""
    if not isinstance(dataset_query, dict):
        return "", {}
    # MLv2 / pMBQL : dataset_query.stages[0] = {"native": "<sql>", "template-tags": {...}}
    stages = dataset_query.get("stages")
    if isinstance(stages, list) and stages:
        st = stages[0] or {}
        sql = st.get("native") or ""
        tags = st.get("template-tags") or {}
        if sql:
            return sql, tags
    # Legacy : dataset_query.native = {"query": "<sql>", "template-tags": {...}}
    native = dataset_query.get("native") or {}
    return native.get("query") or "", native.get("template-tags") or {}


_TABLE_RE = re.compile(r"(?is)\b(?:from|join)\s+([a-z_][\w$]*\.[a-z_][\w$]*)")


def source_tables(sql: str) -> list[str]:
    """Tables schema.table reperees apres FROM/JOIN (hors CTE), dedupliquees, ordonnees."""
    seen: dict[str, None] = {}
    for m in _TABLE_RE.findall(sql or ""):
        seen.setdefault(m.lower(), None)
    return list(seen)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "card"


def fetch_card(mb: Metabase_API, card_id: int) -> dict | None:
    try:
        return mb.get(endpoint=f"/api/card/{card_id}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! card {card_id}: echec fetch ({exc})")
        return None


def tag_summary(tags: dict) -> list[dict]:
    """Resume chaque template-tag : name, type, default, required, dimension (field-filter)."""
    out = []
    for name, t in (tags or {}).items():
        t = t or {}
        out.append({
            "name": name,
            "type": t.get("type"),                 # text | number | date | dimension
            "default": t.get("default"),
            "required": t.get("required", False),
            "dimension": t.get("dimension"),       # ['field', <id>, ...] pour les field-filters
        })
    return sorted(out, key=lambda x: x["name"])


def card_record(card: dict, meta: dict) -> dict:
    sql, tags = extract_native(card.get("dataset_query") or {})
    out_cols = [c.get("name") for c in (card.get("result_metadata") or []) if c.get("name")]
    tag_details = tag_summary(tags)
    return {
        "card_id": card.get("id"),
        "card_name": card.get("name"),
        "archived": card.get("archived"),
        "collection_id": card.get("collection_id"),
        "database_id": card.get("database_id"),
        "query_type": card.get("query_type"),
        "output_columns": out_cols,
        "template_tags": [t["name"] for t in tag_details],
        "template_tag_details": tag_details,
        "source_tables": source_tables(sql),
        "sql_len": len(sql),
        **meta,  # checkpoint_record_id, checkpoint_id, name (Airtable), platform, severity, role
        "_sql": sql,
    }


def write_sql_file(out: Path, rec: dict) -> Path:
    slug = slugify(rec.get("name") or rec.get("card_name") or "")
    path = out / f"{rec['card_id']}__{slug}.sql"
    tag_lines = [
        f"--   {t['name']:<16} type={t.get('type')!s:<10} default={t.get('default')!r}"
        + (f" dimension={t.get('dimension')}" if t.get("dimension") else "")
        for t in (rec.get("template_tag_details") or [])
    ]
    header = [
        f"-- Metabase card {rec['card_id']} : {rec.get('card_name')}",
        f"-- Airtable check   : {rec.get('name')} [{rec.get('platform')}] severity={rec.get('severity')} role={rec.get('role')}",
        f"-- checkpoint_record_id : {rec.get('checkpoint_record_id')}  (checkpoint_id={rec.get('checkpoint_id')})",
        f"-- output columns  : {', '.join(rec.get('output_columns') or []) or '(n/a)'}",
        f"-- source tables    : {', '.join(rec.get('source_tables') or []) or '(none parsed)'}",
        "-- template tags (name / type / DEFAULT = threshold source for alerts) :",
        *(tag_lines or ["--   (none)"]),
        "-- " + "-" * 70,
        "",
    ]
    path.write_text("\n".join(header) + (rec.get("_sql") or "") + "\n")
    return path


def load_targets(args) -> list[dict]:
    """Renvoie une liste de {card_id, role, ...meta} a extraire."""
    targets: list[dict] = []
    if args.backlog:
        data = json.loads(Path(args.backlog).expanduser().read_text())
        for chk in data.get("checks", []):
            base = {k: chk.get(k) for k in ("checkpoint_record_id", "checkpoint_id", "name", "platform", "severity")}
            if chk.get("check_card_id"):
                targets.append({"card_id": int(chk["check_card_id"]), "role": "check", **base})
            if args.details and chk.get("details_card_id"):
                targets.append({"card_id": int(chk["details_card_id"]), "role": "details", **base})
    if args.ids:
        for raw in args.ids.split(","):
            raw = raw.strip()
            if raw:
                targets.append({"card_id": int(raw), "role": "check"})
    # dedup par card_id (garde la 1re occurrence)
    seen: dict[int, dict] = {}
    for t in targets:
        seen.setdefault(t["card_id"], t)
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backlog", help="JSON de survey (alert_cards.json) : lit check_card_id / details_card_id")
    ap.add_argument("--ids", help="Liste explicite d'ids de cards, separes par des virgules")
    ap.add_argument("--details", action="store_true", help="Inclure aussi les details_card_id du backlog")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"Dossier de sortie (def: {DEFAULT_OUT})")
    args = ap.parse_args()

    if not args.backlog and not args.ids:
        ap.error("fournir --backlog et/ou --ids")

    targets = load_targets(args)
    if not targets:
        sys.exit("Aucune card a extraire (check_card_id tous nuls ?).")

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    mb = connect()
    print(f"Extraction de {len(targets)} card(s) -> {out}")

    manifest: list[dict] = []
    for t in sorted(targets, key=lambda x: x["card_id"]):
        cid = t["card_id"]
        card = fetch_card(mb, cid)
        if card is None:
            manifest.append({"card_id": cid, "role": t.get("role"), "error": "fetch_failed", **{k: v for k, v in t.items() if k != "card_id"}})
            continue
        rec = card_record(card, {k: v for k, v in t.items() if k != "card_id"})
        path = write_sql_file(out, rec)
        public = {k: v for k, v in rec.items() if k != "_sql"}
        public["sql_file"] = path.name
        manifest.append(public)
        print(f"  ok card {cid:<6} role={t.get('role'):<7} cols={len(rec['output_columns'])} tags={len(rec['template_tags'])} -> {path.name}")

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    _write_backlog_md(out, manifest)
    print(f"\nManifest : {out / 'manifest.json'}")
    print(f"Backlog  : {out / 'BACKLOG.md'}")
    return 0


def _write_backlog_md(out: Path, manifest: list[dict]) -> None:
    lines = ["# Metabase check cards — port backlog", "", f"{len(manifest)} card(s) extracted.", ""]
    lines.append("| card | role | platform | sev | output cols | template tags | source tables | airtable check |")
    lines.append("|------|------|----------|-----|-------------|---------------|---------------|----------------|")
    for m in manifest:
        if m.get("error"):
            lines.append(f"| {m['card_id']} | {m.get('role','')} | | | **{m['error']}** | | | {m.get('name','')} |")
            continue
        lines.append(
            f"| {m['card_id']} | {m.get('role','')} | {m.get('platform','')} | {m.get('severity','')} "
            f"| {', '.join(m.get('output_columns') or [])} | {', '.join(m.get('template_tags') or [])} "
            f"| {', '.join(m.get('source_tables') or [])} | {m.get('name','')} |"
        )
    (out / "BACKLOG.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
