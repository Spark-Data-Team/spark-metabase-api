"""Verify new card 49097 against baseline of card 1567 (rel tol 1e-9)."""
import sys, json
sys.path.insert(0, 'scripts')
from archive_collections import connect_resilient

mb = connect_resilient()
NEW = 49097
DATE_VALUE = "2026-05-01~2026-05-31"
baseline = json.load(open('migration/snapshots/card-1567-baseline-results.json'))

# Sanity: stored SQL/tags as intended
live = mb.get(f'/api/card/{NEW}')
st = live['dataset_query']['stages'][0]
assert 'WITH granularity AS (' in st['native']
assert st['template-tags']['time_period']['type'] == 'temporal-unit'
print('stored card OK: granularity CTE present, tag type temporal-unit, collection', live.get('collection_id'))

PINNED = [
    {"type": "category", "target": ["dimension", ["template-tag", "clients"]], "value": ["Pro Nutrition"]},
    {"type": "date/all-options", "target": ["dimension", ["template-tag", "date"]], "value": DATE_VALUE},
]

def relequal(a, b, tol=1e-9):
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return True
        return abs(a - b) <= tol * max(abs(a), abs(b))
    return a == b

report = {}
all_ok = True
for g in ["day", "week", "month", "year"]:
    params = [{"type": "temporal-unit", "target": ["dimension", ["template-tag", "time_period"]], "value": g}] + PINNED
    r = mb.post(f"/api/card/{NEW}/query", json={"parameters": params}, timeout=240)
    if r.get("status") != "completed":
        print(f"{g}: RUN FAILED {str(r.get('error'))[:300]}")
        report[g] = {"identical": False, "error": str(r.get("error"))[:1000]}
        all_ok = False
        continue
    cols = [c["name"] for c in r["data"]["cols"]]
    rows = sorted(r["data"]["rows"], key=lambda row: (row[0] is None, str(row[0])))
    base = baseline[g]
    ok = cols == base["columns"] and len(rows) == base["row_count"]
    if ok:
        for nr, br in zip(rows, base["rows"]):
            if not all(relequal(x, y) for x, y in zip(nr, br)):
                ok = False
                print(f"{g}: ROW DIFF new={nr} base={br}")
                break
    else:
        print(f"{g}: SHAPE DIFF cols {cols} vs {base['columns']}, rows {len(rows)} vs {base['row_count']}")
    report[g] = {"identical": ok, "rows": len(rows), "columns": cols}
    all_ok = all_ok and ok
    print(f"{g}: identical={ok} rows={len(rows)}")

# Quarter sanity run
params = [{"type": "temporal-unit", "target": ["dimension", ["template-tag", "time_period"]], "value": "quarter"}] + PINNED
r = mb.post(f"/api/card/{NEW}/query", json={"parameters": params}, timeout=240)
if r.get("status") == "completed":
    rows = sorted(r["data"]["rows"], key=lambda row: (row[0] is None, str(row[0])))
    import re
    labels_ok = bool(rows) and all(re.fullmatch(r"\d{4}_Q[1-4]", row[0]) for row in rows)
    report["quarter"] = {"identical": labels_ok, "rows": len(rows), "labels": [row[0] for row in rows]}
    all_ok = all_ok and labels_ok
    print(f"quarter: ran OK rows={len(rows)} labels={[row[0] for row in rows]} plausible={labels_ok}")
else:
    report["quarter"] = {"identical": False, "error": str(r.get("error"))[:1000]}
    all_ok = False
    print(f"quarter: RUN FAILED {str(r.get('error'))[:300]}")

with open('migration/snapshots/card-1567-verify-results.json', 'w') as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
print('ALL_OK:', all_ok)
sys.exit(0 if all_ok else 2)
