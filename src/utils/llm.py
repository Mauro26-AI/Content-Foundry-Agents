"""
LLM factory — provider-agnostic.

All agents must instantiate their LLM via ``build_llm`` so that
timeout, retry policy, and provider routing are configured in
exactly one place.
"""

from src.utils.config import PipelineConfig


# Hard defaults applied to every LLM call.
# - timeout: max seconds to wait for a single completion.
# - max_retries: provider-side retries on transient errors (rate limits, 5xx).
LLM_TIMEOUT_SECONDS = 60
LLM_MAX_RETRIES = 2


def build_llm(config: PipelineConfig, temperature: float):
    """
    Instantiate the LLM specified in PipelineConfig.

    Providers: "google" (default, free tier), "openai".
    API keys are read from environment variables: GOOGLE_API_KEY, OPENAI_API_KEY.

    Temperature must be passed explicitly by the caller.
    """
    t = temperature

    if config.llm_provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=config.llm_model,
            temperature=t,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )

    if config.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=config.llm_model,
            temperature=t,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )

    raise ValueError(f"Unsupported LLM provider: {config.llm_provider!r}")
