#!/usr/bin/env python3
"""Integration tests for spark-metabase-api against a live Metabase instance.

The script runs in 4 phases, each with a clear safety boundary:

    Phase 1  read-only checks   (auth, search, iac.export idempotency)
    Phase 2  sandbox writes     (creates a throwaway collection, applies a
                                 mini-spec, exercises add_card_to_dashboard
                                 and copy_dashboard's deepcopy path)
    Phase 3  optional chatbot   (Claude proposes a spec — NOT applied)
    Phase 4  cleanup            (archive the sandbox; runs even on failure)

The sandbox is archived in a finally block so a crash mid-test doesn't leave
junk behind. Pass --keep-sandbox to keep it around for manual inspection.

Usage:
    python tests/integration_test.py \\
        --domain https://metabase.example.com \\
        --email me@example.com \\
        --password '...'

    # Or with a session id:
    python tests/integration_test.py \\
        --domain https://metabase.example.com \\
        --session-id <session>

    # Phase 1 also runs the iac round-trip on a real collection if you pass
    # one (read-only — never modified):
    python tests/integration_test.py ... --collection "My Reports"

    # copy_dashboard is exercised if you pass an existing dashboard id (the
    # original is read-only; a deep copy is made inside the sandbox):
    python tests/integration_test.py ... --source-dashboard-id 42

    # Opt in to the chatbot phase (requires ANTHROPIC_API_KEY in env):
    python tests/integration_test.py ... --chatbot

Exit code is 0 on success, 1 on any failed assertion.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Allow running straight from a checkout (`python tests/integration_test.py`)
# without `pip install -e .` first.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spark_metabase_api import Metabase_API, iac  # noqa: E402


SANDBOX_NAME_PREFIX = "spark-metabase-api integration test"


# ---------------------------------------------------------------------------
# Status output
# ---------------------------------------------------------------------------

def _step(label: str) -> None:
    print("\n=== {} ===".format(label))


def _ok(msg: str) -> None:
    print("  [ok]   {}".format(msg))


def _skip(msg: str) -> None:
    print("  [skip] {}".format(msg))


def _fail(msg: str) -> None:
    print("  [FAIL] {}".format(msg))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_parent_id(mb: Metabase_API, collection_ref: Any) -> Optional[int]:
    """Return the parent collection id of `collection_ref`, or None for Root.

    iac.plan/apply need to know where the spec lives so they diff against the
    right sibling set. Metabase returns the parent path on a collection as
    `location`: "/" for Root, "/5/" for a child of #5, "/5/10/" for a
    grandchild.
    """
    if collection_ref in (None, "root", "Root"):
        return None
    if isinstance(collection_ref, int) or (
        isinstance(collection_ref, str) and collection_ref.isdigit()
    ):
        cid = int(collection_ref)
    else:
        cid = mb.get_item_id("collection", collection_ref)
    info = mb.get("/api/collection/{}".format(cid)) or {}
    location = info.get("location") or "/"
    parts = [p for p in location.strip("/").split("/") if p]
    return int(parts[-1]) if parts else None


def _pick_first_db(mb: Metabase_API) -> int:
    res = mb.get("/api/database/")
    dbs = res.get("data", res) if isinstance(res, dict) else res
    if not dbs:
        raise RuntimeError("No databases configured on this Metabase instance.")
    return dbs[0]["id"]


def _find_child(
    mb: Metabase_API, collection_id: int, kind: str, name: str,
) -> int:
    res = mb.get("/api/collection/{}/items".format(collection_id))
    items = res.get("data", res) if isinstance(res, dict) else res
    for item in items or []:
        if item.get("model") == kind and item.get("name") == name:
            return item["id"]
    raise LookupError(
        "no {} named {!r} in collection {}".format(kind, name, collection_id)
    )


# ---------------------------------------------------------------------------
# Phase 1 — read-only
# ---------------------------------------------------------------------------

def phase1_readonly(mb: Metabase_API, sample_collection: Optional[str]) -> None:
    _step("Phase 1: read-only checks")

    info = mb.get("/api/user/current")
    assert info and info.get("email"), "auth check returned empty"
    _ok("authenticated as {}".format(info["email"]))

    results = mb.search("a", item_type=None)
    assert isinstance(results, list), "search did not return a list"
    _ok("search('a') returned {} items".format(len(results)))

    dashboards = [r for r in results if r.get("model") == "dashboard"]
    card_id: Optional[int] = None
    if dashboards:
        dash_id = dashboards[0]["id"]
        cards = mb.get_dashboard_question_ids(dashboard_id=dash_id)
        _ok("get_dashboard_question_ids({}) -> {} cards".format(dash_id, len(cards)))
        if cards:
            card_id = cards[0]
    else:
        _skip("get_dashboard_question_ids: no dashboard surfaced by search")

    # Validation smoke (read-only): a known-good card must pass the gate.
    from spark_metabase_api import validate as V  # noqa: PLC0415
    if card_id:
        report = V.gate(mb, [V.unit_from_card_id(mb, card_id)], execute=True)
        print(report.render())
        assert report.ok(), "validation gate failed on a known-good card"
        _ok("validate.gate passed on card#{}".format(card_id))
    else:
        _skip("validate.gate smoke: no card id available (no dashboard with cards found)")

    if sample_collection is None:
        _skip("iac.export idempotency: no --collection passed")
        return

    print("  ... exporting {!r} (may take a while for large collections)"
          .format(sample_collection))
    spec = iac.export(mb, sample_collection)
    parent_id = _resolve_parent_id(mb, sample_collection)
    p = iac.plan(mb, spec, parent_id=parent_id)
    if all(a.op == "skip" for a in p.actions):
        _ok("iac.export({!r}) -> {} items, plan all-skip (idempotent)"
            .format(sample_collection, len(p.actions)))
    else:
        non_skip = [(a.op, a.path, a.reason) for a in p.actions if a.op != "skip"]
        raise AssertionError(
            "iac.plan on freshly exported spec is NOT idempotent. "
            "Non-skip actions: {}".format(non_skip)
        )


# ---------------------------------------------------------------------------
# Phase 2 — sandbox writes
# ---------------------------------------------------------------------------

def phase2_sandbox(
    mb: Metabase_API, source_dashboard_id: Optional[int],
) -> int:
    _step("Phase 2: sandbox writes")
    sandbox_name = "{} ({})".format(SANDBOX_NAME_PREFIX, int(time.time()))

    # 1. create_collection — covers the color-retry fix.
    res = mb.create_collection(
        sandbox_name, parent_collection_name="Root", return_results=True,
    )
    assert isinstance(res, dict) and res.get("id"), \
        "create_collection returned {!r}".format(res)
    sandbox_id = res["id"]
    _ok("created sandbox collection #{} {!r}".format(sandbox_id, sandbox_name))

    # 2. iac.apply with a card + a dashboard that forward-references the card
    #    by name — covers card_name resolution, executor reorder, and the
    #    end-to-end create path.
    db_id = _pick_first_db(mb)
    spec = iac.CollectionSpec(
        name=sandbox_name,                      # match the live sandbox
        cards=[iac.CardSpec(
            name="Test card",
            definition={
                "dataset_query": {
                    "type": "native",
                    "database": db_id,
                    "native": {"query": "SELECT 1 AS one"},
                },
                "display": "scalar",
                "visualization_settings": {},
            },
        )],
        dashboards=[iac.DashboardSpec(
            name="Test dashboard",
            parameters=[],
            dashcards=[{
                "id": -1,
                "card_name": "Test card",       # forward reference
                "row": 0, "col": 0, "size_x": 24, "size_y": 8,
                "parameter_mappings": [],
                "visualization_settings": {},
            }],
        )],
    )
    parent_id = None  # sandbox lives at Root
    p = iac.apply(mb, spec, parent_id=parent_id)
    assert any(a.op == "create" for a in p.actions), \
        "expected creates in fresh apply, got: {}".format(p.summary())
    _ok("iac.apply -> {}".format(p.summary()))

    # 3. Re-plan must be all-skip (idempotency on a live instance — covers
    #    the dashcard card_name resolution at plan time).
    p2 = iac.plan(mb, spec, parent_id=parent_id)
    if not all(a.op == "skip" for a in p2.actions):
        raise AssertionError(
            "iac.plan after apply is NOT idempotent:\n{}".format(p2.render())
        )
    _ok("re-plan: all-skip (idempotent on live)")

    # 4. add_card_to_dashboard — exercises the legacy POST or the modern PUT
    #    fallback, depending on the Metabase version. We append a SECOND
    #    dashcard pointing at the same card.
    test_dash_id = _find_child(mb, sandbox_id, "dashboard", "Test dashboard")
    test_card_id = _find_child(mb, sandbox_id, "card", "Test card")
    mb.add_card_to_dashboard(card_id=test_card_id, dashboard_id=test_dash_id)
    refreshed = mb.get("/api/dashboard/{}".format(test_dash_id)) or {}
    dashcards = refreshed.get("dashcards") or refreshed.get("ordered_cards") or []
    assert len(dashcards) >= 2, (
        "add_card_to_dashboard didn't append a card; "
        "dashcards={}".format(len(dashcards))
    )
    _ok("add_card_to_dashboard appended a card; dashboard now has {} dashcards"
        .format(len(dashcards)))

    # 5. (optional) copy_dashboard with deepcopy — covers the rstrip → suffix
    #    fix. The source dashboard is read-only.
    if source_dashboard_id is not None:
        copied_id, q_coll_id, q_ids = mb.copy_dashboard(
            source_dashboard_id=source_dashboard_id,
            destination_collection_id=sandbox_id,
            destination_dashboard_name="Copied dashboard",
            deepcopy=True,
        )
        _ok("copy_dashboard deepcopy: dashboard #{} + {} questions in "
            "collection #{}".format(copied_id, len(q_ids or []), q_coll_id))
    else:
        _skip("copy_dashboard deepcopy: no --source-dashboard-id passed")

    return sandbox_id


# ---------------------------------------------------------------------------
# Phase 3 — optional chatbot
# ---------------------------------------------------------------------------

def phase3_chatbot(mb: Metabase_API) -> None:
    _step("Phase 3: chatbot end-to-end (read-only)")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _skip("ANTHROPIC_API_KEY is not set")
        return
    try:
        from spark_metabase_api.chatbot import chat
    except ImportError:
        _skip("anthropic not installed (pip install spark-metabase-api[chatbot])")
        return

    print("  ... running the agent (~30-90s, ~$0.50 in API tokens)")
    spec = chat(
        mb,
        "Build the smallest possible test spec: one collection named "
        "'chatbot smoke test', containing a single card whose native SQL "
        "query is exactly 'SELECT 1 AS one'. Pick database id 1 if it "
        "exists, otherwise the first database returned by list_databases. "
        "Do NOT explore tables — keep the query as 'SELECT 1 AS one'.",
        verbose=False,
    )
    assert spec.name, "chatbot returned a spec with no name"
    assert spec.cards or spec.dashboards, "chatbot returned an empty spec"
    _ok("chatbot proposed: {!r} ({} cards, {} dashboards) — NOT applied"
        .format(spec.name, len(spec.cards), len(spec.dashboards)))


# ---------------------------------------------------------------------------
# Phase 4 — cleanup
# ---------------------------------------------------------------------------

def cleanup(mb: Metabase_API, sandbox_id: int, keep: bool) -> None:
    _step("Phase 4: cleanup")
    if keep:
        _skip("--keep-sandbox set; sandbox #{} left behind".format(sandbox_id))
        return
    try:
        mb.move_to_archive("collection", item_id=sandbox_id)
        _ok("sandbox collection #{} archived".format(sandbox_id))
    except Exception as exc:
        _fail("could not archive sandbox #{}: {}. Archive it manually."
              .format(sandbox_id, exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--domain", required=True, help="Metabase URL")
    parser.add_argument("--email", help="Metabase email (or METABASE_EMAIL)")
    parser.add_argument("--password", help="Metabase password (or METABASE_PASSWORD)")
    parser.add_argument("--session-id", help="Session id (or METABASE_SESSION_ID)")
    parser.add_argument(
        "--collection",
        help="Existing collection name or id, used for the iac.export "
             "idempotency check (read-only)",
    )
    parser.add_argument(
        "--source-dashboard-id", type=int,
        help="An existing dashboard id to test copy_dashboard(deepcopy=True). "
             "The original is read-only.",
    )
    parser.add_argument(
        "--chatbot", action="store_true",
        help="Also run the chatbot end-to-end (does NOT apply the spec)",
    )
    parser.add_argument(
        "--keep-sandbox", action="store_true",
        help="Don't archive the sandbox collection at the end",
    )
    args = parser.parse_args()

    print("Connecting to {} ...".format(args.domain))
    mb = Metabase_API(
        domain=args.domain,
        email=args.email or os.environ.get("METABASE_EMAIL") or None,
        password=args.password or os.environ.get("METABASE_PASSWORD") or None,
        session_id=args.session_id or os.environ.get("METABASE_SESSION_ID") or None,
    )

    sandbox_id: Optional[int] = None
    failed_with: Optional[BaseException] = None
    try:
        phase1_readonly(mb, args.collection)
        sandbox_id = phase2_sandbox(mb, args.source_dashboard_id)
        if args.chatbot:
            phase3_chatbot(mb)
    except AssertionError as exc:
        _fail(str(exc))
        failed_with = exc
    except Exception as exc:  # noqa: BLE001 — we want to surface anything
        _fail("unexpected error: {}: {}".format(type(exc).__name__, exc))
        failed_with = exc
    finally:
        if sandbox_id is not None:
            cleanup(mb, sandbox_id, keep=args.keep_sandbox)

    print()
    if failed_with is not None:
        print("Integration tests FAILED.")
        return 1
    print("All integration tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
