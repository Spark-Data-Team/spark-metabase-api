"""
Infrastructure-as-Code for Metabase.

Define a tree of collections / dashboards / cards in YAML (or JSON) and apply
it idempotently to a Metabase instance, with a Terraform-style diff first.

Natural keys: items are identified by (parent_path, kind, name). Renames are
therefore destructive (delete + create); use the optional `entity_id` field
to bind a spec entry to an existing item across a rename.

Public surface:
    Spec, CollectionSpec, DashboardSpec, CardSpec
    load(path) -> Spec
    dump(spec, path) -> None
    export(client, root_collection) -> CollectionSpec
    plan(client, spec) -> Plan
    apply(client, spec, dry_run=False) -> Plan
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, Union

try:  # pyyaml is an optional extra
    import yaml as _yaml  # type: ignore
except ImportError:  # pragma: no cover - exercised when pyyaml absent
    _yaml = None


# ---------------------------------------------------------------------------
# Spec data model
# ---------------------------------------------------------------------------


@dataclass
class CardSpec:
    """A Metabase card (question or model). `definition` is the opaque payload
    sent to POST/PUT /api/card/, minus the collection_id (resolved on apply)."""

    name: str
    definition: Dict[str, Any] = field(default_factory=dict)
    entity_id: Optional[str] = None
    description: Optional[str] = None

    @property
    def kind(self) -> str:
        return "card"


@dataclass
class DashboardSpec:
    """A Metabase dashboard.

    `dashcards` is preserved verbatim and re-applied as-is. Card ids inside
    dashcards are NOT rewritten in this version; if a dashboard references a
    card created by the same spec run, set the dashcard's `card_id` manually
    after the first apply (or wait for a future release that resolves
    cross-references)."""

    name: str
    description: Optional[str] = None
    dashcards: List[Dict[str, Any]] = field(default_factory=list)
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    entity_id: Optional[str] = None

    @property
    def kind(self) -> str:
        return "dashboard"


@dataclass
class CollectionSpec:
    """A Metabase collection. Children are nested; the parent of the root is
    resolved on apply via parent_path or parent_id."""

    name: str
    description: Optional[str] = None
    authority_level: Optional[str] = None  # 'official' or None
    entity_id: Optional[str] = None
    parent_path: Optional[str] = None  # absolute path of the parent at apply
    collections: List["CollectionSpec"] = field(default_factory=list)
    dashboards: List[DashboardSpec] = field(default_factory=list)
    cards: List[CardSpec] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return "collection"


# Top-level Spec is just a CollectionSpec with parent_path defaulting to "/".
Spec = CollectionSpec


# ---------------------------------------------------------------------------
# (De)serialization
# ---------------------------------------------------------------------------


def _spec_to_dict(spec: CollectionSpec) -> Dict[str, Any]:
    return asdict(spec)


def _spec_from_dict(data: Dict[str, Any]) -> CollectionSpec:
    children = [_spec_from_dict(c) for c in data.get("collections") or []]
    dashboards = [
        DashboardSpec(
            name=d["name"],
            description=d.get("description"),
            dashcards=d.get("dashcards") or [],
            parameters=d.get("parameters") or [],
            entity_id=d.get("entity_id"),
        )
        for d in data.get("dashboards") or []
    ]
    cards = [
        CardSpec(
            name=c["name"],
            definition=c.get("definition") or {},
            entity_id=c.get("entity_id"),
            description=c.get("description"),
        )
        for c in data.get("cards") or []
    ]
    return CollectionSpec(
        name=data["name"],
        description=data.get("description"),
        authority_level=data.get("authority_level"),
        entity_id=data.get("entity_id"),
        parent_path=data.get("parent_path"),
        collections=children,
        dashboards=dashboards,
        cards=cards,
    )


def load(path: str) -> CollectionSpec:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith((".yaml", ".yml")):
        if _yaml is None:
            raise ImportError(
                "PyYAML is required to load YAML specs. "
                "Install with: pip install spark-metabase-api[iac]"
            )
        data = _yaml.safe_load(text)
    else:
        data = json.loads(text)
    return _spec_from_dict(data)


def dump(spec: CollectionSpec, path: str) -> None:
    data = _spec_to_dict(spec)
    if path.endswith((".yaml", ".yml")):
        if _yaml is None:
            raise ImportError(
                "PyYAML is required to dump YAML specs. "
                "Install with: pip install spark-metabase-api[iac]"
            )
        text = _yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


def _collection_items(client, collection_id: Union[int, str, None]) -> List[Dict[str, Any]]:
    # The synthetic Root collection is addressed as 'root' by the Metabase API.
    cid = "root" if collection_id is None or collection_id == "root" else collection_id
    res = client.get("/api/collection/{}/items".format(cid))
    if isinstance(res, dict):  # paginated shape introduced in 0.40
        return res.get("data", [])
    return res or []


def export(client, root_collection: Union[int, str]) -> CollectionSpec:
    """Pull a collection tree from a live Metabase into a Spec.

    `root_collection` is either a collection id, the literal string 'root', or
    a collection name (resolved via get_item_id).
    """
    if isinstance(root_collection, str) and root_collection.lower() != "root":
        try:
            root_collection = int(root_collection)
        except ValueError:
            root_collection = client.get_item_id("collection", root_collection)
    return _export_collection(client, root_collection)


def _export_collection(client, collection_id: Union[int, str, None]) -> CollectionSpec:
    is_root = collection_id is None or collection_id == "root"
    if is_root:
        info: Dict[str, Any] = {
            "name": "Root", "description": None,
            "authority_level": None, "entity_id": None,
        }
    else:
        info = client.get("/api/collection/{}".format(collection_id)) or {}
        if not info:
            raise RuntimeError(
                "Failed to fetch collection {} — aborting export to avoid "
                "silently producing an incomplete spec.".format(collection_id)
            )

    spec = CollectionSpec(
        name=info.get("name") or "Root",
        description=info.get("description"),
        authority_level=info.get("authority_level"),
        entity_id=info.get("entity_id"),
    )
    for item in _collection_items(client, collection_id):
        if item.get("archived"):
            continue
        model = item.get("model")
        if model == "collection":
            spec.collections.append(_export_collection(client, item["id"]))
        elif model == "dashboard":
            spec.dashboards.append(_export_dashboard(client, item["id"]))
        elif model == "card":
            spec.cards.append(_export_card(client, item["id"]))
        # other models (pulse, metric, ...) are ignored on purpose
    return spec


_CARD_OPAQUE_KEYS = (
    "dataset_query", "display", "visualization_settings", "type",
    "parameters", "parameter_mappings", "result_metadata",
    "cache_ttl", "archived",
)


def _export_card(client, card_id: int) -> CardSpec:
    # MBQL 4 shapes are easier to round-trip through the API on Metabase 0.57+
    info = client.get("/api/card/{}".format(card_id), params={"legacy-mbql": "true"}) or {}
    return CardSpec(
        name=info.get("name") or "",
        description=info.get("description"),
        entity_id=info.get("entity_id"),
        definition={k: info.get(k) for k in _CARD_OPAQUE_KEYS if k in info},
    )


def _export_dashboard(client, dashboard_id: int) -> DashboardSpec:
    info = client.get("/api/dashboard/{}".format(dashboard_id)) or {}
    dashcards = info.get("dashcards") or info.get("ordered_cards") or []
    return DashboardSpec(
        name=info.get("name") or "",
        description=info.get("description"),
        entity_id=info.get("entity_id"),
        parameters=info.get("parameters") or [],
        dashcards=dashcards,
    )


# ---------------------------------------------------------------------------
# Plan / Apply
# ---------------------------------------------------------------------------


@dataclass
class Action:
    op: str  # 'create' | 'update' | 'skip'
    kind: str  # 'collection' | 'dashboard' | 'card'
    path: str
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    existing_id: Optional[int] = None


@dataclass
class Plan:
    actions: List[Action] = field(default_factory=list)

    def summary(self) -> str:
        counts: Dict[str, int] = {}
        for a in self.actions:
            counts[a.op] = counts.get(a.op, 0) + 1
        parts = ["{} {}".format(v, k) for k, v in sorted(counts.items())]
        return ", ".join(parts) or "no changes"

    def render(self) -> str:
        glyph = {"create": "+", "update": "~", "skip": "="}
        lines = []
        for a in self.actions:
            lines.append("  {}  {:<10} {}{}".format(
                glyph.get(a.op, "?"), a.kind, a.path,
                "  [{}]".format(a.reason) if a.reason else "",
            ))
        return "\n".join(lines) + ("\n" if lines else "") + "Plan: " + self.summary()


def _join(parent_path: str, name: str) -> str:
    if parent_path == "/" or parent_path == "":
        return "/" + name
    return parent_path.rstrip("/") + "/" + name


def _index_collection_children(client, collection_id) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in _collection_items(client, collection_id):
        if item.get("archived"):
            continue
        model = item.get("model")
        if model in ("collection", "dashboard", "card"):
            out[(model, item["name"])] = item
    return out


def _significant_card_diff(local: CardSpec, remote: Dict[str, Any]) -> List[str]:
    diffs = []
    if (local.description or None) != (remote.get("description") or None):
        diffs.append("description")
    for key in ("dataset_query", "display", "visualization_settings", "type"):
        if key in local.definition and local.definition[key] != remote.get(key):
            diffs.append(key)
    return diffs


def _significant_dashboard_diff(
    local: DashboardSpec,
    remote: Dict[str, Any],
    resolved_dashcards: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    diffs = []
    if (local.description or None) != (remote.get("description") or None):
        diffs.append("description")
    if (local.parameters or []) != (remote.get("parameters") or []):
        diffs.append("parameters")
    if resolved_dashcards is None:
        # Spec carries card_name forward references that can't be resolved
        # yet (cards not created at plan time). Force an update.
        diffs.append("dashcards")
    else:
        remote_dc = remote.get("dashcards") or remote.get("ordered_cards") or []
        if resolved_dashcards != remote_dc:
            diffs.append("dashcards")
    return diffs


def _significant_collection_diff(local: CollectionSpec, remote: Dict[str, Any]) -> List[str]:
    diffs = []
    if (local.description or None) != (remote.get("description") or None):
        diffs.append("description")
    if (local.authority_level or None) != (remote.get("authority_level") or None):
        diffs.append("authority_level")
    return diffs


def plan(client, spec: CollectionSpec, parent_id: Optional[int] = None) -> Plan:
    """Compute a plan to make Metabase match the spec.

    The plan is read-only; pass the same arguments to `apply` to execute it.

    Keyword arguments:
    client -- a configured Metabase_API instance
    spec -- the root CollectionSpec to apply
    parent_id -- id of the Metabase collection that should host `spec`. None
                 means the root collection.
    """
    p = Plan()
    _plan_collection(client, spec, parent_id, parent_path="", p=p)
    return p


def _plan_collection(client, spec: CollectionSpec, parent_id: Optional[int],
                     parent_path: str, p: Plan) -> None:
    path = _join(parent_path or "/", spec.name)

    # Find existing collection at this path
    existing_id = None
    if parent_id is None and spec.name.lower() == "root":
        existing_id = "root"
        existing = {"name": "Root"}
    else:
        siblings = _index_collection_children(client, parent_id if parent_id is not None else "root")
        match = siblings.get(("collection", spec.name))
        if match:
            existing_id = match["id"]
            existing = client.get("/api/collection/{}".format(existing_id)) or match
        else:
            existing = None

    if existing is None:
        p.actions.append(Action(
            op="create", kind="collection", path=path,
            payload={
                "name": spec.name,
                "description": spec.description,
                "authority_level": spec.authority_level,
                "parent_id": parent_id,
            },
        ))
        # Children will all be created under the (future) collection. We still
        # plan their creation so the diff is informative.
        for child in spec.collections:
            _plan_collection(client, child, parent_id=None, parent_path=path, p=p)
        for d in spec.dashboards:
            p.actions.append(Action(op="create", kind="dashboard", path=_join(path, d.name)))
        for c in spec.cards:
            p.actions.append(Action(op="create", kind="card", path=_join(path, c.name)))
        return

    diffs = _significant_collection_diff(spec, existing)
    p.actions.append(Action(
        op="update" if diffs else "skip",
        kind="collection", path=path,
        reason=",".join(diffs),
        existing_id=existing_id if isinstance(existing_id, int) else None,
        payload={
            "description": spec.description,
            "authority_level": spec.authority_level,
        } if diffs else {},
    ))

    children = _index_collection_children(client, existing_id) if existing_id != "root" else \
        _index_collection_children(client, "root")

    for child in spec.collections:
        _plan_collection(
            client, child,
            parent_id=existing_id if isinstance(existing_id, int) else None,
            parent_path=path, p=p,
        )

    # name_to_id for cards in this collection — also used to resolve
    # card_name forward references in spec dashcards before we diff them
    # against the live state (which carries card_id).
    existing_name_to_id = {
        name: item["id"]
        for (kind, name), item in children.items()
        if kind == "card"
    }

    for d in spec.dashboards:
        match = children.get(("dashboard", d.name))
        d_path = _join(path, d.name)
        if not match:
            p.actions.append(Action(op="create", kind="dashboard", path=d_path))
            continue
        remote = client.get("/api/dashboard/{}".format(match["id"])) or match
        try:
            resolved_dashcards = _resolve_card_names(d.dashcards, existing_name_to_id)
        except ValueError:
            # The spec references a card_name that doesn't exist yet (will be
            # created in the same apply). Treat as needing an update; the
            # executor will resolve it once the card is materialised.
            resolved_dashcards = None
        diffs = _significant_dashboard_diff(d, remote, resolved_dashcards)
        p.actions.append(Action(
            op="update" if diffs else "skip",
            kind="dashboard", path=d_path,
            reason=",".join(diffs),
            existing_id=match["id"],
        ))

    for c in spec.cards:
        match = children.get(("card", c.name))
        c_path = _join(path, c.name)
        if not match:
            p.actions.append(Action(op="create", kind="card", path=c_path))
            continue
        remote = client.get("/api/card/{}".format(match["id"]),
                            params={"legacy-mbql": "true"}) or match
        diffs = _significant_card_diff(c, remote)
        p.actions.append(Action(
            op="update" if diffs else "skip",
            kind="card", path=c_path,
            reason=",".join(diffs),
            existing_id=match["id"],
        ))


# ---------------------------------------------------------------------------
# Applier
# ---------------------------------------------------------------------------


def apply(client, spec: CollectionSpec, parent_id: Optional[int] = None,
          dry_run: bool = False) -> Plan:
    """Apply the spec to Metabase so the live state matches the spec.

    Returns the executed plan. With dry_run=True nothing is written and the
    returned plan is exactly what `plan(client, spec, parent_id)` would return.
    """
    p = plan(client, spec, parent_id=parent_id)
    if dry_run:
        return p
    by_path = {a.path: a for a in p.actions}
    _execute_collection(client, spec, parent_id, parent_path="", by_path=by_path)
    return p


def _resolve_card_names(dashcards: List[Dict[str, Any]],
                        name_to_id: Dict[str, int]) -> List[Dict[str, Any]]:
    """Replace `card_name` forward references in dashcards with `card_id`.

    Dashcards that already have a `card_id` are left alone. A dashcard with
    `card_name` set and no `card_id` is rewritten to point at the live id;
    if the name doesn't match any card created or found in the same scope,
    a ValueError is raised with the offending name.
    """
    out = []
    for dc in dashcards or []:
        if dc.get("card_name") and not dc.get("card_id"):
            cid = name_to_id.get(dc["card_name"])
            if cid is None:
                raise ValueError(
                    "Dashcard references card_name {!r}, but no card with "
                    "that name was created or found in the same collection."
                    .format(dc["card_name"])
                )
            resolved = dict(dc)
            resolved["card_id"] = cid
            resolved.pop("card_name")
            out.append(resolved)
        else:
            out.append(dc)
    return out


def _execute_collection(client, spec: CollectionSpec, parent_id: Optional[int],
                        parent_path: str, by_path: Dict[str, Action]) -> int:
    path = _join(parent_path or "/", spec.name)
    action = by_path.get(path)
    if action is None:
        # Defensive: if the plan lost track, skip silently.
        return 0

    if action.op == "create":
        new = client.create_collection(
            collection_name=spec.name,
            parent_collection_id=parent_id,
            parent_collection_name="Root" if parent_id is None else None,
            official=(spec.authority_level == "official"),
            return_results=True,
        )
        collection_id = new["id"] if isinstance(new, dict) else new
        if not collection_id:
            raise RuntimeError(
                "Failed to create collection {!r} under parent {}: aborting "
                "the apply to avoid orphaning its children at the root."
                .format(spec.name, parent_id)
            )
        if spec.description:
            client.put("/api/collection/{}".format(collection_id),
                       json={"description": spec.description})
    elif action.op == "update" and action.existing_id is not None:
        collection_id = action.existing_id
        client.put("/api/collection/{}".format(collection_id), json=action.payload)
    else:
        collection_id = action.existing_id  # may be None for the synthetic Root

    # Walk children
    for child in spec.collections:
        _execute_collection(client, child, collection_id, path, by_path)

    # Track card names → ids in this collection so dashcards can reference
    # cards by name. Pre-populate with cards that already exist (skip ops).
    name_to_id: Dict[str, int] = {}
    if collection_id and collection_id != "root":
        for (kind, name), item in _index_collection_children(client, collection_id).items():
            if kind == "card":
                name_to_id[name] = item["id"]

    # Cards must be processed before dashboards so name_to_id is populated.
    for c in spec.cards:
        c_path = _join(path, c.name)
        c_action = by_path.get(c_path)
        if c_action is None:
            continue
        if c_action.op == "create":
            payload = dict(c.definition)
            payload.update({
                "name": c.name,
                "collection_id": collection_id,
                "description": c.description,
            })
            res = client.create_card(custom_json=payload, return_card=True)
            if not isinstance(res, dict) or "id" not in res:
                raise RuntimeError(
                    "Failed to create card {!r} in collection {}: {}"
                    .format(c.name, collection_id, res)
                )
            name_to_id[c.name] = res["id"]
        elif c_action.op == "update" and c_action.existing_id is not None:
            payload = dict(c.definition)
            payload["description"] = c.description
            client.put("/api/card/{}".format(c_action.existing_id), json=payload)
            name_to_id[c.name] = c_action.existing_id
        elif c_action.existing_id is not None:  # skip
            name_to_id[c.name] = c_action.existing_id

    for d in spec.dashboards:
        d_path = _join(path, d.name)
        d_action = by_path.get(d_path)
        if d_action is None:
            continue
        dashcards = _resolve_card_names(d.dashcards, name_to_id)
        if d_action.op == "create":
            payload = {
                "name": d.name,
                "description": d.description,
                "collection_id": collection_id,
                "parameters": d.parameters or [],
            }
            res = client.post("/api/dashboard/", json=payload)
            if res and dashcards:
                client.put(
                    "/api/dashboard/{}".format(res["id"]),
                    json={"dashcards": dashcards, "parameters": d.parameters or []},
                )
        elif d_action.op == "update" and d_action.existing_id is not None:
            client.put(
                "/api/dashboard/{}".format(d_action.existing_id),
                json={
                    "description": d.description,
                    "parameters": d.parameters or [],
                    "dashcards": dashcards,
                },
            )

    return collection_id or 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_client(args) -> Any:
    from .main_methods import Metabase_API
    return Metabase_API(
        domain=args.domain or os.environ["METABASE_DOMAIN"],
        email=args.email or os.environ.get("METABASE_EMAIL"),
        password=args.password or os.environ.get("METABASE_PASSWORD"),
        session_id=args.session_id or os.environ.get("METABASE_SESSION_ID"),
    )


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m spark_metabase_api.iac")
    parser.add_argument("--domain", help="Metabase URL (or METABASE_DOMAIN)")
    parser.add_argument("--email", help="Metabase email (or METABASE_EMAIL)")
    parser.add_argument("--password", help="Metabase password (or METABASE_PASSWORD)")
    parser.add_argument("--session-id", help="Metabase session id (or METABASE_SESSION_ID)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser("export", help="Pull a collection tree to a YAML/JSON spec")
    p_export.add_argument("collection", help="Collection id, name, or 'root'")
    p_export.add_argument("output", help="Output path (.yaml/.yml/.json)")

    p_plan = sub.add_parser("plan", help="Show what would change if the spec was applied")
    p_plan.add_argument("spec", help="Path to the spec file")

    p_apply = sub.add_parser("apply", help="Apply the spec to Metabase")
    p_apply.add_argument("spec", help="Path to the spec file")
    p_apply.add_argument("--yes", action="store_true",
                         help="Skip the interactive confirmation")

    args = parser.parse_args(argv)
    client = _build_client(args)

    if args.cmd == "export":
        spec = export(client, args.collection)
        dump(spec, args.output)
        print("Exported to {}".format(args.output))
        return 0

    if args.cmd == "plan":
        spec = load(args.spec)
        the_plan = plan(client, spec)
        print(the_plan.render())
        return 0

    if args.cmd == "apply":
        spec = load(args.spec)
        the_plan = plan(client, spec)
        print(the_plan.render())
        if any(a.op != "skip" for a in the_plan.actions):
            if not args.yes:
                answer = input("\nApply these changes? [y/N] ").strip().lower()
                if answer not in ("y", "yes"):
                    print("Aborted.")
                    return 1
            apply(client, spec)
            print("\nApplied.")
        else:
            print("\nNothing to do.")
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
