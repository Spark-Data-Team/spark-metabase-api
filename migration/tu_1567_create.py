"""Create temporal-unit copy of card 1567 in collection 13885."""
import sys, json, uuid
sys.path.insert(0, 'scripts')
from archive_collections import connect_resilient

mb = connect_resilient()
card = json.load(open('migration/snapshots/card-1567-before.json'))
sql = card['dataset_query']['stages'][0]['native']
tags = dict(card['dataset_query']['stages'][0]['template-tags'])

# --- 1. Granularity CTE (verbatim from live card 41350) ---
GRANULARITY_CTE = open('migration/snapshots/card-41350-granularity-cte.txt').read()
assert GRANULARITY_CTE.startswith('WITH granularity AS (') and GRANULARITY_CTE.rstrip().endswith('),')

OLD_WITH = 'WITH data AS ('
assert sql.count(OLD_WITH) == 1
new_sql = sql.replace(OLD_WITH, GRANULARITY_CTE + 'data AS (', 1)

# --- 2. Replace the time_periods LATERAL (motif: SELECT * ... WHERE {{time_period}}, required filter) ---
OLD_LATERAL = "LATERAL (SELECT * FROM metabase_filters.time_periods WHERE {{time_period}} LIMIT 1) AS t"
assert new_sql.count(OLD_LATERAL) == 1
new_sql = new_sql.replace(OLD_LATERAL, "LATERAL (SELECT name FROM granularity LIMIT 1) AS t", 1)

# --- 3. Add quarter branch to the CASE on t.name (label only; no comparison shift in this card) ---
OLD_YEAR = "WHEN t.name = 'year' THEN to_char(date, 'YYYY')\r\n"
assert new_sql.count(OLD_YEAR) == 1
QUARTER = "WHEN t.name = 'year' THEN to_char(date, 'YYYY')\r\n            WHEN t.name = 'quarter' THEN to_char(date, 'YYYY') || '_Q' || QUARTER(date)::TEXT\r\n"
new_sql = new_sql.replace(OLD_YEAR, QUARTER, 1)

assert '{{time_period}}' in new_sql  # only inside granularity CTE now
assert new_sql.count('{{time_period}}') == 1
assert 'metabase_filters.time_periods' not in new_sql

# --- 4. New temporal-unit template tag (field 419201 = UTILS.CALENDAR.DATE; CTE probes utils.calendar) ---
tag_id = str(uuid.uuid4())
tags['time_period'] = {
    "type": "temporal-unit",
    "name": "time_period",
    "id": tag_id,
    "display-name": "Time Period",
    "dimension": ["field", {"lib/uuid": str(uuid.uuid4())}, 419201],
    "default": "week",
    "required": False,
}

dq = {
    "database": card['dataset_query']['database'],
    "lib/type": "mbql/query",
    "stages": [{
        "lib/type": "mbql.stage/native",
        "native": new_sql,
        "template-tags": tags,
    }],
}

# --- Parameters: original card has parameters=None; build full list mirroring tags (41350 pattern) ---
parameters = [{
    "id": tag_id,
    "type": "temporal-unit",
    "target": ["dimension", ["template-tag", "time_period"]],
    "name": "Time Period",
    "slug": "time_period",
    "temporal_units": ["day", "week", "month", "quarter", "year"],
    "default": "week",
    "required": False,
    "isMultiSelect": False,
}]
for name, t in tags.items():
    if name == 'time_period':
        continue
    ptype = "date/all-options" if t.get("widget-type") == "date/all-options" else "category"
    p = {
        "id": t["id"],
        "type": ptype,
        "target": ["dimension", ["template-tag", name]],
        "name": t.get("display-name") or name,
        "slug": name,
    }
    if ptype == "category":
        p["isMultiSelect"] = True
    parameters.append(p)

payload = {
    "name": card['name'],
    "description": card.get('description'),
    "display": card['display'],
    "visualization_settings": card.get('visualization_settings') or {},
    "dataset_query": dq,
    "parameters": parameters,
    "collection_id": 13885,
}

r = mb.post('/api/card', 'raw', json=payload, timeout=120)
print('POST status:', r.status_code)
if r.status_code not in (200, 202):
    print(r.text[:2000])
    sys.exit(1)
new_card = r.json()
print('NEW CARD ID:', new_card['id'])
with open('migration/snapshots/card-1567-new-card.json', 'w') as f:
    json.dump(new_card, f, indent=2, ensure_ascii=False)
with open('migration/snapshots/card-1567-new-sql.txt', 'w') as f:
    f.write(new_sql)
