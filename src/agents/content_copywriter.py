"""
Content Copywriter Agent — Post Generation.

Receives the user-selected editorial pick and crafts a post in the voice
and structure defined by ``prompts/system_copywriter.md`` and
``prompts/post_example.md``.

Two operating modes:
  • **First draft**: temperature = ``config.copywriter_temperature``.
  • **Regeneration**: temperature = ``config.regeneration_temperature`` so the
    rewrite genuinely diverges from the rejected draft even when the human
    gives no explicit feedback.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from src.core.state import EditorialPick, GraphState, TokenUsage
from src.utils.config import PipelineConfig
from src.utils.llm import build_llm
from src.utils.logger import log_llm_usage
from src.utils.prompts import fill, load_few_shot_examples, load_prompt

logger = logging.getLogger("content_pipeline.copywriter")


def content_copywriter_node(state: GraphState, config: RunnableConfig) -> dict:
    """
    LangGraph node: generate a post from the selected pick.

    Temperature is chosen based on the mode:
      • first draft     → ``pipeline_cfg.copywriter_temperature``
      • regeneration    → ``pipeline_cfg.regeneration_temperature``

    Returns a partial state update with ``draft_post`` and a delta
    ``token_usage`` (the reducer in GraphState accumulates it).
    """
    pipeline_cfg: PipelineConfig = config["configurable"]["pipeline_config"]
    picks: list[EditorialPick] = state.get("editorial_picks", []) or []
    selected_id = state.get("selected_pick_id")

    if not picks:
        logger.error("No editorial picks in state — cannot generate a post.")
        return {
            "draft_post": "",
            "token_usage": TokenUsage(),
        }

    chosen: EditorialPick | None = next(
        (p for p in picks if p.id == selected_id), None
    )
    if chosen is None:
        logger.warning(
            "selected_pick_id=%s not found among pick IDs %s — falling back to first pick.",
            selected_id,
            [p.id for p in picks],
        )
        chosen = picks[0]

    feedback = (state.get("regeneration_feedback") or "").strip()
    # On a revision pass the previous (rejected) draft is still in state until
    # this node overwrites it
    previous = (state.get("draft_post") or "").strip() if feedback or state.get("human_approved") is False else ""
    is_revision = bool(feedback or previous)

    few_shot_block = load_few_shot_examples(
        prompts_dir=pipeline_cfg.prompts_dir
    ) or (
        "(no reference example available — follow the STRUCTURE and "
        "HARD RULES below strictly)"
    )

    system_prompt = fill(
        load_prompt("system_copywriter", pipeline_cfg.prompts_dir),
        few_shot_examples=few_shot_block,
        headline=chosen.headline,
        summary=chosen.summary,
        relevance=chosen.relevance,
        sources=", ".join(chosen.source_urls) or "—",
    )
    if is_revision:
        system_prompt += "\n\n" + fill(
            load_prompt("revision_block", pipeline_cfg.prompts_dir),
            previous_draft=previous or "(no previous draft available)",
            regeneration_feedback=feedback or "(no specific feedback — rewrite freely)",
        )

    user_msg = (
        "Rewrite the post taking the revision request into account."
        if is_revision
        else "Write the post based on the editorial brief above."
    )

    chosen_temperature = (
        pipeline_cfg.regeneration_temperature if is_revision
        else pipeline_cfg.copywriter_temperature
    )
    llm = build_llm(pipeline_cfg, temperature=chosen_temperature)
    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_msg),
    ])

    step_usage = TokenUsage()
    log_llm_usage(response, usage=step_usage, step_name="content_copywriter")

    draft = response.content.strip()
    logger.info(
        "Content Copywriter generated a %d-word post%s (temp=%.2f).",
        len(draft.split()),
        " (revision)" if is_revision else "",
        chosen_temperature,
    )

    return {
        "draft_post": draft,
        # Clear regeneration inputs so an old feedback never re-applies on a
        # subsequent run; the human supplies fresh feedback for each loop.
        "regeneration_feedback": "",
        "token_usage": step_usage,
    }
