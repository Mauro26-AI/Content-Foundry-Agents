"""
LangGraph Workflow — Multi-Agent Pipeline with Human-in-the-Loop.

Two interrupt points on the copywriter node:

    [Trend Scout] → [News Strategist]
        → ⏸ interrupt_before(Copywriter) — user selects editorial pick
        → [Content Copywriter]
        → ⏸ interrupt_after(Copywriter)  — user approves / regenerates draft
        → END  (or loop back to Copywriter if human_approved is False)
"""

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from src.agents.content_copywriter import content_copywriter_node
from src.agents.news_strategist import news_strategist_node
from src.agents.trend_scout import trend_scout_node
from src.core.state import GraphState

logger = logging.getLogger("content_pipeline.graph")

TREND_SCOUT = "trend_scout"
NEWS_STRATEGIST = "news_strategist"
COPYWRITER = "content_copywriter"


def _route_after_approval(state: GraphState) -> str:
    """
    Conditional edge evaluated after interrupt_after(COPYWRITER).

    human_approved=True                          → END  (approve)
    human_approved=False & draft_post empty      → END  (discard)
    human_approved=False & draft_post non-empty  → re-run copywriter (regenerate)
    None                                         → re-run copywriter
    """
    if state.get("human_approved") is True:
        return END
    if state.get("human_approved") is False and not (state.get("draft_post") or "").strip():
        return END
    return COPYWRITER


def build_graph():
    """
    Full pipeline graph with two HITL breakpoints.

    Breakpoint 1 — interrupt_before(COPYWRITER):
        Pause after curation so user can pick an editorial angle.
        Resume with: graph.update_state(config, {"selected_pick_id": N})

    Breakpoint 2 — interrupt_after(COPYWRITER):
        Pause after draft is generated so user can approve or regenerate.
        Approve:    graph.update_state(config, {"human_approved": True})  → invoke → END
        Regenerate: graph.update_state(config, {"human_approved": False}) → invoke (traverses
                    conditional back to COPYWRITER, pauses at interrupt_before)
                    → invoke again (runs copywriter, pauses at interrupt_after)
    """
    workflow = StateGraph(GraphState)

    workflow.add_node(TREND_SCOUT, trend_scout_node)
    workflow.add_node(NEWS_STRATEGIST, news_strategist_node)
    workflow.add_node(COPYWRITER, content_copywriter_node)

    workflow.set_entry_point(TREND_SCOUT)
    workflow.add_edge(TREND_SCOUT, NEWS_STRATEGIST)
    workflow.add_edge(NEWS_STRATEGIST, COPYWRITER)
    workflow.add_conditional_edges(
        COPYWRITER,
        _route_after_approval,
        {END: END, COPYWRITER: COPYWRITER},
    )

    memory = MemorySaver()
    return workflow.compile(
        checkpointer=memory,
        interrupt_before=[COPYWRITER],
        interrupt_after=[COPYWRITER],
    )


def build_copywriter_only_graph():
    """
    Minimal graph for Phase 2 (GitHub Actions): runs only the Content
    Copywriter with no interrupts. Single-pass, no checkpointing needed.
    Requires editorial_picks and selected_pick_id already set in the
    initial state.
    """
    workflow = StateGraph(GraphState)
    workflow.add_node(COPYWRITER, content_copywriter_node)
    workflow.set_entry_point(COPYWRITER)
    workflow.add_edge(COPYWRITER, END)
    return workflow.compile()
