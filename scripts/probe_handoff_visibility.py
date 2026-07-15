"""Phase-1 diagnostic v2: are consultant-handoff slots DISPLAYED (strict) or only in SQL?

Per tile, classify how the slot's column appears:
  explicit  = table column with enabled=True  |  chart metric in graph.metrics  |  scalar.field match
  default   = table with table.columns present but column NOT listed (Metabase shows unlisted -> visible, but weaker signal)
  hidden    = table column enabled=False  |  chart with metrics present but column absent
  ambiguous = scalar w/o field, chart w/o metrics, pie/funnel/object/unknown (can't tell)

Per (client, slot) decision:
  STRICT displayed = at least one tile is 'explicit'      (airtight: someone sees it)
  LOOSE  displayed = at least one tile is explicit/default/ambiguous (not provably hidden)
  HIDDEN-ONLY      = every tile is 'hidden'                (safe to drop -> FALSE consultant question)

Read-only. Card viz-settings cached to migration/_card_viz_cache.json.
"""
import sys, json, csv, os
from collections import defaultdict
sys.path.insert(0, "scripts")
from archive_collections import connect_resilient
import conv_lib

mb = connect_resilient()
CACHE = "migration/_card_viz_cache.json"
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}

def viz(cid):
    k = str(cid)
    if k not in cache:
        c = mb.get(f"/api/card/{cid}") or {}
        cache[k] = {"display": c.get("display"), "vs": c.get("visualization_settings") or {}}
    return cache[k]

decisions = {}
with open("migration/HANDOFF-consultants.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        p = r["ref"].split("§")
        if len(p) < 3 or "PAIRING" in p[2]:
            continue
        try:
            decisions[(r["client"], int(p[1]))] = p[2].split()[0]
        except ValueError:
            pass

tg = json.load(open("migration/conv-targets.json"))
tiles_by_client = defaultdict(list)
for d in tg:
    for t in d.get("tiles", []):
        tiles_by_client[d.get("client")].append(t)

ORDER = {"explicit": 3, "default": 2, "ambiguous": 1, "hidden": 0}

def classify(colname, cid):
    v = viz(cid); disp = v["display"]; vs = v["vs"]; up = colname.upper()
    if disp == "table":
        cols = vs.get("table.columns")
        if not cols:
            return "default"  # no explicit list -> shown, but weak signal
        d = {c.get("name", "").upper(): c.get("enabled", True) for c in cols}
        if up in d:
            return "explicit" if d[up] else "hidden"
        return "default"
    if disp in ("line", "bar", "area", "combo", "row", "scatter"):
        m = [x.upper() for x in (vs.get("graph.metrics") or [])]
        if not m:
            return "ambiguous"
        return "explicit" if up in m else "hidden"
    if disp in ("scalar", "smartscalar", "gauge", "progress"):
        f = vs.get("scalar.field")
        if f:
            return "explicit" if f.upper() == up else "hidden"
        return "ambiguous"
    return "ambiguous"

out = []
for (client, slot), kind in sorted(decisions.items()):
    counts = defaultdict(int); explicit_cards = []
    for t in tiles_by_client.get(client, []):
        cols = [c for c in t.get("old_cols", []) if conv_lib._slot_of(c) == slot]
        if not cols:
            continue
        best = "hidden"
        for c in cols:
            cl = classify(c, t["card_id"])
            if ORDER[cl] > ORDER[best]:
                best = cl
        counts[best] += 1
        if best == "explicit":
            explicit_cards.append((t["card_id"], t.get("card_name")))
    n = sum(counts.values())
    strict = counts["explicit"] > 0
    loose = (counts["explicit"] + counts["default"] + counts["ambiguous"]) > 0
    verdict = "STRICT-DISPLAYED" if strict else ("LOOSE-ONLY" if loose else "HIDDEN-ONLY")
    out.append({"client": client, "slot": slot, "kind": kind, "tiles": n,
                "counts": dict(counts), "verdict": verdict,
                "proof_card": explicit_cards[0] if explicit_cards else None})

json.dump(cache, open(CACHE, "w"))
json.dump(out, open("migration/handoff-visibility-probe.json", "w"), ensure_ascii=False, indent=1)

strict = [r for r in out if r["verdict"] == "STRICT-DISPLAYED"]
loose = [r for r in out if r["verdict"] == "LOOSE-ONLY"]
hidden = [r for r in out if r["verdict"] == "HIDDEN-ONLY"]
print(f"Total decisions        : {len(out)}")
print(f"STRICT-DISPLAYED (real): {len(strict)}   (>=1 tile shows it with an explicit flag)")
print(f"LOOSE-ONLY (uncertain) : {len(loose)}    (only default/ambiguous tiles - need eyeball)")
print(f"HIDDEN-ONLY (FALSE)    : {len(hidden)}   (every tile provably hides it -> droppable)")
print()
if hidden:
    print("=== HIDDEN-ONLY (real false positives) ===")
    for r in sorted(hidden, key=lambda r: -r["tiles"]):
        print(f"  {r['client']:<22} slot {r['slot']:<2} {r['kind']:<16} tuiles={r['tiles']} counts={r['counts']}")
if loose:
    print("\n=== LOOSE-ONLY (no explicit display - inspect) ===")
    for r in sorted(loose, key=lambda r: -r["tiles"]):
        print(f"  {r['client']:<22} slot {r['slot']:<2} {r['kind']:<16} tuiles={r['tiles']} counts={r['counts']}")
