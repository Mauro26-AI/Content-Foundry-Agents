"""
Web search tools for the Trend Scout agent.
"""

from tavily import TavilyClient
from src.utils.config import PipelineConfig


def build_search_tool(config: PipelineConfig) -> TavilyClient:
    """
    Construct a Tavily client configured for retrieval.
    """
    return TavilyClient(api_key=config.tavily_api_key)
