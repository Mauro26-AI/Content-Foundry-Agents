"""
Trend Scout Agent — Search & Discovery.

Runs every search query listed in ``prompts/search_topics.md`` against
Tavily in parallel and returns a deduplicated list of ``NewsItem`` objects
into the graph state.

Dedup strategy:
  Jaccard similarity over the lowercased word sets of article titles.
  Items are processed in insertion order; the first article in a
  near-duplicate cluster is kept.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from tenacity import retry, stop_after_attempt, wait_exponential

from langchain_core.runnables import RunnableConfig

from src.core.state import GraphState, NewsItem
from src.tools.search import build_search_tool
from src.utils.config import PipelineConfig
from src.utils.prompts import load_search_queries

logger = logging.getLogger("content_pipeline.trend_scout")


def _safe_source(url: str) -> str:
    """Return the registered domain from a URL, or 'unknown' if missing."""
    netloc = urlparse(url or "").netloc.lower().removeprefix("www.")
    return netloc or "unknown"


def _deduplicate_by_jaccard(items: list[dict]) -> list[dict]:
    """
    Remove near-duplicate articles by Jaccard similarity on title word sets.

    Items are processed in insertion order; the first occurrence of any
    near-duplicate cluster is kept.
    """
    if len(items) <= 1:
        return items

    token_sets: list[set[str]] = [
        set(re.findall(r"\w+", (it.get("title") or "").lower())) for it in items
    ]

    kept: list[int] = []
    for i, tokens_i in enumerate(token_sets):
        is_dup = False
        for j in kept:
            tokens_j = token_sets[j]
            union = tokens_i | tokens_j
            if not union:
                continue
            if len(tokens_i & tokens_j) / len(union) >= 0.7:
                is_dup = True
                break
        if not is_dup:
            kept.append(i)
    return [items[i] for i in kept]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _search_with_retry(search_tool, query: str, max_results: int) -> list[dict]:
    response = search_tool.search(
        query=query,
        max_results=max_results,
        search_depth="advanced",
        include_answer=True,
    )
    return response.get("results", []) if isinstance(response, dict) else []


def _run_query(search_tool, query: str, max_results: int) -> list[dict]:
    try:
        return _search_with_retry(search_tool, query, max_results)
    except Exception as exc:
        logger.warning("Search failed for '%s' after retries: %s", query, exc)
        return []


def trend_scout_node(state: GraphState, config: RunnableConfig) -> dict:
    """
    LangGraph node: run all search queries in parallel and consolidate results.

    Pipeline:
      1. Fan-out N search queries on a thread pool.
      2. Deduplicate by Jaccard similarity on title word sets (threshold 0.7).
    """
    pipeline_cfg: PipelineConfig = config["configurable"]["pipeline_config"]
    search_tool = build_search_tool(pipeline_cfg)
    queries = load_search_queries(pipeline_cfg.prompts_dir)
    if not queries:
        logger.error("No search queries configured — check prompts/search_topics.md.")
        return {"raw_news": []}

    # Fan-out: all queries in parallel
    raw: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(queries)) as executor:
        futures = {
            executor.submit(_run_query, search_tool, q, pipeline_cfg.max_search_results): q
            for q in queries
        }
        for future in as_completed(futures):
            query = futures[future]
            results = future.result()
            logger.debug("Query '%s' returned %d results.", query, len(results))
            raw.extend(results)

    # Single dedup pass
    deduped = _deduplicate_by_jaccard(raw)
    dropped = len(raw) - len(deduped)

    all_items: list[NewsItem] = []
    for idx, item in enumerate(deduped, start=1):
        url = item.get("url", "")
        all_items.append(
            NewsItem(
                id=idx,
                title=item.get("title", "Untitled"),
                url=url,
                snippet=item.get("content", "")[:500],
                source=_safe_source(url),
            )
        )

    logger.info(
        "Trend Scout: kept=%d  deduped=%d", len(all_items), dropped
    )

    return {"raw_news": all_items}
