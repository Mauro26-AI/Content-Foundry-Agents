"""
News Strategist Agent — Editorial Curation.

Receives raw news from the Trend Scout, invokes an LLM to rank and distill
them into N editorial angles.

The system prompt — including the target audience, editorial priorities,
and avoid-list — lives in ``prompts/system_strategist.md`` so it can be
customised without changing code.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from src.core.state import EditorialPick, GraphState, TokenUsage
from src.utils.config import PipelineConfig
from src.utils.llm import build_llm
from src.utils.logger import log_llm_usage
from src.utils.prompts import fill, load_prompt

logger = logging.getLogger("content_pipeline.news_strategist")


# Pydantic schema

class PickSchema(BaseModel):
    """A single editorial angle, exactly as the LLM must produce it."""

    headline: str = Field(
        description="A punchy editorial headline (≤ 15 words)."
    )
    summary: str = Field(
        description="2-3 sentence factual summary of the news."
    )
    relevance: str = Field(
        description=(
            "1-2 sentences explaining the reader takeaway — what changes "
            "for the target audience."
        )
    )
    source_urls: list[str] = Field(
        default_factory=list,
        description="List of original article URLs, verbatim from input.",
    )


class StrategistOutput(BaseModel):
    """Top-level schema returned by the LLM."""

    picks: list[PickSchema] = Field(
        description="The curated editorial angles, ordered by editorial priority."
    )


def news_strategist_node(state: GraphState, config: RunnableConfig) -> dict:
    """
    LangGraph node: distill raw news into editorial picks.

    Returns a partial state update with ``editorial_picks`` and a delta
    ``token_usage`` (the reducer in GraphState accumulates it).
    """
    pipeline_cfg: PipelineConfig = config["configurable"]["pipeline_config"]
    raw_news = state["raw_news"]

    news_payload = json.dumps(
        [{"title": n.title, "url": n.url, "snippet": n.snippet} for n in raw_news],
        indent=2,
    )

    base_llm = build_llm(pipeline_cfg, temperature=pipeline_cfg.strategist_temperature)

    structured_llm = base_llm.with_structured_output(
        StrategistOutput, include_raw=True
    )

    system_prompt = fill(
        load_prompt("system_strategist", pipeline_cfg.prompts_dir),
        max_picks=str(pipeline_cfg.max_editorial_picks),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=news_payload),
    ]

    response = structured_llm.invoke(messages)

    raw_msg = response["raw"]
    parsed: StrategistOutput | None = response["parsed"]
    parsing_error = response["parsing_error"]

    step_usage = TokenUsage()
    if raw_msg is not None:
        log_llm_usage(raw_msg, usage=step_usage, step_name="news_strategist")

    if parsing_error is not None or parsed is None:
        logger.error("Strategist structured-output failed: %s", parsing_error)
        editorial_picks: list[EditorialPick] = []
    else:
        # Re-assign id deterministically so downstream ``selected_pick_id`` 
        # lookups are always stable.
        editorial_picks = [
            EditorialPick(
                id=idx,
                headline=p.headline,
                summary=p.summary,
                relevance=p.relevance,
                source_urls=p.source_urls or [],
            )
            for idx, p in enumerate(parsed.picks, start=1)
        ]

    logger.info("News Strategist produced %d editorial picks.", len(editorial_picks))

    return {
        "editorial_picks": editorial_picks,
        "token_usage": step_usage,
    }
