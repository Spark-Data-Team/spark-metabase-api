## 0.1.1 (2023-12-15)
## 0.1.2 (2023-12-18)
## 0.1.3 (2023-12-18)
## 0.1.4 (2023-12-18)
## 0.1.5 (2024-01-18)
## 0.1.6 (2024-01-23)
* Add a new function *rescan_object_values*
## 0.1.7 (2024-01-23)
* Add a new help function *find_cards_via_db_object*
## 0.1.8 (2024-03-07)
* Upgrade for new MB API dashboard + fix small bugs
## 0.1.9 (2024-04-26)
* Add a new help function *get_user_coll_id*
## 0.1.10 (2024-04-29)
* Add a new argument (remove_default) to *restrict_filter_with_card_values* method
## 0.1.11 (2024-04-29)
* Add helper function *get_user_coll_id* to main
## 0.1.12 (2024-04-29)
* Fix small bugs
## 0.1.13 (2024-10-29)
* Add 2 functions *rescan_db_field_values* & *rescan_db_sync_schemas* to main
## 0.1.14 (2026-05-08)
* Fix `__init__`: `password` argument is now stored, dead `getpass` branch removed (raises `ValueError` if neither email/password nor session_id is provided)
* Fix `clone_card`: typo where `target_table_id` was reassigned to `source_table_id`
* Remove unsafe `eval()` from `clone_card` and `create_card` (could break on names containing quotes/unicode); MBQL field-id remap now done via tree walk
* `clone_card`: fetch with `?legacy-mbql=true` to keep MBQL 4 shapes on Metabase 0.57+
* Fix `check_collection`: `NameError` on the duplicate-collection branch
* Fix `copy_dashboard`: `rstrip(' - Duplicate')` (which strips a *set* of characters) replaced by a real suffix removal
* `restrict_collection_access`: now writes 'none' for groups whose entry is missing in the graph (Metabase 0.56.13 stopped returning explicit 'none' values)
* `restrict_filter_with_card_values`: `column_base_type` configurable, forced uppercase opt-out via `preserve_column_case=True`, doc typo fixed
* `add_card_to_dashboard`: legacy `POST /api/dashboard/:id/cards` falls back to `PUT /api/dashboard/:id` with full `dashcards` array on newer Metabase; returns `None` consistently
* `get_dashboard_question_ids`: handles both new `dashcards` and legacy `ordered_cards` shapes
* `create_collection`: `color` is sent for older Metabase but transparently dropped on a 400 from newer Metabase
* Hardened `_rest_methods`: shared `requests.Session`, default 30s timeout (override via `timeout=None`), network errors during session validation no longer raise
* `validate_session` and `is_session_valid` deduplicated