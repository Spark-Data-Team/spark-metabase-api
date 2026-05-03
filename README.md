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

## Acknowledgements

- [Metabase API documentation](https://www.metabase.com/docs/latest/api-documentation)
- [Metabase API changelog](https://www.metabase.com/docs/latest/developers-guide/api-changelog)
- Inspired from [metabase_api_python](https://github.com/vvaezian/metabase_api_python)
