"""
Configuration management for the content pipeline.

Centralizes environment variable loading, model selection, and LangSmith
tracing settings.

Default provider: Google Gemini 2.5 Flash (free tier).
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class PipelineConfig:
    """
    Runtime configuration for the multi-agent pipeline.

    Immutable on purpose: pass it once into the graph and never mutate (frozen=True).
    """

    # LLM
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "google")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gemini-2.5-flash")
    )
    # Per-agent temperatures: The Strategist runs cold (deterministic curation);
    # the Copywriter runs hotter on the first draft for stylistic variance, and
    # hotter still on a regeneration so the rewrite materially diverges from
    # the rejected draft even when the human gives no explicit feedback.
    strategist_temperature: float = 0.4
    copywriter_temperature: float = 0.7
    regeneration_temperature: float = 0.85

    # Search
    tavily_api_key: str = field(
        default_factory=lambda: os.getenv("TAVILY_API_KEY", "")
    )
    max_search_results: int = 10

    # Editorial
    max_editorial_picks: int = 5

    # Prompts
    prompts_dir: str = field(
        default_factory=lambda: os.getenv("PROMPTS_DIR", "prompts")
    )

    # Branding
    # Used in GitHub Issue titles and bodies opened by the pipeline.
    project_name: str = field(
        default_factory=lambda: os.getenv("PROJECT_NAME", "Content Foundry Agents")
    )

    # LangSmith Tracing
    langsmith_tracing: bool = field(
        default_factory=lambda: os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
    )
    langsmith_project: str = field(
        default_factory=lambda: os.getenv("LANGSMITH_PROJECT", "content-foundry")
    )

    # Output
    output_dir: str = field(
        default_factory=lambda: os.getenv("OUTPUT_DIR", "posts")
    )

    def __post_init__(self) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
