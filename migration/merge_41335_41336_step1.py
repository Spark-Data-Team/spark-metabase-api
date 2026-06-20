"""Step 1 — fetch pair 41335 (generic) / 41336 (custom), assert tags, dry-run merge."""
import sys, json
sys.path.insert(0, 'scripts')
sys.path.insert(0, 'migration')
from archive_collections import connect_resilient
from merge_tables import merge_sqls, MergeBlocked

mb = connect_resilient()

GEN, CUS = 41335, 41336
cards = {}
for cid in (GEN, CUS):
    c = mb.get(f'/api/card/{cid}')
    cards[cid] = c
    st = c['dataset_query']['stages'][0]
    print(f"#{cid} name={c['name']!r} db={c['dataset_query']['database']} "
          f"collection={c.get('collection_id')} display={c.get('display')} "
          f"sql_lines={len(st['native'].splitlines())} tags={sorted(st['template-tags'].keys())}")
    json.dump(c, open(f'migration/snapshots/card-{cid}-full.json', 'w'), indent=1)

tg = set(cards[GEN]['dataset_query']['stages'][0]['template-tags'])
tc = set(cards[CUS]['dataset_query']['stages'][0]['template-tags'])
assert tg == tc, f"template-tag sets differ: only-generic={tg-tc} only-custom={tc-tg}"
print("template-tag sets identical:", sorted(tg))

sql_g = cards[GEN]['dataset_query']['stages'][0]['native']
sql_c = cards[CUS]['dataset_query']['stages'][0]['native']
try:
    merged = merge_sqls(sql_g, sql_c)
except MergeBlocked as e:
    print("MERGE_BLOCKED:", e)
    sys.exit(3)

open('migration/merged-41335-41336.sql', 'w').write(merged)
print(f"merged sql: {len(merged.splitlines())} lines "
      f"(generic {len(sql_g.splitlines())}, custom {len(sql_c.splitlines())})")
print("parameters(custom):", json.dumps(cards[CUS].get('parameters'), indent=1)[:1500])
