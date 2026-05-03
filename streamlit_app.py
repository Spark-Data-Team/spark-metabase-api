"""Streamlit frontend for the spark-metabase-api chatbot.

Launch with:
    pip install "spark-metabase-api[chatbot,streamlit,iac]"
    streamlit run streamlit_app.py

Workflow:
    1. Configure Metabase + Anthropic credentials in the sidebar.
    2. Type a natural-language brief in the chat box.
    3. Watch Claude inspect the live Metabase metadata and emit a spec.
    4. Review the proposed spec and the diff (iac.plan).
    5. Click Apply to write the spec to Metabase.
"""
from __future__ import annotations

import json
import os
import traceback
from typing import Any, Dict, List, Optional

import streamlit as st

from spark_metabase_api import Metabase_API, chatbot, iac


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Metabase dashboard authoring",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
)
st.title("Metabase dashboard authoring")
st.caption(
    "Describe the dashboard you want; Claude inspects your Metabase, "
    "proposes a spec, you review and apply."
)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults: Dict[str, Any] = {
        "metabase": None,            # connected Metabase_API instance
        "history": [],               # list of (role, content) — chat transcript
        "current_events": [],        # events from the latest agent run
        "proposed_spec": None,       # CollectionSpec produced by Claude
        "plan": None,                # iac.Plan computed from the spec
        "applied": False,            # whether the spec was applied
        "error": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


_init_state()


# ---------------------------------------------------------------------------
# Sidebar — credentials and connection
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Metabase")
    domain = st.text_input(
        "Metabase URL",
        value=os.environ.get("METABASE_DOMAIN", ""),
        placeholder="https://metabase.example.com",
    )
    auth_mode = st.radio(
        "Auth mode",
        options=["Email + password", "Session id"],
        horizontal=True,
    )
    email = password = session_id = None
    if auth_mode == "Email + password":
        email = st.text_input(
            "Email", value=os.environ.get("METABASE_EMAIL", "")
        )
        password = st.text_input(
            "Password", type="password", value=os.environ.get("METABASE_PASSWORD", "")
        )
    else:
        session_id = st.text_input(
            "Session id", value=os.environ.get("METABASE_SESSION_ID", "")
        )

    if st.button("Connect to Metabase", use_container_width=True):
        try:
            st.session_state.metabase = Metabase_API(
                domain=domain,
                email=email or None,
                password=password or None,
                session_id=session_id or None,
            )
            st.success("Connected.")
        except Exception as exc:  # pragma: no cover - UI feedback
            st.session_state.metabase = None
            st.error("Connection failed: {}".format(exc))

    st.divider()
    st.header("Anthropic")
    api_key = st.text_input(
        "API key",
        type="password",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Stored only in this session; not written to disk.",
    )
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    model = st.selectbox(
        "Model",
        options=["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"],
        index=0,
        help="Opus 4.7 is the default; Sonnet 4.6 is cheaper for simpler briefs.",
    )

    st.divider()
    if st.button("Reset conversation", use_container_width=True):
        for key in ("history", "current_events", "proposed_spec", "plan", "applied", "error"):
            st.session_state[key] = [] if key in ("history", "current_events") else (
                False if key == "applied" else None
            )
        st.rerun()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_args(input_dict: Dict[str, Any]) -> str:
    parts = []
    for k, v in input_dict.items():
        rendered = json.dumps(v, ensure_ascii=False)
        if len(rendered) > 80:
            rendered = rendered[:77] + "..."
        parts.append("{}={}".format(k, rendered))
    return ", ".join(parts)


def _render_event(event_type: str, payload: Any) -> None:
    """Render a single chat event in the assistant's bubble."""
    if event_type == "text":
        st.markdown(payload)
    elif event_type == "tool_call":
        st.markdown(
            ":wrench: **{}**({})".format(payload["name"], _format_args(payload["input"]))
        )
    elif event_type == "tool_result":
        with st.expander(":receipt: {} returned".format(payload["name"]), expanded=False):
            try:
                parsed = json.loads(payload["result"])
                st.json(parsed)
            except (TypeError, ValueError):
                st.code(payload["result"])
    elif event_type == "proposed":
        st.success(":white_check_mark: Spec proposed.")


def _spec_to_yaml_or_json(spec: iac.CollectionSpec) -> str:
    try:
        import yaml  # type: ignore

        return yaml.safe_dump(iac._spec_to_dict(spec), sort_keys=False, allow_unicode=True)
    except ImportError:
        return json.dumps(iac._spec_to_dict(spec), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Replay the conversation
# ---------------------------------------------------------------------------

for role, blocks in st.session_state.history:
    with st.chat_message(role):
        if role == "user":
            st.markdown(blocks)
        else:
            for ev_type, payload in blocks:
                _render_event(ev_type, payload)


# ---------------------------------------------------------------------------
# Live agent run (only fires when user submits a new prompt)
# ---------------------------------------------------------------------------

prompt = st.chat_input(
    "Describe the dashboard to build (e.g. 'Acme overview with monthly revenue and top accounts')"
)

if prompt:
    if st.session_state.metabase is None:
        st.error("Connect to Metabase first (sidebar).")
        st.stop()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("Provide your Anthropic API key (sidebar).")
        st.stop()

    st.session_state.history.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)

    rendered_events: List[tuple] = []
    with st.chat_message("assistant"):
        try:
            for ev_type, payload in chatbot.stream(
                st.session_state.metabase, prompt, model=model,
            ):
                rendered_events.append((ev_type, payload))
                _render_event(ev_type, payload)
                if ev_type == "proposed":
                    st.session_state.proposed_spec = iac._spec_from_dict(payload)
        except Exception as exc:  # pragma: no cover - UI feedback
            st.error("Agent crashed: {}".format(exc))
            with st.expander("Traceback"):
                st.code(traceback.format_exc())

    st.session_state.history.append(("assistant", rendered_events))
    # Reset plan / apply state so the new spec gets a fresh review.
    st.session_state.plan = None
    st.session_state.applied = False


# ---------------------------------------------------------------------------
# Review & apply
# ---------------------------------------------------------------------------

spec = st.session_state.proposed_spec
if spec is not None:
    st.divider()
    st.subheader("Proposed spec")
    st.code(_spec_to_yaml_or_json(spec), language="yaml")

    col_plan, col_apply = st.columns(2)

    with col_plan:
        if st.button("Compute plan", use_container_width=True):
            try:
                st.session_state.plan = iac.plan(st.session_state.metabase, spec)
            except Exception as exc:  # pragma: no cover - UI feedback
                st.error("plan() failed: {}".format(exc))
                with st.expander("Traceback"):
                    st.code(traceback.format_exc())

    if st.session_state.plan is not None:
        st.subheader("Plan")
        st.code(st.session_state.plan.render(), language="text")

    with col_apply:
        disabled = (
            st.session_state.plan is None
            or all(a.op == "skip" for a in st.session_state.plan.actions)
            or st.session_state.applied
        )
        if st.button("Apply", type="primary", use_container_width=True, disabled=disabled):
            try:
                iac.apply(st.session_state.metabase, spec)
                st.session_state.applied = True
                st.success("Applied. Re-run plan to confirm idempotency.")
            except Exception as exc:  # pragma: no cover - UI feedback
                st.error("apply() failed: {}".format(exc))
                with st.expander("Traceback"):
                    st.code(traceback.format_exc())
