#!/usr/bin/env python3
"""Archive les collections vides détectées par l'audit (vague 0, réversible).

Sécurité :
- Re-vérification LIVE de la vacuité via /api/collection/<id>/items : on n'archive
  que si la collection ne contient QUE des sous-collections elles-mêmes candidates
  vides (toute carte / dashboard / dataset / sous-collection non-candidate -> on saute).
- Exclut par défaut le template (sous /215/) : ces vides sont des placeholders curés
  (ex. « 18. Nouvelles Conversions »). --include-template pour les inclure.
- Archivage réversible (PUT archived:false pour annuler). Écrit la liste pour rollback.

Usage :
  python3 scripts/archive_empty_collections.py                    # dry-run (catégorise)
  python3 scripts/archive_empty_collections.py --yes              # archive le set "safe"
  python3 scripts/archive_empty_collections.py --include-template --yes
"""
from __future__ import annotations

import argparse
import csv
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

MIGRATION_DIR = REPO_ROOT / "migration"
TEMPLATE_ROOT_ID = 215


def connect_resilient() -> Metabase_API:
    env = _load_env()
    d, e, p = env.get("METABASE_DOMAIN"), env.get("METABASE_EMAIL"), env.get("METABASE_PASSWORD")
    if not (d and e and p):
        sys.exit("METABASE_DOMAIN / EMAIL / PASSWORD requis dans .env.")
    return Metabase_API(domain=d, email=e, password=p)


def _latest_findings():
    fs = sorted(MIGRATION_DIR.glob("audit-findings-*.json"))
    if not fs:
        sys.exit("Aucun audit-findings : lancer `audit.py scan` d'abord.")
    return json.loads(fs[-1].read_text())


def _is_template(col):
    return col.get("id") == TEMPLATE_ROOT_ID or f"/{TEMPLATE_ROOT_ID}/" in (col.get("location") or "")


def _top_ancestor_name(col, live):
    parts = [p for p in (col.get("location") or "/").strip("/").split("/") if p.isdigit()]
    if parts and int(parts[0]) in live:
        return live[int(parts[0])].get("name") or "?"
    return "(racine)"


def _under_personal(col, live):
    """True si un ancêtre (via location) est une collection personnelle.

    find_empty_collections exclut les collections perso elles-mêmes, mais pas leurs
    sous-collections vides — qui relèvent de la campagne sprawl (zone sensible).
    """
    for part in (col.get("location") or "/").strip("/").split("/"):
        if part.isdigit():
            anc = live.get(int(part))
            if anc and anc.get("personal_owner_id"):
                return True
    return False


def _get_retry(mb, endpoint, tries=3):
    for attempt in range(tries):
        try:
            r = mb.get(endpoint)
        except Exception:
            r = None
        if r is not False and r is not None:
            return r
        time.sleep(1.0 * (attempt + 1))
    return None


def reverify_empty(mb, cid, candidate_ids):
    """True si la collection ne contient que des sous-collections candidates vides.

    Retourne None si la lecture échoue (incertain -> on ne touche pas).
    """
    r = _get_retry(mb, f"/api/collection/{cid}/items?limit=2000")
    if not isinstance(r, dict):
        return None
    for it in r.get("data", []):
        if it.get("model") == "collection" and it.get("id") in candidate_ids:
            continue
        return False  # carte / dashboard / dataset / sous-collection non-candidate
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--yes", action="store_true", help="archive réellement (sinon dry-run)")
    ap.add_argument("--include-template", action="store_true",
                    help="inclure aussi les vides sous le template 215")
    ap.add_argument("--include-personal-nested", action="store_true",
                    help="inclure aussi les vides nichées sous une collection personnelle (sprawl)")
    ap.add_argument("--exclude", default="",
                    help="ids à retirer de la cible, séparés par des virgules (ex. 11212,11345)")
    args = ap.parse_args()
    exclude_ids = {int(x) for x in args.exclude.split(",") if x.strip().isdigit()}

    mb = connect_resilient()
    blob = _latest_findings()
    candidates = blob["findings"]["empty_collections"]["items"]
    cand_ids = {c["id"] for c in candidates}
    live = {c.get("id"): c for c in (mb.get("/api/collection/") or [])}

    print(f"Re-vérification live de {len(candidates)} collections vides...")
    safe, template, personal_nested, skipped = [], [], [], []
    for c in candidates:
        cid = c["id"]
        col = live.get(cid)
        if col is None:
            skipped.append({**c, "why": "absente de la liste active"})
            continue
        if col.get("type"):  # collection système (Metrics Library) — non archivable
            skipped.append({**c, "why": f"système (type={col.get('type')})"})
            continue
        verdict = reverify_empty(mb, cid, cand_ids)
        if verdict is not True:
            skipped.append({**c, "why": "non vide" if verdict is False else "lecture échouée"})
            continue
        entry = {"id": cid, "name": col.get("name"), "location": col.get("location")}
        if _under_personal(col, live):
            personal_nested.append(entry)
        elif _is_template(col):
            template.append(entry)
        else:
            safe.append(entry)

    print(f"\n=== {len(safe)} VIDES sûres (hors template, hors perso) ===")
    for c in sorted(safe, key=lambda x: str(x["name"])):
        print(f"  #{c['id']:>6}  {c['name']}")
    print(f"\n=== {len(template)} vides SOUS TEMPLATE (exclues par défaut — placeholders curés) ===")
    for c in sorted(template, key=lambda x: str(x["name"])):
        print(f"  #{c['id']:>6}  {c['name']}  ({c['location']})")
    print(f"\n=== {len(personal_nested)} vides NICHÉES EN PERSO (exclues par défaut — campagne sprawl) ===")
    for c in sorted(personal_nested, key=lambda x: str(x["name"])):
        print(f"  #{c['id']:>6}  {c['name']}  ({c['location']})")
    if skipped:
        print(f"\n=== {len(skipped)} sautées (contenu gagné / disparues / lecture KO) ===")
        for c in skipped[:15]:
            print(f"  #{c['id']:>6}  {str(c.get('name'))[:40]:40} — {c['why']}")

    target = safe + (template if args.include_template else []) \
        + (personal_nested if args.include_personal_nested else [])
    if exclude_ids:
        kept = [c for c in target if c["id"] not in exclude_ids]
        print(f"\n--exclude : {len(target) - len(kept)} retirée(s) de la cible.")
        target = kept
    MIGRATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = MIGRATION_DIR / f"archive-empty-collections-{ts}.json"
    log.write_text(json.dumps([c["id"] for c in target], indent=2))

    # CSV de relecture (toutes les catégories), pour validation humaine
    review = MIGRATION_DIR / f"empty-collections-review-{ts}.csv"
    with review.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["categorie", "id", "nom", "dossier_racine", "location"])
        for label, rows_ in (("safe", safe), ("template", template), ("perso_niche", personal_nested)):
            for c in sorted(rows_, key=lambda x: str(x["name"])):
                w.writerow([label, c["id"], c["name"], _top_ancestor_name(c, live), c.get("location")])
    print(f"\nCible d'archivage : {len(target)} collections — liste/rollback : {log}")
    print(f"Relecture (CSV, {len(safe)+len(template)+len(personal_nested)} lignes) : {review}")

    if not args.yes:
        print("\n(DRY-RUN — rien archivé. Relancer avec --yes pour archiver.)")
        return

    print(f"\n=== Archivage de {len(target)} collections (réversible)... ===")
    done, miss = [], []
    for c in sorted(target, key=lambda x: len(x.get("location") or ""), reverse=True):  # enfants d'abord
        cid = c["id"]
        if reverify_empty(mb, cid, cand_ids) is not True:
            print(f"  SAUTÉ #{cid} «{c['name']}» : non vide à la re-vérif")
            miss.append(cid)
            continue
        rc = mb.put(f"/api/collection/{cid}", json={"archived": True})
        if rc == 200:
            done.append(cid)
            print(f"  archivée #{cid} «{c['name']}»")
        else:
            print(f"  ÉCHEC #{cid} «{c['name']}» (HTTP {rc})")
            miss.append(cid)
    print(f"\n=== {len(done)} archivée(s), {len(miss)} sautée(s)/échec ===")
    print(f"Rollback : PUT /api/collection/<id> {{archived:false}} pour les ids de {log}")


if __name__ == "__main__":
    main()
