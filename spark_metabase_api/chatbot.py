"""Natural-language dashboard authoring for Metabase.

Powered by Claude with tool-use (Anthropic SDK). Takes a natural-language
brief, inspects a live Metabase instance via read-only tools, and produces a
`spark_metabase_api.iac.CollectionSpec` you can review and apply.

This module is an optional extra:

    pip install "spark-metabase-api[chatbot]"

Typical usage:

    from spark_metabase_api import Metabase_API, iac
    from spark_metabase_api.chatbot import chat

    mb = Metabase_API(domain=..., session_id=...)
    spec = chat(mb, "Build an Acme dashboard with monthly revenue and top accounts")
    print(iac.plan(mb, spec).render())
    iac.apply(mb, spec)
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

try:  # anthropic is an optional extra
    import anthropic  # type: ignore
    from anthropic import beta_tool  # type: ignore
except ImportError:  # pragma: no cover - exercised when anthropic absent
    anthropic = None  # type: ignore
    beta_tool = None  # type: ignore

from . import iac
from .iac import CollectionSpec


SYSTEM_PROMPT = """You are a Metabase dashboard architect.

Given a natural-language brief, you inspect a live Metabase instance via
read-only tools, then emit a complete dashboard spec for the user to review
and apply. You operate on real data: never invent column names or table ids.

# Workflow (in order)
1. `list_databases` — see what databases are connected.
2. `list_tables(database_id)` — explore the relevant database.
3. `describe_table(table_id)` — get column names, types, and ids. **Always do
   this before writing SQL — never guess column names.**
4. (optional) `search_metabase(query)` and
   `find_cards_using_table(schema_name, table_name)` — check whether suitable
   cards already exist before duplicating work.
5. `propose_dashboard_spec(spec)` — call this exactly once at the end with
   the complete spec. After this tool returns, your job is done.

# Rules
- Never hallucinate column names. If `describe_table` did not confirm a name,
  it does not exist.
- Prefer native SQL queries (`type: "native"`) — simpler and more durable
  than MBQL. Match the database's SQL dialect (engine field).
- A typical dashboard has 4-12 cards. Prefer a few well-chosen cards over
  many redundant ones.
- Metabase's dashboard grid is 24 columns wide. Stack cards vertically with
  `row`/`col`/`size_x`/`size_y`. A full-width card is `size_x: 24, size_y: 8`.
- Reference cards in dashcards either by `card_id: <int>` (an existing
  Metabase card) or `card_name: "<name>"` (forward-reference to a card you
  define in the same `cards` array).

# CollectionSpec shape
```json
{
  "name": "string (collection name)",
  "description": "optional string",
  "authority_level": null,
  "collections": [],
  "cards": [
    {
      "name": "Daily revenue",
      "description": "optional",
      "definition": {
        "dataset_query": {
          "type": "native",
          "database": 1,
          "native": {"query": "SELECT day, sum(amount) FROM sales GROUP BY 1"}
        },
        "display": "line",
        "visualization_settings": {}
      }
    }
  ],
  "dashboards": [
    {
      "name": "Acme Overview",
      "description": "optional",
      "parameters": [],
      "dashcards": [
        {
          "id": -1,
          "card_name": "Daily revenue",
          "row": 0, "col": 0, "size_x": 24, "size_y": 8,
          "parameter_mappings": [],
          "visualization_settings": {}
        }
      ]
    }
  ]
}
```
"""


def _require_anthropic() -> None:
    if anthropic is None:
        raise ImportError(
            "The chatbot module requires the 'anthropic' package. "
            "Install with: pip install spark-metabase-api[chatbot]"
        )


def chat(
    metabase,
    prompt: str,
    *,
    model: str = "claude-opus-4-7",
    max_tokens: int = 8192,
    anthropic_client: Optional[Any] = None,
    verbose: bool = True,
) -> CollectionSpec:
    """Run a Claude tool-use session that produces a CollectionSpec.

    Keyword arguments:
    metabase -- a configured Metabase_API instance
    prompt -- natural-language description of the dashboard to build
    model -- Claude model id (default 'claude-opus-4-7')
    max_tokens -- per-turn output cap (default 8192)
    anthropic_client -- optional pre-built anthropic.Anthropic
    verbose -- print Claude's progress to stdout (default True)

    Returns the CollectionSpec the agent emitted via propose_dashboard_spec.
    Raises RuntimeError if the agent finished without proposing one.
    """
    _require_anthropic()
    client = anthropic_client or anthropic.Anthropic()

    # Bag captured in the closure of propose_dashboard_spec.
    proposed: Dict[str, Any] = {}

    @beta_tool
    def list_databases() -> str:
        """List the Metabase-connected databases.

        Returns a JSON array of {id, name, engine, description} entries.
        Use the engine field to know which SQL dialect to write."""
        res = metabase.get("/api/database/")
        if isinstance(res, dict):
            res = res.get("data", [])
        items = [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "engine": d.get("engine"),
                "description": d.get("description"),
            }
            for d in (res or [])
        ]
        return json.dumps(items, ensure_ascii=False)

    @beta_tool
    def list_tables(database_id: int) -> str:
        """List tables for a Metabase database.

        Args:
            database_id: id of the database (from list_databases)

        Returns a JSON array of {id, name, schema, display_name, description}."""
        info = metabase.get(
            "/api/database/{}".format(database_id),
            params={"include": "tables"},
        ) or {}
        tables = info.get("tables") or []
        items = [
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "schema": t.get("schema"),
                "display_name": t.get("display_name"),
                "description": t.get("description"),
            }
            for t in tables
        ]
        return json.dumps(items, ensure_ascii=False)

    @beta_tool
    def describe_table(table_id: int) -> str:
        """Get the columns of a Metabase table.

        Args:
            table_id: id of the table (from list_tables)

        Returns JSON {table: {...}, fields: [{id, name, base_type,
        semantic_type, description}, ...]}. Use the exact column names from
        this response in any SQL you write — never guess."""
        meta = metabase.get_table_metadata(table_id=table_id) or {}
        fields = [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "base_type": f.get("base_type"),
                "semantic_type": f.get("semantic_type"),
                "description": f.get("description"),
            }
            for f in (meta.get("fields") or [])
        ]
        return json.dumps(
            {
                "table": {
                    "id": meta.get("id"),
                    "name": meta.get("name"),
                    "schema": meta.get("schema"),
                    "description": meta.get("description"),
                    "db_id": meta.get("db_id"),
                },
                "fields": fields,
            },
            ensure_ascii=False,
        )

    @beta_tool
    def search_metabase(query: str, item_type: Optional[str] = None) -> str:
        """Search existing Metabase items by name.

        Args:
            query: search string
            item_type: optional filter ('card', 'dashboard', 'collection',
                       'table', 'segment', 'metric')

        Returns a JSON array of {id, name, model, collection_id} entries."""
        results = metabase.search(query, item_type=item_type) or []
        return json.dumps(
            [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "model": r.get("model"),
                    "collection_id": r.get("collection_id"),
                }
                for r in results
            ],
            ensure_ascii=False,
        )

    @beta_tool
    def find_cards_using_table(schema_name: str, table_name: str) -> str:
        """Find existing native-SQL cards that reference schema.table.

        Useful before authoring new SQL — if a card already provides what
        the brief asks for, reuse it instead of duplicating it.

        Args:
            schema_name: database schema name
            table_name: table name

        Returns a JSON array of {id, name} for matching cards."""
        infos = metabase.find_cards_via_db_object(
            schema_name=schema_name, table_name=table_name,
        ) or []
        return json.dumps(infos, ensure_ascii=False)

    @beta_tool
    def propose_dashboard_spec(spec: Dict[str, Any]) -> str:
        """Emit the final CollectionSpec. Call this exactly once.

        Args:
            spec: a dict matching the CollectionSpec shape from the system
                  prompt. Must include 'name'. Should include at least one
                  card or dashboard.

        Returns 'ok' on success, an error string otherwise."""
        if not isinstance(spec, dict):
            return "Error: spec must be a JSON object."
        if not spec.get("name"):
            return "Error: spec must include a 'name' field."
        if not (spec.get("cards") or spec.get("dashboards") or spec.get("collections")):
            return ("Error: spec must include at least one card, dashboard, "
                    "or nested collection — empty specs are not useful.")
        proposed.clear()
        proposed.update(spec)
        return "ok"

    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": "xhigh"},
        cache_control={"type": "ephemeral"},
        system=SYSTEM_PROMPT,
        tools=[
            list_databases,
            list_tables,
            describe_table,
            search_metabase,
            find_cards_using_table,
            propose_dashboard_spec,
        ],
        messages=[{"role": "user", "content": prompt}],
    )

    for message in runner:
        if not verbose:
            continue
        for block in message.content:
            if getattr(block, "type", None) == "text" and getattr(block, "text", ""):
                print(block.text)
            elif getattr(block, "type", None) == "tool_use":
                args = (block.input or {}) if hasattr(block, "input") else {}
                summary = ", ".join(
                    "{}={}".format(k, json.dumps(v, ensure_ascii=False)[:80])
                    for k, v in args.items()
                )
                print("    → {}({})".format(block.name, summary))

    if not proposed:
        raise RuntimeError(
            "The agent finished without calling propose_dashboard_spec. "
            "Try a more concrete brief, or re-run with a higher max_tokens."
        )

    return iac._spec_from_dict(proposed)
