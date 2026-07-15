"""Annotate every conv-targets tile with the EFFECTIVE visibility of each conversion slot,
accounting for dashcard-level overrides (which win over the card's own settings).

Outputs:
  migration/conv-visibility-by-slot.json  -> per (client, slot): tile counts + verdict
      verdict = VISIBLE  (shown in >=1 tile)   -> genuine consultant/mapping question
              | AMBIGUOUS (never provably shown, but not provably hidden either)
              | HIDDEN    (provably hidden in EVERY tile) -> false positive, auto-droppable

Read-only against Metabase. Caches to migration/_viz_cache.json (resumable).
"""
import sys, json, os
from collections import defaultdict
sys.path.insert(0, "scripts")
from archive_collections import connect_resilient
import conv_lib, conv_visibility as cv

mb = connect_resilient()
CACHE = "migration/_viz_cache.json"
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {"cards": {}, "dashboards": {}}

def card_info(cid):
    k = str(cid)
    if k not in cache["cards"]:
        c = mb.get(f"/api/card/{cid}") or {}
        vs = c.get("visualization_settings") or {}
        names = set()
        for col in (vs.get("table.columns") or []):
            names.add((col.get("name") or "").upper())
        for m in (vs.get("graph.metrics") or []):
            if m:
                names.add(m.upper())
        if vs.get("scalar.field"):
            names.add(vs["scalar.field"].upper())
        for rc in (c.get("result_metadata") or []):
            names.add((rc.get("name") or "").upper())
        cache["cards"][k] = {"display": c.get("display"), "vs": vs, "cols": sorted(n for n in names if n)}
    return cache["cards"][k]

def dashcard_overrides(did):
    k = str(did)
    if k not in cache["dashboards"]:
        d = mb.get(f"/api/dashboard/{did}") or {}
        ov = {}
        for dc in (d.get("dashcards") or d.get("ordered_cards") or []):
            ov[str(dc.get("id"))] = dc.get("visualization_settings") or {}
        cache["dashboards"][k] = ov
    return cache["dashboards"][k]

tg = json.load(open("migration/conv-targets.json"))
agg = {}  # (client, slot) -> tile-status counts
vis_dash = defaultdict(set)   # (client, slot) -> {dashboard_id where a tile is VISIBLE}
shown_dash = defaultdict(set) # (client, slot) -> {dashboard_id where NOT hidden (visible|ambiguous)}
all_dash = defaultdict(set)   # (client, slot) -> {dashboard_id where present at all}
dash_name = {}                # dashboard_id -> name
n = 0
for d in tg:
    client = d.get("client")
    did = d["dashboard_id"]
    dash_name[did] = d.get("dashboard_name", "")
    overrides = dashcard_overrides(did)
    for t in d.get("tiles", []):
        try:
            ci = card_info(t["card_id"])
            # union of every column name we know about, plus the SQL old_cols
            result_cols = set(ci["cols"]) | {c.upper() for c in t.get("old_cols", [])}
            dcvs = overrides.get(str(t.get("dashcard_id")), {})
            # add dashcard-override column names too (they may list columns the card didn't)
            for col in (dcvs.get("table.columns") or []):
                result_cols.add((col.get("name") or "").upper())
            slots = {conv_lib._slot_of(c) for c in t.get("old_cols", [])}
            slots.discard(None)
            for s in slots:
                status = cv.tile_slot_status(ci["display"], ci["vs"], dcvs, result_cols, s)
                a = agg.setdefault((client, s), defaultdict(int))
                a[status] += 1
                all_dash[(client, s)].add(did)
                if status == "visible":
                    vis_dash[(client, s)].add(did)
                if status in ("visible", "ambiguous"):
                    shown_dash[(client, s)].add(did)
        except Exception as e:
            print(f"  !! skip tile card {t.get('card_id')} dash {did}: {e!r}", flush=True)
    n += 1
    if n % 50 == 0:
        json.dump(cache, open(CACHE, "w"))
        print(f"...{n}/{len(tg)} dashboards", flush=True)

json.dump(cache, open(CACHE, "w"))

out = []
for (client, slot), c in sorted(agg.items()):
    visible = c.get("visible", 0); amb = c.get("ambiguous", 0); hid = c.get("hidden", 0)
    verdict = "VISIBLE" if visible else ("AMBIGUOUS" if amb else "HIDDEN")
    vdash = sorted(vis_dash[(client, slot)])
    sdash = sorted(shown_dash[(client, slot)])
    out.append({"client": client, "slot": slot, "verdict": verdict,
                "visible_dashboards": len(vdash), "shown_dashboards": len(sdash),
                "total_dashboards": len(all_dash[(client, slot)]),
                "visible": visible, "ambiguous": amb, "hidden": hid, "absent": c.get("absent", 0),
                "visible_dash_names": [dash_name.get(i, "") for i in vdash],
                "shown_dash_names": [dash_name.get(i, "") for i in sdash]})
json.dump(out, open("migration/conv-visibility-by-slot.json", "w"), ensure_ascii=False, indent=1)

byv = defaultdict(int)
for r in out:
    byv[r["verdict"]] += 1
print(f"\nSlots (client,slot) classés : {len(out)}")
print(f"  VISIBLE   : {byv['VISIBLE']}")
print(f"  AMBIGUOUS : {byv['AMBIGUOUS']}")
print(f"  HIDDEN    : {byv['HIDDEN']}  (masqués partout -> faux positifs)")
print("-> migration/conv-visibility-by-slot.json")
