"""
GitHub REST API helpers — shared between Phase 1 and Phase 2 scripts.

Picks are embedded in the Issue body using invisible HTML comment delimiters
(<!-- picks-start / picks-end -->).
"""

import dataclasses
import json
import logging
import os

import requests

logger = logging.getLogger("content_pipeline.github")

_PICKS_START = "picks-start"
_PICKS_END = "picks-end"


def _env() -> tuple[str, str]:
    return os.getenv("GITHUB_TOKEN", ""), os.getenv("GITHUB_REPOSITORY", "")


def gh_headers() -> dict:
    token, _ = _env()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def create_issue(title: str, body: str, labels: list[str]) -> int | None:
    """
    Open a GitHub Issue. Returns the issue number or None on failure.
    """

    token, repo = _env()
    if not token or not repo:
        logger.error("GITHUB_TOKEN or GITHUB_REPOSITORY not set. Cannot open Issue.")
        return None

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers=gh_headers(),
        json={"title": title, "body": body, "labels": labels},
        timeout=30,
    )
    if resp.status_code == 201:
        number = resp.json()["number"]
        logger.info("Opened Issue #%d", number)
        return number
    logger.error("Failed to create Issue: %s %s", resp.status_code, resp.text)
    return None


def fetch_issue_body(issue_number: int) -> str | None:
    """
    Retrieve the issue body from the GitHub API.
    """

    token, repo = _env()
    if not token or not repo:
        logger.error("GITHUB_TOKEN or GITHUB_REPOSITORY not set.")
        return None

    resp = requests.get(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}",
        headers=gh_headers(),
        timeout=30,
    )
    if resp.status_code == 200:
        return resp.json().get("body", "")
    logger.error("Failed to fetch Issue #%d: %s", issue_number, resp.status_code)
    return None


def comment_on_issue(issue_number: int, body: str) -> None:
    """
    Post a comment on the Issue (do NOT close the issue) -> /regenerate
    """

    token, repo = _env()
    if not token or not repo:
        return

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
        headers=gh_headers(),
        json={"body": body},
        timeout=30,
    )
    if resp.status_code != 201:
        logger.error(
            "Failed to comment on Issue #%d: %s", issue_number, resp.status_code
        )


def close_issue_with_comment(issue_number: int, comment: str) -> None:
    """
    Post a comment and close the GitHub Issue -> /approve
    """

    token, repo = _env()
    if not token or not repo:
        return

    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments",
        headers=gh_headers(),
        json={"body": comment},
        timeout=30,
    )
    if resp.status_code != 201:
        logger.error(
            "Failed to comment on Issue #%d: %s", issue_number, resp.status_code
        )
        return

    resp = requests.patch(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}",
        headers=gh_headers(),
        json={"state": "closed"},
        timeout=30,
    )
    if resp.status_code == 200:
        logger.info("Closed Issue #%d", issue_number)
    else:
        logger.error("Failed to close Issue #%d: %s", issue_number, resp.status_code)


def picks_to_json_block(picks: list) -> str:
    """Serialise editorial picks inside a single HTML comment block (invisible in UI)."""
    data = [dataclasses.asdict(p) for p in picks]
    return f"<!--\n{_PICKS_START}\n{json.dumps(data, indent=2)}\n{_PICKS_END}\n-->"


def parse_picks_json(body: str) -> list[dict]:
    """
    Extract and parse the picks JSON from an Issue body.
    """

    start = body.find(_PICKS_START)
    end = body.find(_PICKS_END)
    if start == -1 or end == -1 or end <= start:
        logger.error("Could not find picks block in issue body.")
        return []

    raw = body[start + len(_PICKS_START) : end].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse picks JSON: %s", exc)
        return []
