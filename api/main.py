"""
FastAPI backend — HTTP surface over the LangGraph HITL pipeline.

Run with:
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Streamlit (or others UI) talks to this service via REST. The graph
and its ``MemorySaver`` checkpointer live in this process as module-level
singletons: every run is keyed by ``thread_id`` and resumed across HTTP
requests using LangGraph's checkpoint mechanism.

Endpoints
---------
    POST   /runs                          → start Phase 1, return picks
    POST   /runs/{thread_id}/pick         → resume to draft (after pick)
    POST   /runs/{thread_id}/approve      → finalize + save post on disk
    POST   /runs/{thread_id}/regenerate   → produce a new draft
    POST   /runs/{thread_id}/discard      → close the run without saving

The "phase" string returned to clients is a coarse state-machine label
(awaiting_pick / awaiting_approval / finalized / discarded) so the UI
does not have to inspect LangGraph internals.
"""

import dataclasses
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import (
    PickDTO,
    PickInput,
    RegenerateInput,
    RunInput,
    RunStateDTO,
    TokenUsageDTO,
)
from src.core.graph import build_graph
from src.core.state import EditorialPick, TokenUsage, make_initial_state
from src.utils.config import PipelineConfig
from src.utils.tracing import configure_langsmith, get_run_metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("content_pipeline.api")


# Application + singletons
app = FastAPI(
    title="Content Foundry Agents API",
    version="1.0.0",
    description="HTTP surface over the LangGraph HITL pipeline.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Build the graph once at process start. ``MemorySaver`` is held inside
# the compiled graph instance: every ``thread_id`` is independent.
_pipeline_cfg: PipelineConfig = PipelineConfig()
configure_langsmith(_pipeline_cfg)
_graph = build_graph()


def _thread_config(thread_id: str) -> dict:
    """Build the thread runnable config (carries the pipeline cfg)."""
    return {
        "configurable": {
            "thread_id": thread_id,
            "pipeline_config": _pipeline_cfg,
        },
        "metadata": get_run_metadata(run_type="streamlit"),
    }


# State helpers

def _pick_to_dto(pick: EditorialPick) -> PickDTO:
    return PickDTO(**asdict(pick))

def _usage_to_dto(usage: TokenUsage | None) -> TokenUsageDTO:
    if usage is None:
        return TokenUsageDTO()
    return TokenUsageDTO(**asdict(usage))

def _get_snapshot_values(thread_id: str) -> dict[str, Any]:
    """Return the current LangGraph state values (or raise 404)."""
    snapshot = _graph.get_state(_thread_config(thread_id))
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail=f"Unknown thread_id: {thread_id}")
    return snapshot.values

def _infer_phase(values: dict[str, Any], snapshot_next: tuple[str, ...]) -> str:
    """
    Map LangGraph's (next-nodes + values) into a coarse UI phase.

    Heuristic:
      • snapshot.next == ()                                       → terminal → finalized/discarded
      • copywriter is next and we already have a draft            → awaiting_approval
      • copywriter is next without a draft                        → awaiting_pick
    """
    if not snapshot_next:
        if values.get("human_approved") is False and not values.get("draft_post"):
            return "discarded"
        return "finalized"
    if values.get("draft_post"):
        return "awaiting_approval"
    return "awaiting_pick"

def _build_run_state(thread_id: str, saved_path: str | None = None) -> RunStateDTO:
    snapshot = _graph.get_state(_thread_config(thread_id))
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Unknown thread_id: {thread_id}")
    values = snapshot.values or {}
    phase = _infer_phase(values, snapshot.next or ())

    return RunStateDTO(
        thread_id=thread_id,
        phase=phase,
        picks=[_pick_to_dto(p) for p in values.get("editorial_picks", []) or []],
        selected_pick_id=values.get("selected_pick_id"),
        draft_post=values.get("draft_post", "") or "",
        saved_path=saved_path,
        token_usage=_usage_to_dto(values.get("token_usage")),
    )


# Endpoints

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_provider": _pipeline_cfg.llm_provider,
        "llm_model": _pipeline_cfg.llm_model,
    }


@app.post("/runs", response_model=RunStateDTO)
def start_run(body: RunInput = RunInput()) -> RunStateDTO:
    """
    Phase 1: Trend Scout + News Strategist. Pauses at interrupt_before
    the Copywriter. Returns the picks for the human to choose from.

    Optional body: ``{"max_editorial_picks": 3}`` (1-10, default 5).
    """
    thread_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    logger.info(
        "Starting run thread_id=%s max_editorial_picks=%d",
        thread_id,
        body.max_editorial_picks,
    )

    run_cfg = dataclasses.replace(_pipeline_cfg, max_editorial_picks=body.max_editorial_picks)
    cfg = {
        "configurable": {
            "thread_id": thread_id,
            "pipeline_config": run_cfg,
        },
        "metadata": get_run_metadata(run_type="streamlit"),
    }
    _graph.invoke(make_initial_state(), cfg)
    return _build_run_state(thread_id)


@app.post("/runs/{thread_id}/pick", response_model=RunStateDTO)
def select_pick(thread_id: str, payload: PickInput) -> RunStateDTO:
    """
    HITL #1: human selects an editorial pick. Resume the graph so the
    Copywriter produces the first draft, then pause at interrupt_after.
    """
    values = _get_snapshot_values(thread_id)
    valid_ids = {p.id for p in values.get("editorial_picks", []) or []}
    if payload.pick_id not in valid_ids:
        raise HTTPException(
            status_code=400,
            detail=f"pick_id {payload.pick_id} not in {sorted(valid_ids)}",
        )

    cfg = _thread_config(thread_id)
    _graph.update_state(cfg, {"selected_pick_id": payload.pick_id})
    _graph.invoke(None, cfg)  # runs Copywriter → pauses at interrupt_after
    return _build_run_state(thread_id)


@app.post("/runs/{thread_id}/approve", response_model=RunStateDTO)
def approve(thread_id: str) -> RunStateDTO:
    """
    HITL #2 (approve): finalize the run, write the post to disk, return
    the final snapshot with the saved file path.
    """
    values = _get_snapshot_values(thread_id)
    draft = (values.get("draft_post") or "").strip()
    if not draft:
        raise HTTPException(status_code=409, detail="No draft to approve.")

    cfg = _thread_config(thread_id)
    _graph.update_state(cfg, {"human_approved": True})
    _graph.invoke(None, cfg)  # conditional edge → END

    saved_path = _save_post(thread_id, draft, values)
    return _build_run_state(thread_id, saved_path=str(saved_path))


@app.post("/runs/{thread_id}/regenerate", response_model=RunStateDTO)
def regenerate(thread_id: str, payload: RegenerateInput) -> RunStateDTO:
    """
    HITL #2 (regenerate): rewind to the Copywriter with optional feedback
    and previous draft, then run it again. Pauses at interrupt_after.

    2 invoke:
      1. invoke(None) traverses the conditional edge back to the
         copywriter and pauses at ``interrupt_before`` (no LLM call).
      2. invoke(None) runs the copywriter and pauses at ``interrupt_after``.
    """
    values = _get_snapshot_values(thread_id)
    if not (values.get("draft_post") or "").strip():
        raise HTTPException(status_code=409, detail="Nothing to regenerate yet.")

    cfg = _thread_config(thread_id)
    _graph.update_state(
        cfg,
        {
            "human_approved": False,
            "regeneration_feedback": (payload.feedback or "").strip(),
        },
    )
    _graph.invoke(None, cfg)
    _graph.invoke(None, cfg)
    return _build_run_state(thread_id)


@app.post("/runs/{thread_id}/discard", response_model=RunStateDTO)
def discard(thread_id: str) -> RunStateDTO:
    """Close the run without saving. The graph traverses to END so the
    thread is properly terminated; it remains queryable for audit."""
    cfg = _thread_config(thread_id)
    _graph.update_state(
        cfg,
        {"human_approved": False, "draft_post": ""},
    )
    # Traverse the conditional edge → END.
    _graph.invoke(None, cfg)
    return _build_run_state(thread_id)


# Persistence
def _save_post(thread_id: str, draft: str, values: dict[str, Any]) -> Path:
    """
    Write the approved post to ``posts/post_<thread_id>.md``.

    Includes a small metadata block (topic, sources, cost) for traceability
    so each file is self-contained.
    """
    picks = values.get("editorial_picks", []) or []
    selected_id = values.get("selected_pick_id")
    chosen = next((p for p in picks if p.id == selected_id), None)

    usage: TokenUsage = values.get("token_usage") or TokenUsage()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = Path(_pipeline_cfg.output_dir) / f"{today}.md"

    sources = ", ".join(chosen.source_urls) if chosen and chosen.source_urls else "—"
    headline = chosen.headline if chosen else "(unknown topic)"
    summary = chosen.summary if chosen else ""

    content = (
        f"# {headline}\n\n"
        f"> Generated on {today} by {_pipeline_cfg.project_name} (Streamlit/FastAPI)\n\n"
        f"## Post\n\n{draft}\n\n"
        f"---\n\n"
        f"## Metadata\n\n"
        f"- **Topic**: {headline}\n"
        f"- **Summary**: {summary}\n"
        f"- **Sources**: {sources}\n\n"
        f"## Token Usage\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Prompt tokens | {usage.prompt_tokens:,} |\n"
        f"| Completion tokens | {usage.completion_tokens:,} |\n"
        f"| Total tokens | {usage.total_tokens:,} |\n"
    )
    filepath.write_text(content, encoding="utf-8")
    logger.info("Post saved to %s", filepath)
    return filepath
