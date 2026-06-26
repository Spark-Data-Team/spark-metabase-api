#!/usr/bin/env python3
"""Crée des COPIES temporal-unit de cartes « by date » non-conversion (Cost, Clicks,
Orders, COS…) bloquant la bascule du filtre temps. JAMAIS in-place (casserait les
dashboards originaux) : copie dans la sandbox 13885, inscrite au registre
migration/tu-generic-<id>.json (lu par bascule_time_filter).

Recette (éprouvée sur 41349/41350) : préfixe la CTE 'granularity' (sonde l'unité via
le tag temporal-unit sur utils.calendar.date 419201) + remplace chaque
LATERAL(... metabase_filters.time_periods ... {{time_period}} ... LIMIT 1) par
LATERAL(SELECT name FROM granularity LIMIT 1). temporal_units = [day,week,month,year]
(comme l'ancien filtre, sans quarter). Vérif baseline (ancien field-filter) vs copie
(temporal-unit) sur les 4 granularités, sinon archive la copie + skip.

Usage : .venv/bin/python scripts/convert_generic_temporal.py --ids 4324,27970 --client "Goodiespub" --yes
"""
import argparse, json, re, sys, uuid, copy
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from archive_collections import connect_resilient
import conv_lib

SANDBOX = 14115  # collection accessible sous 11673 (PAS le sandbox 13885/13851 — sinon tuiles vides conso)
CTE = (REPO / "scripts" / "granularity_cte.sql").read_text()
LATERAL_RE = re.compile(
    # [^()] (not dotall .) so the match can't span an EARLIER LATERAL's parens
    # (e.g. a brand/comparison-window LATERAL before the time_periods one) — that
    # over-match used to swallow CTE boundaries and drop a downstream CTE.
    # match to the LATERAL's own closing paren ([^()] can't cross it); LIMIT 1 is
    # optional (card 87's time_periods LATERAL has no LIMIT 1, others do).
    r"LATERAL\s*\(\s*SELECT\s+[^()]*?FROM\s+metabase_filters\.time_periods[^()]*?\)",
    re.I | re.S)
GRANS = ["day", "week", "month", "year"]


def transform(sql):
    n_lat = len(LATERAL_RE.findall(sql))
    if n_lat == 0:
        raise ValueError("aucun LATERAL time_periods")
    sql = LATERAL_RE.sub("LATERAL (SELECT name FROM granularity LIMIT 1)", sql)
    s = sql.lstrip()
    if s.upper().startswith("WITH"):
        i = sql.upper().find("WITH") + 4
        return sql[:i] + " " + CTE + sql[i:], n_lat   # CTE finit par ',' -> suivi de la 1ère CTE existante
    # pas de WITH : on en crée un (CTE sans la virgule terminale, suivi du SELECT)
    return "WITH " + CTE.rstrip().rstrip(",") + "\n" + sql, n_lat


def inline_baseline_sql(sql, g):
    """Remplace le LATERAL time_periods par la granularité littérale -> baseline fiable
    (l'ancien field-filter peut être cassé/vide)."""
    return LATERAL_RE.sub(f"(SELECT '{g}' AS name)", sql)


def run(mb, cid, params):
    r = mb.post(f"/api/card/{cid}/query", json={"parameters": params}, timeout=300)
    if not isinstance(r, dict) or r.get("status") != "completed":
        return None
    cols = [c["name"] for c in r["data"]["cols"]]
    return sorted(round(float(x), 4) for row in r["data"]["rows"] for x in row if isinstance(x, (int, float)))


def run_dataset(mb, dq, params):
    body = json.loads(json.dumps(dq)); body["parameters"] = params
    r = mb.post("/api/dataset", json=body, timeout=300)
    if not isinstance(r, dict) or r.get("status") != "completed":
        return None
    cols = [c["name"] for c in r["data"]["cols"]]
    return sorted(round(float(x), 4) for row in r["data"]["rows"] for x in row if isinstance(x, (int, float)))


def close(a, b, tol=1e-9):
    return a is not None and b is not None and len(a) == len(b) and \
        all(x == y or abs(x - y) <= tol * max(abs(x), abs(y), 1e-12) for x, y in zip(a, b))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--window", default="2026-05-01~2026-05-31")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    mb = connect_resilient()
    done = sum(1 for cid in ids if convert_card(mb, cid, args.client, args.window, dry=not args.yes))
    print(f"\n=> {done}/{len(ids)} converties")


def _ptype(tags, name, default):
    return (tags.get(name) or {}).get("widget-type") or default


def base_params(tags, client, window, time_payload):
    p = []
    for ct in ("clients", "client"):  # 'client' singulier (magento) = souvent string/=
        if ct in tags:
            p.append({"type": _ptype(tags, ct, "category"), "value": [client],
                      "target": ["dimension", ["template-tag", ct]]})
    if "date" in tags:
        p.append({"type": _ptype(tags, "date", "date/all-options"), "value": window,
                  "target": ["dimension", ["template-tag", "date"]]})
    if "brand_included" in tags:
        p.append({"type": _ptype(tags, "brand_included", "category"), "value": ["yes"],
                  "target": ["dimension", ["template-tag", "brand_included"]]})
    if time_payload:
        p.append(time_payload)
    return p


def convert_card(mb, cid, client, window, dry=False):
    """Crée une COPIE temporal-unit (sandbox 13885) d'une carte time-driven (conversion
    ou non), vérifiée sur les 4 granularités, inscrite au registre. Retourne new_id si
    OK, None sinon. Idempotent : si déjà au registre, renvoie l'id existant."""
    from conv_paths import reg_dir
    reg = reg_dir() / f"tu-generic-{cid}.json"   # par-client si CONV_REG_DIR (parallèle)
    if not reg.exists() and (REPO / "migration" / f"tu-generic-{cid}.json").exists():
        reg = REPO / "migration" / f"tu-generic-{cid}.json"  # réutilise un maître déjà converti
    if reg.exists():
        d = json.loads(reg.read_text())
        if d.get("verified"):
            return d["new_id"]
    reg = reg_dir() / f"tu-generic-{cid}.json"   # écriture toujours dans le shard
    (REPO / "migration" / "snapshots").mkdir(parents=True, exist_ok=True)
    card = mb.get(f"/api/card/{cid}")
    (REPO / "migration" / "snapshots" / f"card-{cid}-genconv-before.json").write_text(json.dumps(card))
    st0 = card["dataset_query"]["stages"][0]
    sql, tags = st0["native"], st0.get("template-tags") or {}
    try:
        new_sql, n_lat = transform(sql)
    except Exception as e:
        print(f"{cid}: ⛔ transform impossible ({e})"); return None

    base = {}
    base_dq = copy.deepcopy(card["dataset_query"])
    base_dq["stages"][0]["template-tags"] = {k: v for k, v in tags.items() if k != "time_period"}
    for g in GRANS:
        base_dq["stages"][0]["native"] = inline_baseline_sql(sql, g)
        base[g] = run_dataset(mb, base_dq, base_params(tags, client, window, None))

    ndq = copy.deepcopy(card["dataset_query"])
    ndq["stages"][0]["native"] = new_sql
    tag_id = (tags.get("time_period") or {}).get("id") or str(uuid.uuid4())
    ndq["stages"][0]["template-tags"]["time_period"] = {
        "type": "temporal-unit", "name": "time_period", "id": tag_id, "display-name": "Time Period",
        "dimension": ["field", {"lib/uuid": str(uuid.uuid4())}, 419201], "default": "week", "required": False}
    params = [p for p in (card.get("parameters") or []) if p.get("slug") != "time_period"]
    params.append({"id": tag_id, "type": "temporal-unit", "name": "Time Period", "slug": "time_period",
                   "target": ["dimension", ["template-tag", "time_period"]],
                   "temporal_units": GRANS, "default": "week", "required": False, "isMultiSelect": False})
    if dry:
        print(f"{cid} «{card['name'][:40]}»: {n_lat} LATERAL(s) → temporal-unit (dry, baseline {[bool(base[g]) for g in GRANS]})")
        return None
    r = mb.post("/api/card", json={"name": card["name"], "collection_id": SANDBOX, "display": card.get("display"),
                                   "dataset_query": ndq, "parameters": params,
                                   "visualization_settings": card.get("visualization_settings") or {}})
    new_id = r.get("id") if isinstance(r, dict) else None
    if not new_id:
        print(f"{cid}: ⛔ création échouée"); return None
    ok = all(base[g] is not None for g in GRANS)
    for g in GRANS:
        tp = {"type": "temporal-unit", "value": g, "target": ["dimension", ["template-tag", "time_period"]]}
        if not close(base[g], run(mb, new_id, base_params(tags, client, window, tp))):
            ok = False
    if ok:
        reg.write_text(json.dumps({"old_id": cid, "new_id": new_id, "name": card["name"], "verified": True}))
        print(f"{cid} -> {new_id} ✅ ({card['name'][:42]})")
        return new_id
    mb.put(f"/api/card/{new_id}", "raw", json={"archived": True})
    print(f"{cid}: ⛔ vérif échouée → copie {new_id} archivée")
    return None


if __name__ == "__main__":
    main()
