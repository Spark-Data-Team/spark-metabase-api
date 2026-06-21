#!/usr/bin/env python3
"""Migre les tuiles de conversion d'UN dashboard vers le nouveau système.
Par tuile : détecte la carte ancienne, résout new_type (mapping client) + carte cible
(index de forme), garde-fous relâchés, snapshot, repointe (swap_lib), recâble les
column_settings, valide (structurel + lecture de valeur + réconciliation Snowflake).
NE archive JAMAIS la carte partagée. Réversible (snapshot).

Usage:
  python3 scripts/migrate_conversions_on_dashboard.py --dashboard 14118 --client "Pro Nutrition"          # dry-run
  python3 scripts/migrate_conversions_on_dashboard.py --dashboard 14118 --client "Pro Nutrition" --copy --yes  # migre une COPIE
  python3 scripts/migrate_conversions_on_dashboard.py --dashboard 14118 --client "Pro Nutrition" --yes     # applique in-place + snapshot
"""
import argparse, json, sys
from datetime import datetime
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO))
from spark_metabase_api import Metabase_API
from reorg_phase1 import _load_env
import swap_lib, conv_lib
from spark_metabase_api import validate as V

MIG = REPO / "migration"

def connect():
    e = _load_env()
    return Metabase_API(domain=e["METABASE_DOMAIN"], email=e["METABASE_EMAIL"], password=e["METABASE_PASSWORD"])

def _dashcards(d):
    return d.get("dashcards") or d.get("ordered_cards") or []

def load_inputs():
    mapping = json.loads((MIG / "conv-client-mapping.json").read_text())
    raw = json.loads((MIG / "conv-new-index.json").read_text())
    index = {}
    for k, v in raw.items():
        col, bd = json.loads(k)
        index[(col, tuple(bd))] = v
    return mapping, index

def remap_column_settings(viz, old_col, new_col):
    """Re-key dashcard column_settings ["name","OLD_COL"] -> NEW_COL so number formatting applies."""
    cs = (viz or {}).get("column_settings")
    if not cs:
        return viz
    out = dict(viz)
    new_cs = {}
    for k, val in cs.items():
        nk = k.replace(f'"{old_col}"', f'"{new_col}"').replace(f'"{old_col.lower()}"', f'"{new_col.lower()}"')
        new_cs[nk] = val
    out["column_settings"] = new_cs
    return out

def reconcile(mb, client, old_col, new_col, start, end):
    """Independent SUM of old/new columns over the same join chain (Snowflake via /api/dataset)."""
    sql = f"""
WITH base AS (
  SELECT global.campaign_daily_metrics.{old_col} AS old_c,
         global.campaign_daily_metrics.{new_col} AS new_c
  FROM utils.clients
    JOIN utils.client_ad_platforms ON client_id = utils.clients.id
    JOIN reports.campaign_details ON reports.campaign_details.account_id = utils.client_ad_platforms.account_id
    JOIN global.campaign_daily_metrics ON global.campaign_daily_metrics.campaign_id = reports.campaign_details.campaign_id
  WHERE utils.clients.name = '{client}'
    AND global.campaign_daily_metrics.date BETWEEN '{start}' AND '{end}')
SELECT COALESCE(SUM(old_c),0), COALESCE(SUM(new_c),0) FROM base""".strip()
    ds = mb.post("/api/dataset", json={"database": 144, "type": "native", "native": {"query": sql}}, timeout=180)
    rows = ds.get("data", {}).get("rows") if isinstance(ds, dict) else None
    return (rows[0][0], rows[0][1]) if rows else (None, None)

def tile_value(mb, dash_id, dc_id, card_id, client, date_range):
    d = mb.get(f"/api/dashboard/{dash_id}")
    dc = next((x for x in _dashcards(d) if x.get("id") == dc_id), {})
    params = []
    for pm in dc.get("parameter_mappings") or []:
        p = next((q for q in d.get("parameters") or [] if q.get("id") == pm.get("parameter_id")), {})
        val = [client] if p.get("slug") == "client" else (date_range if p.get("slug") == "date" else None)
        if val is not None:
            params.append({"id": p["id"], "type": p.get("type"), "value": val, "target": pm.get("target")})
    r = mb.post(f"/api/dashboard/{dash_id}/dashcard/{dc_id}/card/{card_id}/query", json={"parameters": params}, timeout=120)
    try:
        return r["data"]["rows"][-1][-1]
    except Exception:
        return None

def card_values(mb, card_id, client, window):
    """All numeric values a card returns for (client, window), sorted. Used to prove a
    swap doesn't change anything (old card values == new card values)."""
    c = mb.get(f"/api/card/{card_id}")
    _, tags = conv_lib.native_and_tags(c)
    params = []
    if "clients" in tags:
        params.append({"type": "string/=", "value": [client], "target": ["dimension", ["template-tag", "clients"]]})
    if "date" in tags:
        params.append({"type": "date/all-options", "value": window, "target": ["dimension", ["template-tag", "date"]]})
    r = mb.post(f"/api/card/{card_id}/query", json={"parameters": params}, timeout=120)
    rows = (r or {}).get("data", {}).get("rows", []) or []
    return sorted(round(float(x), 4) for row in rows for x in row if isinstance(x, (int, float)))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", type=int, required=True)
    ap.add_argument("--client", required=True)
    ap.add_argument("--copy", action="store_true", help="migrer une copie (test) au lieu de l'original")
    ap.add_argument("--yes", action="store_true", help="appliquer (sinon dry-run)")
    ap.add_argument("--window", default="2026-05-01~2026-05-31", help="fenêtre de validation date/all-options")
    ap.add_argument("--no-verify", action="store_true", help="ne PAS vérifier avant/après (déconseillé)")
    args = ap.parse_args()
    mb = connect()
    mapping_all, index = load_inputs()
    cmap = {int(k): v for k, v in mapping_all.get(args.client, {}).items()}
    if not cmap:
        sys.exit(f"Aucun mapping pour client {args.client!r} (conv-client-mapping.json).")

    src = args.dashboard
    if args.copy and args.yes:
        cp = mb.post(f"/api/dashboard/{src}/copy", json={"collection_id": None, "name": f"MIGRATION TEST {src}", "is_deep_copy": False})
        src = cp["id"]
        print(f"copie -> dashboard {src}")
    dash = mb.get(f"/api/dashboard/{src}")
    dcs = _dashcards(dash)

    plan, report = [], {"dashboard": src, "client": args.client, "tiles": []}
    for dc in dcs:
        cid = dc.get("card_id")
        if not cid:
            continue
        card = mb.get(f"/api/card/{cid}")
        sql, _ = conv_lib.native_and_tags(card)
        if not conv_lib.old_conversion_columns(sql):
            continue
        res = conv_lib.resolve_new_card(card, cmap, index)
        entry = {"dashcard_id": dc["id"], "old_card": cid, "old_name": card.get("name"), **res}
        if res["status"] == "ok":
            new = mb.get(f"/api/card/{res['new_card_id']}")
            ref = swap_lib.referenced_template_tags(dcs, cid)
            _, ntags = conv_lib.native_and_tags(new)
            renames = conv_lib.tag_rename_map(card, new)  # e.g. location -> campaign_location
            problems = []
            if new.get("archived"):
                problems.append("new archived")
            if card.get("database_id") != new.get("database_id"):
                problems.append("different DB")
            miss = ref - set(ntags) - set(renames)  # a renamed filter is re-wireable, not missing
            if miss:
                problems.append(f"new misses tags {sorted(miss)}")
            entry["safety"] = problems
            if renames:
                entry["renames"] = renames
            if problems:
                entry["status"] = "blocked"
            else:
                oc = res["old_col"]  # resolver supplies old+new cols for reconciliation
                entry["old_col"] = oc
                plan.append((dc, card, new, res, oc, renames))
        report["tiles"].append(entry)

    MIG.mkdir(exist_ok=True)
    rpt = MIG / f"conv-report-{src}.json"
    rpt.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"REPORT_FILE: {rpt}")  # consumers read this (wrapper pollutes stdout with an auth line)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if not args.yes or not plan:
        print("\n(DRY-RUN ou rien à faire — aucune modification.)")
        return

    # GARDE-FOU: ne remplacer une tuile que si la valeur avant == après (sinon on la laisse sur l'ancien).
    if not args.no_verify:
        verified = []
        for item in plan:
            _dc, _card, _new, _res, _oc, _ren = item
            before = card_values(mb, _card["id"], args.client, args.window)
            after = card_values(mb, _res["new_card_id"], args.client, args.window)
            if all(f.level == "ok" for f in V.check_values(_card.get("name"), before, after, mode="identical")):
                verified.append(item)
            else:
                print(f"  ⚠️ NON migrée «{_card.get('name')}» — valeur avant/après différente "
                      f"({len(before)} vs {len(after)} valeurs) → laissée sur l'ancien système")
        plan = verified
        print(f"Vérifiées identiques avant/après : {len(plan)} tuile(s) à migrer.")
        if not plan:
            print("(Rien de vérifié-identique — aucune modification.)")
            return

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap = MIG / f"conv-migrate-snapshot-{src}-{ts}.json"
    snap.write_text(json.dumps({"dashboard": src, "dashcards": dcs}, ensure_ascii=False, indent=2))
    print(f"snapshot: {snap}")

    new_dcs = dcs
    for dc, card, new, res, oc, renames in plan:
        new_dcs, _ = swap_lib.rewrite_dashcards(new_dcs, card["id"], res["new_card_id"])
        for ndc in new_dcs:
            if ndc.get("id") == dc["id"]:
                ndc["visualization_settings"] = remap_column_settings(ndc.get("visualization_settings") or {}, oc, res["new_col"])
                for pm in ndc.get("parameter_mappings") or []:
                    tgt = pm.get("target")
                    try:
                        if tgt[1][0] == "template-tag" and tgt[1][1] in renames:
                            tgt[1][1] = renames[tgt[1][1]]  # re-wire renamed filter (location->campaign_location)
                    except Exception:
                        pass
    rc = mb.put(f"/api/dashboard/{src}", json={"dashcards": new_dcs})
    print(f"PUT dashboard {src}: {rc}")

    start, end = args.window.split("~")
    for dc, card, new, res, oc, renames in plan:
        nv = tile_value(mb, src, dc["id"], res["new_card_id"], args.client, args.window)
        if res.get("source") == "global.campaign_daily_metrics":
            o_sum, n_sum = reconcile(mb, args.client, oc, res["new_col"], start, end)
            ok = (nv is not None and n_sum is not None and abs(float(nv) - float(n_sum)) < 1e-6)
            print(f"  tile {dc['id']} {card['name']!r} -> #{res['new_card_id']}: tile={nv} snowflake_new={n_sum} reconciled={ok} (old_sum={o_sum})")
        else:
            print(f"  tile {dc['id']} {card['name']!r} -> #{res['new_card_id']}: tile={nv} (source {res.get('source')}: réconciliation manuelle)")
    print(f"\nRollback: restaurer dashcards depuis {snap}.")

if __name__ == "__main__":
    main()
