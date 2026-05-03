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
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

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


def _build_tools(
    metabase,
    on_propose: Callable[[Dict[str, Any]], None],
    on_tool_call: Optional[Callable[[str, Dict[str, Any], str], None]] = None,
) -> List[Any]:
    """Build the agent's read-only inspection tools + the propose-spec sink.

    `on_propose(spec)` is called when the agent emits the final spec.
    `on_tool_call(name, input, result)` (optional) is called after every
    inspection tool returns, for UI logging.
    """

    def _record(name: str, input: Dict[str, Any], result: str) -> str:
        if on_tool_call is not None:
            on_tool_call(name, input, result)
        return result

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
        return _record("list_databases", {}, json.dumps(items, ensure_ascii=False))

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
        return _record(
            "list_tables",
            {"database_id": database_id},
            json.dumps(items, ensure_ascii=False),
        )

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
        payload = {
            "table": {
                "id": meta.get("id"),
                "name": meta.get("name"),
                "schema": meta.get("schema"),
                "description": meta.get("description"),
                "db_id": meta.get("db_id"),
            },
            "fields": fields,
        }
        return _record(
            "describe_table",
            {"table_id": table_id},
            json.dumps(payload, ensure_ascii=False),
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
        items = [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "model": r.get("model"),
                "collection_id": r.get("collection_id"),
            }
            for r in results
        ]
        return _record(
            "search_metabase",
            {"query": query, "item_type": item_type},
            json.dumps(items, ensure_ascii=False),
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
        return _record(
            "find_cards_using_table",
            {"schema_name": schema_name, "table_name": table_name},
            json.dumps(infos, ensure_ascii=False),
        )

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
        on_propose(spec)
        return "ok"

    return [
        list_databases,
        list_tables,
        describe_table,
        search_metabase,
        find_cards_using_table,
        propose_dashboard_spec,
    ]


# Event tuple types yielded by `stream`. Kept as plain tuples so callers don't
# need to import any class — easy to pattern-match in a UI loop.
ChatEvent = Tuple[str, Any]
#   ("text",        str)              — assistant prose
#   ("tool_call",   {"name", "input"}) — agent invoked a tool
#   ("tool_result", {"name", "input", "result"}) — tool returned (truncated str)
#   ("proposed",    dict)              — final CollectionSpec dict (last event)


def stream(
    metabase,
    prompt: str,
    *,
    model: str = "claude-opus-4-7",
    max_tokens: int = 8192,
    anthropic_client: Optional[Any] = None,
) -> Iterator[ChatEvent]:
    """Run the agent and yield events as they happen.

    Use this to drive a UI that updates as Claude works (e.g. Streamlit).
    For a blocking call that just returns the final spec, use ``chat()``.
    """
    _require_anthropic()
    client = anthropic_client or anthropic.Anthropic()

    proposed: Dict[str, Any] = {}
    pending_tool_results: List[Dict[str, Any]] = []

    def _on_propose(spec: Dict[str, Any]) -> None:
        proposed.clear()
        proposed.update(spec)

    def _on_tool_call(name: str, input: Dict[str, Any], result: str) -> None:
        # Truncate large results so the UI stays readable; the agent still
        # sees the full result via the tool runner.
        snippet = result if len(result) <= 4000 else result[:4000] + "...[truncated]"
        pending_tool_results.append({"name": name, "input": input, "result": snippet})

    tools = _build_tools(metabase, on_propose=_on_propose, on_tool_call=_on_tool_call)

    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": "xhigh"},
        cache_control={"type": "ephemeral"},
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=[{"role": "user", "content": prompt}],
    )

    for message in runner:
        # Drain results from tool calls executed since the previous message.
        while pending_tool_results:
            yield ("tool_result", pending_tool_results.pop(0))
        for block in message.content:
            btype = getattr(block, "type", None)
            if btype == "text" and getattr(block, "text", ""):
                yield ("text", block.text)
            elif btype == "tool_use":
                yield ("tool_call", {
                    "name": block.name,
                    "input": dict(block.input or {}),
                })

    while pending_tool_results:
        yield ("tool_result", pending_tool_results.pop(0))

    if proposed:
        yield ("proposed", dict(proposed))


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

    Blocking convenience wrapper around ``stream()``. Returns the final spec.

    Keyword arguments:
    metabase -- a configured Metabase_API instance
    prompt -- natural-language description of the dashboard to build
    model -- Claude model id (default 'claude-opus-4-7')
    max_tokens -- per-turn output cap (default 8192)
    anthropic_client -- optional pre-built anthropic.Anthropic
    verbose -- print Claude's progress to stdout (default True)

    Raises RuntimeError if the agent finished without proposing a spec.
    """
    spec_dict: Optional[Dict[str, Any]] = None
    for event_type, payload in stream(
        metabase, prompt,
        model=model, max_tokens=max_tokens,
        anthropic_client=anthropic_client,
    ):
        if event_type == "proposed":
            spec_dict = payload
        elif verbose and event_type == "text":
            print(payload)
        elif verbose and event_type == "tool_call":
            args = ", ".join(
                "{}={}".format(k, json.dumps(v, ensure_ascii=False)[:80])
                for k, v in payload["input"].items()
            )
            print("    → {}({})".format(payload["name"], args))

    if spec_dict is None:
        raise RuntimeError(
            "The agent finished without calling propose_dashboard_spec. "
            "Try a more concrete brief, or re-run with a higher max_tokens."
        )

    return iac.spec_from_dict(spec_dict)
