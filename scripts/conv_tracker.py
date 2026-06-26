#!/usr/bin/env python3
"""Suivi de la migration conversions, client par client, + ancre de campagne.

- ANCRE (TAG) : "[conv-2026-06]" — marqueur de CAMPAGNE (pas date de création). TOUT dashboard
  dupliqué par le chantier conversions le porte, qu'il soit créé en juin, juillet ou après.
- REGISTRE / tracker : migration/conv-migration-tracker.json — 1 entrée par dashboard migré
  (client, dashboard, copy_id, original_id, tagged, status, archive_old, old_archived, notes).
  = source de vérité du « qui remplace qui » → pilote scripts/archive_superseded.py.
- VUE humaine : docs/conversion-migration-tracker.md (régénérée via --render).

Logique pure testée dans tests/test_conv_tracker.py. I/O fines + CLI.

CLI :
  python3 scripts/conv_tracker.py --render   # régénère le markdown depuis le json
  python3 scripts/conv_tracker.py --list     # affiche le tracker
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
from conv_paths import reg_dir, is_isolated
TRACKER_JSON = reg_dir() / "conv-migration-tracker.json"   # par-client si CONV_REG_DIR, sinon migration/
TRACKER_MD = REPO_ROOT / "docs" / "conversion-migration-tracker.md"

TAG = "[conv-2026-06]"   # ancre de CAMPAGNE


# ─── logique pure (testée) ───────────────────────────────────────────

def is_tagged(name) -> bool:
    return bool(name) and TAG in name


def apply_tag(name, tag: str = TAG) -> str:
    """Ajoute l'ancre en suffixe si absente (idempotent)."""
    name = name or ""
    return name if tag in name else f"{name} {tag}".strip()


def upsert_entry(tracker: list, entry: dict) -> list:
    """Ajoute ou MERGE l'entrée (clé = copy_id), sans doublon, ordre préservé."""
    out, found = [], False
    for e in tracker:
        if e.get("copy_id") == entry.get("copy_id"):
            out.append({**e, **entry}); found = True
        else:
            out.append(e)
    if not found:
        out.append(entry)
    return out


def archivable_originals(tracker: list) -> list:
    """Originaux à archiver = OPT-IN EXPLICITE (`archive_old: true`) + original connu + pas déjà
    archivé. Aucune inférence depuis le statut : il faut poser `archive_old` à la main par ligne."""
    return [e["original_id"] for e in tracker
            if e.get("archive_old") is True and e.get("original_id") and not e.get("old_archived")]


_COLS = [("client", "Client"), ("dashboard", "Dashboard"), ("copy_id", "Copie"),
         ("original_id", "Original"), ("tagged", "Taggé"), ("status", "Statut"),
         ("archive_old", "Archiver ancien"), ("old_archived", "Ancien archivé"), ("notes", "Notes")]


def render_markdown(tracker: list) -> str:
    def cell(e, k):
        v = e.get(k)
        if isinstance(v, bool):
            return "✅" if v else "—"
        return "" if v is None else str(v).replace("|", "\\|")  # échappe le séparateur de table
    head = "| " + " | ".join(h for _, h in _COLS) + " |"
    sep = "|" + "|".join("---" for _ in _COLS) + "|"
    rows = ["| " + " | ".join(cell(e, k) for k, _ in _COLS) + " |" for e in tracker]
    return "\n".join([head, sep, *rows])


# ─── I/O ─────────────────────────────────────────────────────────────

def load(path: Path = TRACKER_JSON) -> list:
    return json.loads(path.read_text()) if path.exists() else []


def save(tracker: list, path: Path = TRACKER_JSON):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tracker, ensure_ascii=False, indent=2) + "\n")


def upsert_key(entry: dict) -> tuple:
    """Clé d'identité d'une entrée tracker (pour merge/dédup sans écrasement)."""
    return (entry.get("client"), entry.get("original_id"), entry.get("copy_id"))


def merge_trackers(master: list, shard: list) -> list:
    """Fusionne un shard par-client dans le tracker maître, ADDITIF : une entrée du shard
    remplace l'entrée maître DE MÊME CLÉ (mise à jour), sinon est ajoutée. L'ordre maître
    est préservé ; les nouvelles entrées sont ajoutées à la fin. Aucune perte."""
    by_key = {upsert_key(e): e for e in shard}
    out, seen = [], set()
    for e in master:
        k = upsert_key(e)
        out.append(by_key.get(k, e)); seen.add(k)
    for e in shard:
        if upsert_key(e) not in seen:
            out.append(e)
    return out


def render_to_file(tracker: list, path: Path = TRACKER_MD):
    if is_isolated():
        return  # mode parallèle : la vue .md (partagée) est rendue par le CENTRAL après merge
    n = len(tracker)
    tagged = sum(1 for e in tracker if e.get("tagged"))
    archived = sum(1 for e in tracker if e.get("old_archived"))
    by_client = {}
    for e in tracker:
        by_client.setdefault(e.get("client", "?"), 0)
        by_client[e.get("client", "?")] += 1
    header = (
        "# Migration conversions — SUIVI (généré, ne pas éditer à la main)\n\n"
        f"> Source : `migration/conv-migration-tracker.json` · régénérer : `conv_tracker.py --render`.\n"
        f"> Ancre de campagne : `{TAG}`. **{n} dashboards** · {tagged} taggés · {archived} anciens archivés.\n"
        f"> Clients : " + ", ".join(f"{c} ({k})" for c, k in by_client.items()) + ".\n\n"
        "Statuts : `migré` (copie faite) · `validé` (consultant OK) · `archive_old:true` (opt-in pour "
        "archiver l'ancien) · `old_archived` (ancien archivé). L'archivage des anciens est piloté par "
        "`archive_superseded.py` et ne touche QUE les lignes `archive_old:true`.\n\n"
    )
    path.write_text(header + render_markdown(tracker) + "\n")


# ─── CLI ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--render", action="store_true", help="régénère le markdown depuis le json")
    ap.add_argument("--list", action="store_true", help="affiche le tracker")
    args = ap.parse_args()
    tracker = load()
    if args.render:
        render_to_file(tracker)
        print(f"{TRACKER_MD.relative_to(REPO_ROOT)} régénéré ({len(tracker)} entrées).")
    if args.list or not args.render:
        print(render_markdown(tracker))


if __name__ == "__main__":
    main()
