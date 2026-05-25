"""
Graph state definition for the content pipeline.

Uses TypedDict with Annotated reducers so LangGraph knows how
to merge partial updates produced by each node.
"""

from dataclasses import dataclass, field
from typing import Annotated, TypedDict


# Domain models

@dataclass
class NewsItem:
    """A single news article surfaced by the Trend Scout."""

    id: int
    title: str
    url: str
    snippet: str
    source: str
    published: str = ""


@dataclass
class EditorialPick:
    """A curated editorial angle proposed by the News Strategist."""

    id: int
    headline: str
    summary: str
    relevance: str
    source_urls: list[str] = field(default_factory=list)


@dataclass
class TokenUsage:
    """Accumulated token counts across all LLM calls in a run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion


def _add_usage(a: "TokenUsage | None", b: "TokenUsage | None") -> "TokenUsage":
    """LangGraph reducer: accumulate TokenUsage across nodes."""
    if a is None:
        return b or TokenUsage()
    if b is None:
        return a
    return TokenUsage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
    )


# LangGraph state

class GraphState(TypedDict, total=False):
    """
    Shared state that travels across every node in the graph.
    """

    raw_news: list[NewsItem]
    editorial_picks: list[EditorialPick]
    selected_pick_id: int | None
    human_approved: bool | None
    draft_post: str
    # Set by the human when requesting a regeneration with extra instructions.
    regeneration_feedback: str
    token_usage: Annotated[TokenUsage, _add_usage]


# Initial-state factory
def make_initial_state() -> GraphState:
    """
    Build a fresh ``GraphState`` with all fields zeroed.

    Every entry point (FastAPI, Streamlit-via-API, GitHub Actions
    scripts) must use this factory rather than redefining the dict
    inline.
    """
    return {
        "raw_news": [],
        "editorial_picks": [],
        "selected_pick_id": None,
        "human_approved": None,
        "draft_post": "",
        "regeneration_feedback": "",
        "token_usage": TokenUsage(),
    }
