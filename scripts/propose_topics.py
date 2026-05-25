"""
Phase 1: Propose Topics — opens a GitHub Issue for human review.

Called on a schedule by the cron workflow. Runs the Trend Scout and
News Strategist agents, then creates a GitHub Issue listing all
editorial picks so the user can reply with /approve <id>.
"""

import logging
import sys
from datetime import datetime, timezone

from src.core.graph import build_graph
from src.core.state import TokenUsage, make_initial_state
from src.utils.config import PipelineConfig
from src.utils.github import create_issue, picks_to_json_block
from src.utils.logger import format_usage_report
from src.utils.tracing import configure_langsmith, get_run_metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("content_pipeline.propose")


def _create_github_issue(picks: list, today: str, project_name: str) -> int | None:
    """
    Open a GitHub Issue with the editorial picks formatted as a checklist.

    Returns the issue number or None if the API call fails.
    """
    body_lines = [
        f"## 📰 {project_name} — Editorial Picks for {today}\n",
        "The pipeline scanned today's landscape and curated these editorial angles.\n",
        "**Reply with `/approve <id>` to generate a post from that topic.**\n",
        "**Reply with `/reject` to skip today.**\n",
        "---\n",
    ]

    for pick in picks:
        sources = (
            ", ".join(f"[link]({url})" for url in pick.source_urls)
            if pick.source_urls else "—"
        )
        body_lines.append(
            f"### [{pick.id}] {pick.headline}\n\n"
            f"{pick.summary}\n\n"
            f"💡 **Why it matters:** {pick.relevance}\n\n"
            f"🔗 Sources: {sources}\n\n"
            f"---\n"
        )
        
    body_lines.append(f"\n{picks_to_json_block(picks)}")

    return create_issue(
        title=f"📰 Editorial Picks — {today}",
        body="\n".join(body_lines),
        labels=["ai-curator", "human-in-the-loop"],
    )


def propose() -> bool:
    """
    Run Phase 1: search + curation, then open a GitHub Issue.

    Returns True if the Issue was created successfully.
    """
    pipeline_cfg = PipelineConfig()
    configure_langsmith(pipeline_cfg)
    run_metadata = get_run_metadata(run_type="github_action")

    graph = build_graph()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    thread_config = {
        "configurable": {
            "thread_id": f"propose-{today}",
            "pipeline_config": pipeline_cfg,
        },
        "metadata": run_metadata,
    }

    initial_state = make_initial_state()

    logger.info("Phase 1: Scanning landscape for %s", today)
    result = graph.invoke(initial_state, thread_config)

    picks = result.get("editorial_picks", [])
    if not picks:
        logger.error("No editorial picks generated. Aborting.")
        return False

    logger.info("Got %d picks. Opening GitHub Issue...", len(picks))
    usage = result.get("token_usage", TokenUsage())
    print(format_usage_report(usage))

    issue_number = _create_github_issue(picks, today, pipeline_cfg.project_name)

    return issue_number is not None


if __name__ == "__main__":
    ok = propose()
    sys.exit(0 if ok else 1)
