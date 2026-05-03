[![GPLv3 License](https://img.shields.io/badge/License-GPL%20v3-yellow.svg)](https://opensource.org/licenses/)

# Spark Metabase API

A Python wrapper for the Metabase API, developed by the [Spark Tech team](https://www.spark.do/) ⭐️

## Installation

```bash
pip install spark-metabase-api
# Optional YAML support for the Infrastructure-as-Code module:
pip install "spark-metabase-api[iac]"
```

## Quick start

```python
from spark_metabase_api import Metabase_API

mb = Metabase_API(
    domain="https://metabase.example.com",
    email="me@example.com",
    password="hunter2",
)

mb.copy_dashboard(source_dashboard_id=42, destination_collection_name="Acme")
```

## Infrastructure-as-Code

Define a Metabase collection tree in YAML, version it in git, and apply it
idempotently with a Terraform-style diff.

```bash
# Pull the live state for an existing collection
spark-metabase --domain "$MB_URL" --email "$MB_USER" --password "$MB_PASS" \
    export "Acme Customer" specs/acme.yaml

# Show what would change after editing the spec
spark-metabase plan specs/acme.yaml

# Apply (with confirmation prompt unless --yes)
spark-metabase apply specs/acme.yaml
```

Example spec:

```yaml
name: "Acme Customer"
description: "Customer-facing dashboards"
authority_level: official
collections:
  - name: "Questions"
    cards:
      - name: "Daily revenue"
        definition:
          dataset_query:
            type: native
            database: 2
            native:
              query: "SELECT day, sum(amount) FROM sales GROUP BY 1"
          display: line
          visualization_settings: {}
dashboards:
  - name: "Acme Dashboard"
    description: "Top-level KPIs"
    parameters: []
    dashcards: []  # populated automatically by `export`
```

The Python API is also exposed:

```python
from spark_metabase_api import Metabase_API, iac

mb = Metabase_API(domain=..., session_id=...)

# Export to YAML
spec = iac.export(mb, "Acme Customer")
iac.dump(spec, "specs/acme.yaml")

# Edit the file in git, then in CI:
spec = iac.load("specs/acme.yaml")
print(iac.plan(mb, spec).render())
iac.apply(mb, spec)
```

### Natural keys & renames

Items are identified by `(parent_path, kind, name)` within the spec. Renaming
an item is therefore a destructive change (delete + create). To bind a spec
entry to a specific live item across renames, set `entity_id` (Metabase's
stable nanoid, available since v0.46) on the entry.

### Forward references in dashcards

A dashcard can reference a card created by the same spec via
`card_name: "<name>"` instead of `card_id`. The applier looks the name up in
the cards present (or just created) inside the same collection and rewrites
the dashcard with the real id.

## Natural-language dashboard authoring

```bash
pip install "spark-metabase-api[chatbot]"
```

Describe what you want; Claude inspects the live Metabase via read-only tools
(`list_databases`, `list_tables`, `describe_table`, `search_metabase`,
`find_cards_using_table`) and emits a `CollectionSpec`:

```python
from spark_metabase_api import Metabase_API, iac
from spark_metabase_api.chatbot import chat

mb = Metabase_API(domain=..., session_id=...)
spec = chat(mb, "Build an Acme dashboard with monthly revenue and top accounts")
print(iac.plan(mb, spec).render())
iac.apply(mb, spec)
```

For UIs (Streamlit, Slack, etc.) use the streaming generator:

```python
from spark_metabase_api.chatbot import stream

for event_type, payload in stream(mb, "..."):
    if event_type == "text":          render_assistant_text(payload)
    elif event_type == "tool_call":   render_tool_call(payload)      # {name, input}
    elif event_type == "tool_result": render_tool_result(payload)    # {name, input, result}
    elif event_type == "proposed":    save_spec(payload)             # CollectionSpec dict
```

Powered by Claude Opus 4.7 with adaptive thinking; the model needs an
`ANTHROPIC_API_KEY` environment variable.

### Streamlit frontend

A single-file Streamlit app that wires the chatbot to a chat UI with live
tool-call rendering, plan diffing, and an Apply button.

```bash
pip install "spark-metabase-api[streamlit]"
streamlit run streamlit_app.py
```

The app:
- collects Metabase + Anthropic credentials in the sidebar,
- streams Claude's progress (text, tool calls, expandable tool results) as
  the agent works,
- renders the proposed spec as YAML,
- previews the diff via `iac.plan` and applies it on demand.

## Integration tests

A standalone script exercises the package against a live Metabase instance,
in four phases with a sandboxed write area that's archived on exit:

```bash
python tests/integration_test.py \
    --domain "$MB_URL" --email "$MB_USER" --password "$MB_PASS" \
    --collection "My Reports" \
    --source-dashboard-id 42 \
    --chatbot
```

Phase 1 is fully read-only. Phase 2 creates a uniquely-named throwaway
collection, applies a tiny spec, exercises `add_card_to_dashboard` and
`copy_dashboard(deepcopy=True)`, then archives the sandbox in a `finally`
block (use `--keep-sandbox` to keep it around for manual inspection).
Phase 3 (opt-in via `--chatbot`) runs the Claude agent but does *not*
apply the spec it proposes.

## Acknowledgements

- [Metabase API documentation](https://www.metabase.com/docs/latest/api-documentation)
- [Metabase API changelog](https://www.metabase.com/docs/latest/developers-guide/api-changelog)
- Inspired from [metabase_api_python](https://github.com/vvaezian/metabase_api_python)
