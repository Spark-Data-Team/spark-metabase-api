export const meta = {
  name: 'sql-antipattern-audit',
  description: 'Classify Metabase native cards for 2 SQL anti-patterns (kp JOIN missing language/zone; eaten regex escape), then adversarially verify every BUG',
  phases: [
    { title: 'Analyze', detail: 'one auditor per candidate card reads its SQL and renders a verdict' },
    { title: 'Verify', detail: 'diverse-lens skeptics try to refute each BUG' },
  ],
}

// Task list injected by build_antipattern_workflow.py (metadata only, no SQL —
// each agent reads its own .sql file from disk).
const TASKS = [{"task_id": "A-28512", "antipattern": "A", "card_id": 28512, "name": "Average bid cost (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28512.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_aggregated_metrics"], "dashboards": [11747, 13158, 16953]}, {"task_id": "A-28551", "antipattern": "A", "card_id": 28551, "name": "Best opportunity keywords (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28551.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics", "kp__keyword_aggregated_metrics"], "dashboards": [11747, 16953]}, {"task_id": "A-31648", "antipattern": "A", "card_id": 31648, "name": "Client rank group, estimated traffic, rank absolute, rank group, search volume by keyword, rank gap, url (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-31648.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": []}, {"task_id": "A-15943", "antipattern": "A", "card_id": 15943, "name": "Concurrence scatter plot [share of voice vs presence top 10, scale estimated traffic] (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15943.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11509, 11721, 11747, 11885]}, {"task_id": "A-15948", "antipattern": "A", "card_id": 15948, "name": "Corpus search volume distribution (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15948.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11721, 11747, 11885, 11943, 12993]}, {"task_id": "A-28549", "antipattern": "A", "card_id": 28549, "name": "Flop trending keywords (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28549.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics", "kp__keyword_aggregated_metrics"], "dashboards": [11747, 16953]}, {"task_id": "A-15949", "antipattern": "A", "card_id": 15949, "name": "Keyword insights [focus client] (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15949.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11509, 11721, 11747, 11885, 11943, 12993]}, {"task_id": "A-15999", "antipattern": "A", "card_id": 15999, "name": "Keyword insights [focus SERP functionality]", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15999.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11721, 11885, 11943, 12993]}, {"task_id": "A-15953", "antipattern": "A", "card_id": 15953, "name": "Keyword insights [top kw competitors] (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15953.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11721, 11747, 11885, 11943, 12993]}, {"task_id": "A-15952", "antipattern": "A", "card_id": 15952, "name": "Keyword insights [top kw corpus] (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15952.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11509, 11721, 11747, 11885, 11943, 12993, 13489, 15176]}, {"task_id": "A-32433", "antipattern": "A", "card_id": 32433, "name": "Keyword insights w/ historic comparison [top kw corpus] (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-32433.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [14780, 17250, 17481, 17977, 18042, 18544, 19560, 20022]}, {"task_id": "A-16326", "antipattern": "A", "card_id": 16326, "name": "Keyword insights w/ SERP functionalities [focus client] (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-16326.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11376, 11721, 11747, 11885, 11943, 12993]}, {"task_id": "A-28100", "antipattern": "A", "card_id": 28100, "name": "Keyword overlap | table (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28100.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157]}, {"task_id": "A-32496", "antipattern": "A", "card_id": 32496, "name": "Keywords average ranking by date (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-32496.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [17250]}, {"task_id": "A-15938", "antipattern": "A", "card_id": 15938, "name": "KP monthly | Duplicates", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15938.sql", "has_join": false, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11343]}, {"task_id": "A-16650", "antipattern": "A", "card_id": 16650, "name": "Market share by domain (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-16650.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11509]}, {"task_id": "A-16707", "antipattern": "A", "card_id": 16707, "name": "Market share (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-16707.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11509]}, {"task_id": "A-31641", "antipattern": "A", "card_id": 31641, "name": "Max traffic on best possible keyword rankings (monthly) (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-31641.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": []}, {"task_id": "A-15939", "antipattern": "A", "card_id": 15939, "name": "Monthly estimated traffic by domain (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15939.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11721, 11747, 11885, 11943, 12993]}, {"task_id": "A-15937", "antipattern": "A", "card_id": 15937, "name": "Monthly estimated traffic only on client position keywords (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15937.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11509, 11721, 11747, 11885, 11943, 12993, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "A-18400", "antipattern": "A", "card_id": 18400, "name": "Monthly max estimated traffic on best possible keyword rankings (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-18400.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 12993, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "A-15942", "antipattern": "A", "card_id": 15942, "name": "Monthly max estimated traffic only on client position keywords (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15942.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11509, 11721, 11747, 11885, 11943, 12993, 14780, 17481, 17977, 18042, 18544, 19560, 20022]}, {"task_id": "A-28550", "antipattern": "A", "card_id": 28550, "name": "Most expensive keywords (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28550.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics", "kp__keyword_aggregated_metrics"], "dashboards": [11747, 16953]}, {"task_id": "A-28614", "antipattern": "A", "card_id": 28614, "name": "Performances by keyword (GSC) | Quiz Room", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28614.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [13587, 14577]}, {"task_id": "A-31645", "antipattern": "A", "card_id": 31645, "name": "Ranking, share of voice by domain (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-31645.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": []}, {"task_id": "A-15946", "antipattern": "A", "card_id": 15946, "name": "Search volume by month (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15946.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11509, 11721, 11747, 11885, 11943, 12993, 18544, 20022]}, {"task_id": "A-28206", "antipattern": "A", "card_id": 28206, "name": "Search volume by month (SERP) w/ date filter", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28206.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [12069, 13257, 13489, 15176]}, {"task_id": "A-28513", "antipattern": "A", "card_id": 28513, "name": "Search volume by month YoY (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28513.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11747, 13158, 16953]}, {"task_id": "A-16708", "antipattern": "A", "card_id": 16708, "name": "Search volume last month (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-16708.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11509]}, {"task_id": "A-48633", "antipattern": "A", "card_id": 48633, "name": "SEO Keyword Monitoring — Manucurist (model)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-48633.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": []}, {"task_id": "A-28715", "antipattern": "A", "card_id": 28715, "name": "SEO/SEA synergy by keyword", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28715.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_aggregated_metrics"], "dashboards": [10189, 14911, 19335]}, {"task_id": "A-30516", "antipattern": "A", "card_id": 30516, "name": "SEO/SEA synergy by keyword (IA report) | Ecommerce", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-30516.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_aggregated_metrics"], "dashboards": []}, {"task_id": "A-30517", "antipattern": "A", "card_id": 30517, "name": "SEO/SEA synergy by keyword (IA report) | Lead gen", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-30517.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_aggregated_metrics"], "dashboards": []}, {"task_id": "A-16647", "antipattern": "A", "card_id": 16647, "name": "SEO value (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-16647.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_aggregated_metrics"], "dashboards": [10157, 11509, 11721, 11747, 11885, 11943, 12993, 15831]}, {"task_id": "A-31642", "antipattern": "A", "card_id": 31642, "name": "SEO value (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-31642.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_aggregated_metrics"], "dashboards": []}, {"task_id": "A-28471", "antipattern": "A", "card_id": 28471, "name": "Share of voice by domain, top 100 only (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28471.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11747]}, {"task_id": "A-15941", "antipattern": "A", "card_id": 15941, "name": "Share of voice by domain, top 10 only (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15941.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11509, 11721, 11747, 11885, 11943, 12993, 19758]}, {"task_id": "A-28923", "antipattern": "A", "card_id": 28923, "name": "Share of voice by domain, top 10 only w/ historic comparison (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28923.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 14780, 17250, 17481, 17977, 18042, 18544, 19560, 20022]}, {"task_id": "A-38733", "antipattern": "A", "card_id": 38733, "name": "Share of voice client all extraction dates (SERP) | Arrago", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-38733.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": []}, {"task_id": "A-15940", "antipattern": "A", "card_id": 15940, "name": "Share of voice client (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-15940.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 11509, 11721, 11885, 11943, 12993, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "A-31609", "antipattern": "A", "card_id": 31609, "name": "Share of voice (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-31609.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": []}, {"task_id": "A-28922", "antipattern": "A", "card_id": 28922, "name": "Share of voice w/ historic comparison (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28922.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 14780, 17250, 17481, 17977, 18042, 18544, 19560, 20022]}, {"task_id": "A-34378", "antipattern": "A", "card_id": 34378, "name": "Spark score (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-34378.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_aggregated_metrics"], "dashboards": [10157]}, {"task_id": "A-31611", "antipattern": "A", "card_id": 31611, "name": "Top keyword client : position 11 to 30, top 10 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-31611.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": []}, {"task_id": "A-31610", "antipattern": "A", "card_id": 31610, "name": "Top keyword client : position 4 to 10, top 10 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-31610.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": []}, {"task_id": "A-28554", "antipattern": "A", "card_id": 28554, "name": "Top keywords & associated competitor results", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28554.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11747, 16953]}, {"task_id": "A-28553", "antipattern": "A", "card_id": 28553, "name": "Top keywords & associated top result (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28553.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11747]}, {"task_id": "A-28869", "antipattern": "A", "card_id": 28869, "name": "Top kw client position 11 to 30 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28869.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "A-28867", "antipattern": "A", "card_id": 28867, "name": "Top kw client position 1 to 3 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28867.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "A-28870", "antipattern": "A", "card_id": 28870, "name": "Top kw client position 31 to 100 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28870.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "A-28868", "antipattern": "A", "card_id": 28868, "name": "Top kw client position 4 to 10 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28868.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [10157, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "A-28547", "antipattern": "A", "card_id": 28547, "name": "Top trending keywords (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28547.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics", "kp__keyword_aggregated_metrics"], "dashboards": [11747, 16953]}, {"task_id": "A-28125", "antipattern": "A", "card_id": 28125, "name": "Total corpus search volumes YoY (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/A-28125.sql", "has_join": true, "mentions_airtable_record_id": false, "kp_tables": ["kp__keyword_monthly_metrics"], "dashboards": [11747, 13158, 16953]}, {"task_id": "B-11277", "antipattern": "B", "card_id": 11277, "name": "audit details | naming des éléments de structure non conforme | --", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-11277.sql", "regex_funcs": ["REGEXP_LIKE"], "escaped_metachars": ["\\|"], "dashboards": []}, {"task_id": "B-11276", "antipattern": "B", "card_id": 11276, "name": "audit | naming des éléments de structure non conforme | --", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-11276.sql", "regex_funcs": ["REGEXP_LIKE"], "escaped_metachars": ["\\|"], "dashboards": []}, {"task_id": "B-35963", "antipattern": "B", "card_id": 35963, "name": "Benchmark blended CTR agency level", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-35963.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11917]}, {"task_id": "B-36028", "antipattern": "B", "card_id": 36028, "name": "Benchmark blended CTR e-commerce", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-36028.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11917]}, {"task_id": "B-36027", "antipattern": "B", "card_id": 36027, "name": "Benchmark blended CTR lead gen", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-36027.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11917]}, {"task_id": "B-35632", "antipattern": "B", "card_id": 35632, "name": "Benchmark blended CTR (model) by date", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-35632.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11917]}, {"task_id": "B-35631", "antipattern": "B", "card_id": 35631, "name": "Blended CTR agency level by date", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-35631.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11917]}, {"task_id": "B-16748", "antipattern": "B", "card_id": 16748, "name": "Blended CTR, cost by date (cross search)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-16748.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11666, 11702, 11917, 11920, 12898, 12974, 13885, 17151, 17184, 18801, 21210, 23589]}, {"task_id": "B-16756", "antipattern": "B", "card_id": 16756, "name": "Blended CTR [total = paid + organic] (cross search)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-16756.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11666, 11917, 11920, 12898, 12974, 13885, 18801]}, {"task_id": "B-31011", "antipattern": "B", "card_id": 31011, "name": "CTR [paid only] (brand monitoring) - smartscallar", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-31011.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11702, 17151, 17184, 21210, 23589]}, {"task_id": "B-8233", "antipattern": "B", "card_id": 8233, "name": "goals checked by date", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-8233.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\[", "\\]"], "dashboards": [6160]}, {"task_id": "B-32496", "antipattern": "B", "card_id": 32496, "name": "Keywords average ranking by date (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-32496.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\."], "dashboards": [17250]}, {"task_id": "B-31641", "antipattern": "B", "card_id": 31641, "name": "Max traffic on best possible keyword rankings (monthly) (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-31641.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\."], "dashboards": []}, {"task_id": "B-18400", "antipattern": "B", "card_id": 18400, "name": "Monthly max estimated traffic on best possible keyword rankings (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-18400.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\."], "dashboards": [10157, 12993, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "B-16747", "antipattern": "B", "card_id": 16747, "name": "Paid clicks, organic clicks, no clicks by date [stack 100%] (cross search)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-16747.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11666, 11702, 11917, 11920, 12898, 12974, 13885, 17151, 17184, 18801, 21210, 23589]}, {"task_id": "B-16746", "antipattern": "B", "card_id": 16746, "name": "Paid clicks, organic clicks, no clicks by date [stack] (cross search)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-16746.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11666, 11702, 11917, 11920, 12898, 12974, 13885, 17151, 17184, 18801, 21210, 23589]}, {"task_id": "B-16739", "antipattern": "B", "card_id": 16739, "name": "Paid/SEO impressions allocation by date (cross search)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-16739.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11666, 11702, 11917, 11920, 12898, 12974, 13885, 17151, 17184, 18801, 21210, 23589]}, {"task_id": "B-16749", "antipattern": "B", "card_id": 16749, "name": "Paid/SEO impressions allocation by keyword (cross search)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-16749.sql", "regex_funcs": ["REGEXP_REPLACE", "REGEXP_LIKE"], "escaped_metachars": ["\\(", "\\)", "\\?"], "dashboards": [11666, 11702, 11917, 11920, 12898, 13885, 17151, 17184, 18801, 21210, 23589]}, {"task_id": "B-8235", "antipattern": "B", "card_id": 8235, "name": "paused accounts by checkpoint", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-8235.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\[", "\\]"], "dashboards": [6160]}, {"task_id": "B-8232", "antipattern": "B", "card_id": 8232, "name": "ratio valid checks by date", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-8232.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\[", "\\]"], "dashboards": [6160]}, {"task_id": "B-14908", "antipattern": "B", "card_id": 14908, "name": "SERP corpus details", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-14908.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\."], "dashboards": [10157, 11509, 11721, 11732, 11747, 11885, 11943, 12993, 14780, 17250, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "B-31611", "antipattern": "B", "card_id": 31611, "name": "Top keyword client : position 11 to 30, top 10 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-31611.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\.", "\\?"], "dashboards": []}, {"task_id": "B-31610", "antipattern": "B", "card_id": 31610, "name": "Top keyword client : position 4 to 10, top 10 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-31610.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\.", "\\?"], "dashboards": []}, {"task_id": "B-28554", "antipattern": "B", "card_id": 28554, "name": "Top keywords & associated competitor results", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-28554.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\."], "dashboards": [11747, 16953]}, {"task_id": "B-28869", "antipattern": "B", "card_id": 28869, "name": "Top kw client position 11 to 30 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-28869.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\.", "\\?"], "dashboards": [10157, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "B-28867", "antipattern": "B", "card_id": 28867, "name": "Top kw client position 1 to 3 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-28867.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\.", "\\?"], "dashboards": [10157, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "B-28870", "antipattern": "B", "card_id": 28870, "name": "Top kw client position 31 to 100 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-28870.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\.", "\\?"], "dashboards": [10157, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "B-28868", "antipattern": "B", "card_id": 28868, "name": "Top kw client position 4 to 10 (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-28868.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\.", "\\?"], "dashboards": [10157, 14780, 17481, 17977, 18042, 18544, 19560, 19758, 20022]}, {"task_id": "B-28125", "antipattern": "B", "card_id": 28125, "name": "Total corpus search volumes YoY (SERP)", "path": "/Users/louismonier/Dev/Pro/spark-metabase-api/migration/antipattern-tasks/B-28125.sql", "regex_funcs": ["REGEXP_REPLACE"], "escaped_metachars": ["\\."], "dashboards": [11747, 13158, 16953]}];

const ANALYSIS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['card_id', 'antipattern', 'verdict', 'confidence', 'evidence',
             'reasoning', 'fix_find', 'fix_replace', 'review_question', 'inflation_note'],
  properties: {
    card_id: { type: 'integer' },
    antipattern: { type: 'string', enum: ['A', 'B'] },
    verdict: { type: 'string', enum: ['BUG', 'OK', 'REVIEW'] },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
    evidence: { type: 'string', description: 'Exact SQL extract that is the crux (the JOIN..ON for A, the REGEXP pattern literal for B)' },
    reasoning: { type: 'string', description: 'Why this verdict, citing the SQL' },
    fix_find: { type: 'string', description: 'Exact substring to find for a copy-paste fix; empty string if not BUG' },
    fix_replace: { type: 'string', description: 'Exact replacement substring; empty string if not BUG' },
    review_question: { type: 'string', description: 'For REVIEW: the precise question a human must resolve; else empty' },
    inflation_note: { type: 'string', description: 'For A BUG: which displayed metric inflates and rough factor; else empty' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['refuted', 'corrected_verdict', 'reason'],
  properties: {
    refuted: { type: 'boolean', description: 'true if the BUG claim is WRONG / does not hold' },
    corrected_verdict: { type: 'string', enum: ['BUG', 'OK', 'REVIEW'] },
    reason: { type: 'string', description: 'Concise justification citing the SQL' },
  },
}

const TEMPLATING_NOTE =
  'The SQL is Snowflake dialect and contains Metabase templating: {{client}}, {{date}}, ' +
  '{{corpus_name}}, and optional [[ ... ]] blocks. Treat every template tag as an opaque ' +
  'filter; NEVER try to execute the SQL. Base your verdict only on the static structure.'

function analyzePromptA(t) {
  return [
    'You are a meticulous SQL auditor. Analyze EXACTLY ONE Metabase card for SQL anti-pattern A.',
    '',
    'Read the file (it starts with comment metadata, then the full native SQL): ' + t.path,
    TEMPLATING_NOTE,
    '',
    'ANTI-PATTERN A — cartesian JOIN on keyword-planner tables.',
    'The tables google_keyword_planner.kp__keyword_monthly_metrics and kp__keyword_aggregated_metrics',
    'store the SAME keyword under MULTIPLE (language, zone) pairs (one client can have corpora for',
    'France, Germany, Netherlands, UK...). Joining such a table ON the keyword column ALONE — without',
    'also matching the kp table language AND zone columns — produces a cartesian fan-out: each source',
    'row matches N kp rows, so SUM/aggregates of volume/traffic/cost inflate (x2-3) for multi-zone clients.',
    '',
    'VERDICT RUBRIC (judge the CURRENT SQL in the file):',
    '- BUG: a JOIN to a kp__ table whose ON clause matches the keyword column but matches NEITHER the kp',
    '       language NOR the kp zone column, and nothing upstream guarantees a single (language,zone) per keyword.',
    '- OK:  every kp__ JOIN matches keyword AND language AND zone (a month/date equality may also appear).',
    '       Calibration: card 15946 currently matches keyword+language+zone -> OK. Its historical BUG form',
    '       matched the keyword only.',
    '- REVIEW: genuinely ambiguous — the kp table is reached via subquery/implicit join; OR the rows feeding',
    '       the join are already reduced to one (language,zone) per keyword upstream (QUALIFY ROW_NUMBER,',
    '       GROUP BY, DISTINCT); OR an upstream filter on airtable_record_id scopes to a single corpus',
    '       (known heuristic: such a filter usually removes the cartesian risk -> lean OK, but use REVIEW',
    '       with a clear note if you are not certain). Quote the exact extract and pose the precise question.',
    '',
    'Track table aliases carefully (the kp table is usually aliased, e.g. AS kp; the source another alias).',
    'If BUG: set fix_find to the EXACT current ON-clause text copied verbatim from the file, and fix_replace',
    'to that same text with two equalities ADDED matching the kp language/zone to the source language/zone',
    '(use the real aliases you see). evidence = the exact "JOIN ... ON ..." extract. inflation_note = which',
    'displayed metric inflates (the SUM/aggregate) and a rough factor if inferable.',
    'Set card_id=' + t.card_id + ', antipattern="A".',
  ].join('\n')
}

function analyzePromptB(t) {
  return [
    'You are a meticulous SQL auditor. Analyze EXACTLY ONE Metabase card for SQL anti-pattern B.',
    '',
    'Read the file (comment metadata, then the full native SQL): ' + t.path,
    TEMPLATING_NOTE,
    '',
    'ANTI-PATTERN B — eaten regex escape in Snowflake.',
    'In Snowflake REGEXP_* / RLIKE the pattern is a SQL string literal. A SINGLE backslash before a regex',
    'metacharacter (dot, question-mark, plus, parentheses, brackets, braces, pipe, caret, dollar, star) is',
    'NOT honored as the author expects: the backslash is consumed and the metacharacter KEEPS its special',
    'meaning. The classic case: a backslash before a dot, intended to match a LITERAL dot, instead matches',
    'ANY single character. Confirmed impact: a Share-of-Voice query used backslash-dot to anchor a domain',
    'suffix and instead mis-stripped a character (e.g. domain handling for manucurist.com went wrong ->',
    'Share of Voice 118%). The correct robust form is a CHARACTER CLASS: wrap the metachar in [ ] (a literal',
    'dot becomes the two-character class open-bracket dot close-bracket).',
    '',
    'VERDICT RUBRIC (judge the CURRENT SQL):',
    '- BUG: a REGEXP pattern contains a single-backslash-escaped metacharacter CLEARLY meant as a LITERAL',
    '       (matching/stripping a real dot, parenthesis, etc. in a domain, URL, or number), so the eaten',
    '       escape changes matching and thus the card output.',
    '- OK:  the metachar is already inside a character class, OR its special meaning is actually intended,',
    '       OR the difference cannot affect this card result.',
    '- REVIEW: intent genuinely ambiguous — quote the pattern and pose the question.',
    '',
    'For each REGEXP call, extract the pattern string literal and reason about author intent. If BUG: fix_find',
    '= the exact pattern literal as written in the file; fix_replace = the corrected pattern (wrap each wrongly',
    'escaped metachar in a character class). evidence = the exact REGEXP_... call. Set card_id=' + t.card_id + ', antipattern="B".',
  ].join('\n')
}

const LENSES_A = [
  { key: 'aliases', title: 'alias & ON-clause re-read',
    body: 'Re-read the kp__ JOIN and ALL alias definitions. Verify the ON clause TRULY omits BOTH the kp ' +
          'language and the kp zone columns. Perhaps language/zone ARE matched under different aliases, via ' +
          'USING, or via an equivalent WHERE/QUALIFY predicate; or the prior auditor misread a non-kp join. ' +
          'If matching on language/zone is in fact present, refute.' },
  { key: 'upstream', title: 'upstream dedup / scoping',
    body: 'Determine the row grain feeding the kp JOIN. If an upstream CTE already reduces to exactly one ' +
          '(language,zone) per keyword (QUALIFY ROW_NUMBER, GROUP BY, DISTINCT), or the query is scoped to a ' +
          'single corpus via airtable_record_id, the cartesian fan-out does not occur on real data -> verdict ' +
          'should be OK/REVIEW. Refute if such a guard exists.' },
  { key: 'impact', title: 'does it actually inflate output',
    body: 'Check how the kp columns are consumed. If they are aggregated immune to row duplication (MAX of a ' +
          'per-keyword-constant column; or joined rows are de-duplicated by a later QUALIFY/DISTINCT/GROUP BY ' +
          'before any SUM/COUNT/AVG), the displayed metric is NOT inflated -> refute. Keep the bug only if a ' +
          'SUM/COUNT/AVG over the fanned-out rows is actually displayed.' },
]

const LENSES_B = [
  { key: 'intent', title: 'literal-intent check',
    body: 'Is the escaped metacharacter truly meant as a literal? If it is already inside a character class, ' +
          'or its regex special meaning is what the author wants, refute.' },
  { key: 'behavior', title: 'behavioral impact',
    body: 'Confirm Snowflake actually mis-handles this escape in a string-literal REGEXP pattern here AND that ' +
          'it changes the card output (not a harmless cosmetic match). If there is no observable output ' +
          'difference, refute.' },
]

function verifyPrompt(t, analysis, lens) {
  return [
    'You are an adversarial verifier. A prior auditor classified card #' + t.card_id + ' as a BUG for SQL',
    'anti-pattern ' + t.antipattern + '. Try HARD to REFUTE the claim through ONE specific lens. Conclude',
    'refuted=false only if the bug clearly survives your scrutiny.',
    '',
    'Read the SQL file: ' + t.path,
    TEMPLATING_NOTE,
    '',
    'Prior auditor evidence: ' + (analysis.evidence || '(none)'),
    'Prior auditor reasoning: ' + (analysis.reasoning || '(none)'),
    'Proposed fix find: ' + (analysis.fix_find || '(none)'),
    '',
    'LENS — ' + lens.title + ':',
    lens.body,
    '',
    'Decide: is the BUG claim wrong (refuted=true) or does it hold (refuted=false)? Give corrected_verdict',
    '(BUG if it holds; OK or REVIEW if you refute) and a concise reason citing the SQL.',
  ].join('\n')
}

log('Auditing ' + TASKS.length + ' candidate cards (' +
    TASKS.filter(t => t.antipattern === 'A').length + ' for A, ' +
    TASKS.filter(t => t.antipattern === 'B').length + ' for B)')

const results = await pipeline(
  TASKS,
  // STAGE 1 — analyze
  (t) => agent(t.antipattern === 'A' ? analyzePromptA(t) : analyzePromptB(t),
               { label: 'analyze:' + t.task_id, phase: 'Analyze', schema: ANALYSIS_SCHEMA }),
  // STAGE 2 — verify BUGs only (per item, no barrier)
  async (analysis, t) => {
    if (!analysis) {
      return { ...t, analysis: null, verifications: [], final_verdict: 'ERROR', confirmed: null }
    }
    if (analysis.verdict !== 'BUG') {
      return { ...t, analysis, verifications: [], final_verdict: analysis.verdict, confirmed: false }
    }
    const lenses = t.antipattern === 'A' ? LENSES_A : LENSES_B
    const votes = (await parallel(lenses.map(L => () =>
      agent(verifyPrompt(t, analysis, L),
            { label: 'verify:' + t.task_id + ':' + L.key, phase: 'Verify', schema: VERDICT_SCHEMA })
        .then(v => v ? { lens: L.key, ...v } : null)
    ))).filter(Boolean)
    const refutes = votes.filter(v => v.refuted).length
    const need = Math.ceil(votes.length / 2)        // majority must NOT refute
    const confirmed = votes.length > 0 && refutes < need
    const final_verdict = confirmed ? 'BUG' : 'REVIEW'  // downgrade refuted bugs to human REVIEW
    return { ...t, analysis, verifications: votes, refutes, votes_total: votes.length,
             final_verdict, confirmed }
  }
)

const clean = results.filter(Boolean)
const tally = (verd) => clean.filter(r => r.final_verdict === verd).length
log('Done. BUG=' + tally('BUG') + ' OK=' + tally('OK') + ' REVIEW=' + tally('REVIEW') + ' ERROR=' + tally('ERROR'))

return {
  summary: {
    analyzed: clean.length,
    bug: tally('BUG'), ok: tally('OK'), review: tally('REVIEW'), error: tally('ERROR'),
    a: clean.filter(r => r.antipattern === 'A').length,
    b: clean.filter(r => r.antipattern === 'B').length,
  },
  results: clean,
}
