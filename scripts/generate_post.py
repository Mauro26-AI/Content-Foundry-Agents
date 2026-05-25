"""
Phase 2: Generate Post — triggered by human approval on a GitHub Issue.

Parses the /approve <id> command from the issue comment, extracts
the editorial picks from the issue body and either commits the result to ``posts/``.
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.core.graph import build_copywriter_only_graph
from src.core.state import EditorialPick, TokenUsage, make_initial_state
from src.utils.config import PipelineConfig
from src.utils.github import (
    close_issue_with_comment,
    comment_on_issue,
    fetch_issue_body,
    parse_picks_json,
)
from src.utils.logger import format_usage_report
from src.utils.tracing import configure_langsmith, get_run_metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("content_pipeline.generate")


# Picks extraction

def _extract_picks(body: str) -> list[EditorialPick]:
    """Parse picks JSON from the Issue body and convert to EditorialPick objects."""
    data = parse_picks_json(body)
    return [
        EditorialPick(
            id=p["id"],
            headline=p["headline"],
            summary=p["summary"],
            relevance=p["relevance"],
            source_urls=p.get("source_urls", []),
        )
        for p in data
    ]


# Main generate

def generate(
    issue_number: int,
    pick_id: int,
    feedback: str = "",
    preview: bool = False,
) -> Path | None:
    """
    Run Phase 2: generate a post from the approved pick.

    Parameters
    ----------
    issue_number : int
        GitHub Issue to read the picks from and report back to.
    pick_id : int
        Which editorial pick to develop.
    feedback : str, optional
        Free-text guidance for the rewrite. Setting this puts the
        Copywriter into "revision mode" (revision block + higher temp).
    preview : bool, optional
        If True, do NOT commit to disk and do NOT close the Issue; post
        the draft as a comment on the Issue. Used by ``/regenerate`` so
        the human can iterate before approving.

    Returns
    -------
    Path | None
        Path of the saved file in commit mode, ``None`` in preview mode
        (or on failure). The workflow only commits the post when this
        returns a path.
    """
    pipeline_cfg = PipelineConfig()
    configure_langsmith(pipeline_cfg)
    run_metadata = get_run_metadata(run_type="github_action")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M")

    body = fetch_issue_body(issue_number)
    if not body:
        return None

    picks = _extract_picks(body)
    if not picks:
        return None

    chosen = next((p for p in picks if p.id == pick_id), None)
    if chosen is None:
        logger.error("Pick ID %d not found in Issue #%d", pick_id, issue_number)
        msg = f"Pick ID `{pick_id}` not found. Valid IDs: {[p.id for p in picks]}"
        if preview:
            comment_on_issue(issue_number, msg)
        else:
            close_issue_with_comment(issue_number, msg)
        return None

    mode = "regenerate (preview)" if preview else "approve (commit)"
    logger.info(
        "Mode=%s · Generating post for pick #%d: %s", mode, pick_id, chosen.headline
    )

    # Copywriter-only graph: no search, no strategist, no interrupts.
    graph = build_copywriter_only_graph()
    thread_config = {
        "configurable": {
            "thread_id": (
                f"{'preview' if preview else 'commit'}-{today}-issue{issue_number}-pick{pick_id}"
            ),
            "pipeline_config": pipeline_cfg,
        },
        "metadata": run_metadata,
    }

    initial_state = make_initial_state()
    initial_state["editorial_picks"] = picks
    initial_state["selected_pick_id"] = pick_id
    if feedback:
        # The Copywriter sees `regeneration_feedback` non-empty and switches
        # into revision mode (revision block + higher temperature).
        initial_state["regeneration_feedback"] = feedback

    result = graph.invoke(initial_state, thread_config)

    draft = result.get("draft_post", "")
    if not draft:
        logger.error("Copywriter produced an empty draft.")
        msg = "Copywriter failed to generate a post. Check logs."
        if preview:
            comment_on_issue(issue_number, msg)
        else:
            close_issue_with_comment(issue_number, msg)
        return None

    usage = result.get("token_usage", TokenUsage())
    print(format_usage_report(usage))

    if preview:
        # No commit, no close — post draft as Issue comment.
        _post_preview(issue_number, chosen, draft, usage, feedback)
        return None

    filepath = _commit_final(today, issue_number, chosen, draft, usage, pipeline_cfg)
    return filepath


def _commit_final(
    today: str,
    issue_number: int,
    chosen: EditorialPick,
    draft: str,
    usage: TokenUsage,
    pipeline_cfg: PipelineConfig,
) -> Path:
    """Write the final post to disk and close the Issue."""
    filepath = Path(pipeline_cfg.output_dir) / f"{today}.md"
    repo = os.getenv("GITHUB_REPOSITORY", "")
    repo_attribution = (
        f"[{pipeline_cfg.project_name}](https://github.com/{repo})"
        if repo
        else pipeline_cfg.project_name
    )

    content = (
        f"# {chosen.headline}\n\n"
        f"> Generated on {today} by {repo_attribution}"
        f" · Approved from Issue #{issue_number}\n\n"
        f"## Post\n\n{draft}\n\n"
        f"---\n\n"
        f"## Metadata\n\n"
        f"- **Topic**: {chosen.headline}\n"
        f"- **Summary**: {chosen.summary}\n"
        f"- **Sources**: {', '.join(chosen.source_urls)}\n\n"
        f"## Token Usage\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Prompt tokens | {usage.prompt_tokens:,} |\n"
        f"| Completion tokens | {usage.completion_tokens:,} |\n"
        f"| Total tokens | {usage.total_tokens:,} |\n"
    )
    filepath.write_text(content, encoding="utf-8")
    logger.info("Post saved to %s", filepath)

    close_issue_with_comment(
        issue_number,
        f"Post generated and committed!\n\n"
        f"**Topic**: {chosen.headline}\n"
        f"**File**: `posts/{today}.md`\n"
        f"**Tokens**: {usage.total_tokens:,}",
    )

    return filepath


def _post_preview(
    issue_number: int,
    chosen: EditorialPick,
    draft: str,
    usage: TokenUsage,
    feedback: str,
) -> None:
    """Post the regenerated draft as a comment on the Issue."""
    feedback_block = f"**Feedback applied:** {feedback}\n\n" if feedback else ""
    body = (
        f"Regenerated draft for pick #{chosen.id} — preview, not committed.\n\n"
        f"{feedback_block}"
        f"---\n\n"
        f"{draft}\n\n"
        f"---\n\n"
        f"*{usage.total_tokens:,} tokens*\n\n"
        f"Send `/approve {chosen.id}` to commit this version, "
        f"or `/regenerate {chosen.id} <new feedback>` to iterate."
    )
    comment_on_issue(issue_number, body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate post from approved pick")
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--pick-id", type=int, required=True)
    parser.add_argument(
        "--feedback",
        type=str,
        default="",
        help="Optional rewrite feedback (triggers Copywriter revision mode).",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Do not commit / do not close. Post the draft as a comment "
            "on the Issue (used by /regenerate)."
        ),
    )
    args = parser.parse_args()

    result = generate(
        args.issue_number,
        args.pick_id,
        feedback=args.feedback,
        preview=args.preview,
    )
    # In preview mode we consider success regardless of return value as long
    # as no exception bubbled up — the comment has already been posted.
    if args.preview:
        sys.exit(0)
    sys.exit(0 if result else 1)
