"""
Token-usage logger.
"""

import logging
from datetime import datetime, timezone

from src.core.state import TokenUsage

logger = logging.getLogger("content_pipeline.cost")


def log_llm_usage(
    response,
    *,
    usage: TokenUsage,
    step_name: str,
) -> None:
    """
    Extract token counts from an LLM response and update the running accumulator.

    Supports OpenAI-style ``response_metadata`` and the newer
    ``usage_metadata`` format used by some providers.
    """
    prompt_tokens = 0
    completion_tokens = 0

    if hasattr(response, "response_metadata"):
        meta = response.response_metadata.get("token_usage", {})
        prompt_tokens = meta.get("prompt_tokens", 0)
        completion_tokens = meta.get("completion_tokens", 0)

    if hasattr(response, "usage_metadata") and prompt_tokens == 0:
        meta = response.usage_metadata or {}
        prompt_tokens = meta.get("input_tokens", 0)
        completion_tokens = meta.get("output_tokens", 0)

    usage.add(prompt_tokens, completion_tokens)

    logger.info(
        "[%s] %s | in=%d  out=%d",
        datetime.now(timezone.utc).strftime("%H:%M:%S"),
        step_name,
        prompt_tokens,
        completion_tokens,
    )


def format_usage_report(usage: TokenUsage) -> str:
    """Return a human-readable token summary string."""
    return (
        f"\nTOKEN USAGE — prompt: {usage.prompt_tokens:,} | "
        f"completion: {usage.completion_tokens:,} | "
        f"total: {usage.total_tokens:,}\n"
    )
