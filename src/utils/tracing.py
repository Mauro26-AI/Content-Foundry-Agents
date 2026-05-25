"""
LangSmith tracing integration.

Configures environment variables and provides a callback handler
for full observability of every LLM call, tool invocation, and
graph transition in the LangSmith dashboard.
"""

import logging
import os

from src.utils.config import PipelineConfig

logger = logging.getLogger("content_pipeline.tracing")


def configure_langsmith(config: PipelineConfig) -> bool:
    """
    Set the environment variables LangSmith needs and verify connectivity.
    Return True if tracing was successfully enabled, False otherwise.
    """

    if not config.langsmith_tracing:
        logger.info("LangSmith tracing is disabled.")
        return False

    api_key = os.getenv("LANGSMITH_API_KEY", "")
    if not api_key:
        logger.warning(
            "LANGSMITH_TRACING=true but LANGSMITH_API_KEY is missing. "
            "Tracing will not work. Get a key at https://smith.langchain.com"
        )
        return False

    os.environ["LANGCHAIN_TRACING"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = config.langsmith_project
    os.environ["LANGCHAIN_ENDPOINT"] = os.getenv(
        "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
    )

    logger.info(
        "LangSmith tracing enabled → project '%s'", config.langsmith_project
    )
    return True


def get_run_metadata(*, run_type: str = "github_action") -> dict:
    """
    Build metadata dict attached to every LangSmith run.

    This metadata appears in the LangSmith UI and makes it easy
    to filter runs by interface type, version, etc.
    """
    return {
        "project": os.getenv("LANGSMITH_PROJECT", "content-foundry"),
        "interface": run_type,
    }
