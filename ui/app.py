"""
Streamlit Dashboard for the content pipeline.

This is a **HTTP client** for the FastAPI backend (``api/main.py``).
Streamlit holds no graph, no MemorySaver, no PipelineConfig — it just
calls REST endpoints and renders the response.

Phase machine (server is the source of truth; Streamlit just mirrors it):

    idle → awaiting_pick → awaiting_approval → finalized / discarded
                                 ↑________________|   (regenerate loops back)
"""

import logging
import os

import httpx
import streamlit as st

logging.basicConfig(level=logging.INFO)

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
HTTP_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


PROJECT_NAME = os.getenv("PROJECT_NAME", "Content Foundry Agents")

st.set_page_config(
    page_title=PROJECT_NAME,
    page_icon="📰",
    layout="wide",
)

# Session state initialization

if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "snapshot" not in st.session_state:
    st.session_state.snapshot = None
if "api_error" not in st.session_state:
    st.session_state.api_error = None


# API client - helpers

def _api_call(method: str, path: str, json_body: dict | None = None) -> dict | None:
    """Call the FastAPI backend and stash an error message on failure."""
    url = f"{API_BASE_URL}{path}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.request(method, url, json=json_body)
        if resp.status_code >= 400:
            st.session_state.api_error = (
                f"API {method} {path} → {resp.status_code}: {resp.text[:300]}"
            )
            return None
        st.session_state.api_error = None
        return resp.json()
    except httpx.HTTPError as exc:
        st.session_state.api_error = f"Cannot reach API at {url} — {exc}"
        return None


def _check_api_health() -> dict | None:
    return _api_call("GET", "/health")


def _start_run(max_picks: int) -> dict | None:
    return _api_call("POST", "/runs", json_body={"max_editorial_picks": max_picks})


def _select_pick(thread_id: str, pick_id: int) -> dict | None:
    return _api_call("POST", f"/runs/{thread_id}/pick", json_body={"pick_id": pick_id})


def _approve(thread_id: str) -> dict | None:
    return _api_call("POST", f"/runs/{thread_id}/approve")


def _regenerate(thread_id: str, feedback: str) -> dict | None:
    return _api_call(
        "POST", f"/runs/{thread_id}/regenerate", json_body={"feedback": feedback}
    )


def _discard(thread_id: str) -> dict | None:
    return _api_call("POST", f"/runs/{thread_id}/discard")



# Header + sidebar

st.title(f"📰 {PROJECT_NAME}")
st.caption(
    "Multi-agent pipeline: **Trend Scout** → **News Strategist** → "
    "🧑 *Your choice* → **Content Copywriter** → 🧑 *Your approval*"
)
st.divider()

with st.sidebar:
    st.header("⚙️ Backend")
    st.text_input("API base URL", value=API_BASE_URL, key="_api_base_display", disabled=True)
    health = _check_api_health()
    if health:
        st.success(f"API up — {health.get('llm_provider')} / {health.get('llm_model')}")
    else:
        st.error("API unreachable")
    st.divider()
    st.header("🔧 Run settings")
    max_picks = st.slider(      # max_editorial_picks
        "Editorial picks",
        min_value=1,
        max_value=10,
        value=5,
        help="How many editorial angles the News Strategist will curate.",
    )
    st.divider()

if st.session_state.api_error:
    st.error(st.session_state.api_error)

snapshot = st.session_state.snapshot
phase = (snapshot or {}).get("phase") if snapshot else "idle"



# Phase: idle  (no active run)

if phase == "idle" or snapshot is None:
    st.info("Click the button below to scan today's landscape.")
    if st.button("🚀 Start Pipeline", type="primary", use_container_width=True):
        with st.spinner("🔍 Trend Scout + 🧠 News Strategist running on the server..."):
            new_snap = _start_run(max_picks)
        if new_snap:
            st.session_state.thread_id = new_snap["thread_id"]
            st.session_state.snapshot = new_snap
            st.rerun()


# Phase: awaiting_pick  (HITL #1)

elif phase == "awaiting_pick":
    st.subheader("📋 Editorial Picks")
    st.caption(f"Thread `{st.session_state.thread_id}`")
    st.write("The **News Strategist** curated these angles. Choose one:")

    for pick in snapshot.get("picks", []):
        with st.container(border=True):
            col1, col2 = st.columns([5, 1])
            with col1:
                st.markdown(f"**[{pick['id']}] {pick['headline']}**")
                st.write(pick["summary"])
                st.caption(f"💡 {pick['relevance']}")
                if pick.get("source_urls"):
                    st.caption(f"🔗 {pick['source_urls'][0]}")
            with col2:
                if st.button("Select", key=f"pick-{pick['id']}", use_container_width=True):
                    with st.spinner("✍️ Copywriter drafting your post..."):
                        new_snap = _select_pick(
                            st.session_state.thread_id, pick["id"]
                        )
                    if new_snap:
                        st.session_state.snapshot = new_snap
                        st.rerun()



# Phase: awaiting_approval  (HITL #2)

elif phase == "awaiting_approval":
    draft = snapshot.get("draft_post", "")
    st.subheader("✍️ Post Draft")
    st.caption(f"Thread `{st.session_state.thread_id}`")
    st.text_area("Your post:", value=draft, height=300, disabled=True, key="draft_view")

    regen_feedback = st.text_area(
        "💬 Optional feedback for the rewrite",
        key="regen_feedback",
        placeholder=(
            "What to change, the tone you want, sections to drop or expand, "
            "specific terms to use… Leave empty to regenerate freely."
        ),
        height=120,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("✅ Approve & Save", type="primary", use_container_width=True):
            with st.spinner("Finalizing and saving..."):
                new_snap = _approve(st.session_state.thread_id)
            if new_snap:
                st.session_state.snapshot = new_snap
                st.rerun()
    with col2:
        if st.button("🔄 Regenerate", use_container_width=True):
            with st.spinner("🔄 Regenerating with feedback..."):
                new_snap = _regenerate(
                    st.session_state.thread_id, (regen_feedback or "").strip()
                )
            if new_snap:
                st.session_state.snapshot = new_snap
                st.rerun()
    with col3:
        if st.button("❌ Discard", use_container_width=True):
            new_snap = _discard(st.session_state.thread_id)
            if new_snap:
                st.session_state.snapshot = new_snap
                st.rerun()

    usage = snapshot.get("token_usage", {})
    with st.expander("📊 Token Usage Report"):
        c1, c2 = st.columns(2)
        c1.metric("Prompt Tokens", f"{usage.get('prompt_tokens', 0):,}")
        c2.metric("Completion Tokens", f"{usage.get('completion_tokens', 0):,}")


# Phase: finalized / discarded

elif phase in ("finalized", "discarded"):
    if phase == "finalized":
        saved = snapshot.get("saved_path")
        if saved:
            st.success(f"Post saved to `{saved}`")
            st.balloons()
        else:
            st.success("Post finalized.")
        st.text_area(
            "Final post",
            value=snapshot.get("draft_post", ""),
            height=300,
            disabled=True,
            key="final_view",
        )
    else:
        st.warning("Post discarded.")

    usage = snapshot.get("token_usage", {})
    with st.expander("📊 Token Usage Report", expanded=True):
        c1, c2 = st.columns(2)
        c1.metric("Prompt Tokens", f"{usage.get('prompt_tokens', 0):,}")
        c2.metric("Completion Tokens", f"{usage.get('completion_tokens', 0):,}")

    if st.button("🔁 Start a new run", use_container_width=True):
        st.session_state.thread_id = None
        st.session_state.snapshot = None
        st.rerun()
