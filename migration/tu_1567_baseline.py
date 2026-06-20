"""Baseline runs of original card 1567 (field-filter time_period) for day/week/month/year."""
import sys, json
sys.path.insert(0, 'scripts')
from archive_collections import connect_resilient

mb = connect_resilient()
CARD = 1567
DATE_VALUE = "2026-05-01~2026-05-31"  # same pinned window as 41349/41350 baselines

PINNED = [
    {"type": "category", "target": ["dimension", ["template-tag", "clients"]], "value": ["Pro Nutrition"]},
    {"type": "date/all-options", "target": ["dimension", ["template-tag", "date"]], "value": DATE_VALUE},
]

out = {}
for g in ["day", "week", "month", "year"]:
    params = [{"type": "category", "target": ["dimension", ["template-tag", "time_period"]], "value": [g]}] + PINNED
    r = mb.post(f"/api/card/{CARD}/query", json={"parameters": params}, timeout=240)
    status = r.get("status")
    if status != "completed":
        print(f"{g}: FAILED status={status} error={str(r.get('error'))[:300]}")
        out[g] = {"status": status, "error": str(r.get("error"))[:1000]}
        continue
    data = r["data"]
    cols = [c["name"] for c in data["cols"]]
    rows = sorted(data["rows"], key=lambda row: (row[0] is None, str(row[0])))
    out[g] = {"status": "completed", "run_params": params, "columns": cols, "row_count": len(rows), "rows": rows}
    print(f"{g}: OK cols={cols} rows={len(rows)} first={rows[0] if rows else None}")

with open('migration/snapshots/card-1567-baseline-results.json', 'w') as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print("saved migration/snapshots/card-1567-baseline-results.json")
