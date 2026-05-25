"""
Prompt loader — externalises agent prompts into ``prompts/*.md`` files.

Caching: prompts are read once and cached for the lifetime of the process
via ``lru_cache``. The prompts directory is small and the agents read the
same files on every invocation, so caching avoids needless IO.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("content_pipeline.prompts")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PROMPTS_DIR: str = os.getenv("PROMPTS_DIR", "prompts")


def _resolve_dir(prompts_dir: str | Path) -> Path:
    """Helper: Resolve a prompts directory relative to the project root."""
    p = Path(prompts_dir)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


@lru_cache(maxsize=10)
def load_prompt(name: str, prompts_dir: str = DEFAULT_PROMPTS_DIR) -> str:
    """
    Read a prompt file from the prompts directory and return its raw text.
    """
    path = _resolve_dir(prompts_dir) / f"{name}.md"
    if not path.exists():
        logger.warning("Prompt file not found: %s", path)
        return ""
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=4)
def load_search_queries(prompts_dir: str = DEFAULT_PROMPTS_DIR) -> tuple[str, ...]:
    """
    Parse ``search_topics.md``: one search query per line.
    """
    raw = load_prompt("search_topics", prompts_dir)
    if not raw:
        return ()
    queries = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return tuple(queries)


def load_few_shot_examples(name: str = "post_example", prompts_dir: str = DEFAULT_PROMPTS_DIR) -> str:
    """
    Load a few-shot example file and wrap each example in ``<example>`` tags.

    Multiple examples can live in the same file, separated by a bare
    ``---`` divider line preceded by a blank line (``\\n---\\n\\n``).
    """
    raw = load_prompt(name, prompts_dir)
    if not raw:
        return ""

    chunks = [c.strip() for c in raw.split("\n---\n\n") if c.strip()] or [raw]
    return "\n\n".join(
        f'<example index="{i + 1}">\n{c}\n</example>'
        for i, c in enumerate(chunks)
    )


def fill(template: str, **values: str) -> str:
    """
    Substitution uses ``str.replace`` rather than ``str.format`` or Jinja2
    because the prompts are free-form Markdown and routinely contain literal
    ``{`` / ``}`` characters (code snippets, JSON examples, set notation).
    """
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", val)
    return out
