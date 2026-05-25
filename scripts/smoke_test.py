"""
Smoke test suite for the content pipeline.

Verifies that each component works end-to-end before running the full pipeline.

Exit code: 0 if all checks pass, 1 if any fail.
"""

import argparse
import sys
import traceback
from dataclasses import dataclass
from typing import Callable


# Result container

@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str


# Individual checks

def check_python_version() -> CheckResult:
    """Python 3.11+ is required."""
    info = sys.version_info
    version_str = f"{info.major}.{info.minor}.{info.micro}"
    if info >= (3, 11):
        return CheckResult("Python version", True, f"Python {version_str} — OK")
    return CheckResult(
        "Python version", False,
        f"Python {version_str} — need 3.11+.",
    )


def check_imports() -> CheckResult:
    """Key packages must be importable."""
    packages = [
        ("langgraph", "langgraph"),
        ("langchain_google_genai", "langchain-google-genai"),
        ("langchain_openai", "langchain-openai"),
        ("tavily", "tavily-python"),
        ("streamlit", "streamlit"),
        ("tenacity", "tenacity"),
        ("dotenv", "python-dotenv"),
        ("requests", "requests"),
        ("fastapi", "fastapi"),
        ("httpx", "httpx"),
        ("uvicorn", "uvicorn"),
    ]
    failed = []
    for module, pkg in packages:
        try:
            __import__(module)
        except ImportError:
            failed.append(pkg)

    if not failed:
        return CheckResult("Dependencies", True, f"All {len(packages)} packages importable — OK")
    return CheckResult(
        "Dependencies", False,
        f"Missing: {', '.join(failed)}. Run: uv sync",
    )


def check_env_vars() -> CheckResult:
    """Required environment variables must be set."""
    import os
    from dotenv import load_dotenv
    load_dotenv()

    required = ["LLM_PROVIDER", "LLM_MODEL", "TAVILY_API_KEY"]
    llm_provider = os.getenv("LLM_PROVIDER", "google")
    provider_key_map = {
        "google": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    provider_key = provider_key_map.get(llm_provider, "GOOGLE_API_KEY")
    required.append(provider_key)

    missing = [var for var in required if not os.getenv(var, "").strip()]
    if not missing:
        return CheckResult(
            "Environment variables", True,
            f"Provider={llm_provider}, model={os.getenv('LLM_MODEL')} — all required vars set",
        )
    return CheckResult(
        "Environment variables", False,
        f"Missing or empty: {', '.join(missing)}. Check your .env file.",
    )


def check_config_loads() -> CheckResult:
    """PipelineConfig must load without errors."""
    try:
        from src.utils.config import PipelineConfig
        cfg = PipelineConfig()
        return CheckResult(
            "Config load", True,
            f"PipelineConfig OK — provider={cfg.llm_provider}, model={cfg.llm_model}, project={cfg.project_name}",
        )
    except Exception as exc:
        return CheckResult("Config load", False, f"PipelineConfig failed: {exc}")


def check_prompts_present() -> CheckResult:
    """The 5 expected prompt files must exist, be non-empty, and parse correctly."""
    try:
        from src.utils.config import PipelineConfig
        from src.utils.prompts import (
            load_few_shot_examples,
            load_prompt,
            load_search_queries,
        )
        cfg = PipelineConfig()

        expected = [
            "search_topics",
            "system_strategist",
            "system_copywriter",
            "revision_block",
            "post_example",
        ]
        missing = [
            name for name in expected
            if not load_prompt(name, cfg.prompts_dir)
        ]
        if missing:
            return CheckResult(
                "Prompts", False,
                f"Missing or empty prompts: {', '.join(missing)} in {cfg.prompts_dir}/",
            )

        queries = load_search_queries(cfg.prompts_dir)
        if not queries:
            return CheckResult(
                "Prompts", False,
                f"search_topics.md parsed to 0 queries — check formatting.",
            )

        examples = load_few_shot_examples(prompts_dir=cfg.prompts_dir)
        return CheckResult(
            "Prompts", True,
            f"5 prompt files OK · {len(queries)} search queries · few-shot block {len(examples)} chars",
        )
    except Exception as exc:
        return CheckResult("Prompts", False, f"Prompt loader failed: {exc}")


def check_graph_builds() -> CheckResult:
    """Both graph constructors must compile without errors."""
    try:
        from src.core.graph import build_copywriter_only_graph, build_graph
        g1 = build_graph()
        g2 = build_copywriter_only_graph()
        nodes_full = list(g1.get_graph().nodes.keys())
        nodes_cw = list(g2.get_graph().nodes.keys())
        return CheckResult(
            "Graph compilation", True,
            f"build_graph() nodes: {nodes_full} | build_copywriter_only_graph() nodes: {nodes_cw}",
        )
    except Exception as exc:
        return CheckResult("Graph compilation", False, f"Graph build failed: {exc}")


def check_llm_connection() -> CheckResult:
    """LLM must respond to a minimal prompt."""
    try:
        from src.utils.config import PipelineConfig
        from src.utils.llm import build_llm
        cfg = PipelineConfig()
        llm = build_llm(cfg, temperature=cfg.strategist_temperature)
        resp = llm.invoke("Say hello in 5 words.")
        content = resp.content.strip()
        if not content:
            return CheckResult("LLM connection", False, "LLM returned an empty response.")
        preview = content[:80].replace("\n", " ")
        return CheckResult(
            "LLM connection", True,
            f"[{cfg.llm_provider}/{cfg.llm_model}] → \"{preview}\"",
        )
    except Exception as exc:
        return CheckResult(
            "LLM connection", False,
            f"LLM call failed: {exc}\nHint: check your API key and model name in .env",
        )


def check_tavily_search() -> CheckResult:
    """Tavily must return at least one result."""
    try:
        from src.tools.search import build_search_tool
        from src.utils.config import PipelineConfig
        cfg = PipelineConfig()
        client = build_search_tool(cfg)
        response = client.search(query="latest tech news today", max_results=3)
        results = response.get("results", []) if isinstance(response, dict) else []
        if not results:
            return CheckResult("Tavily search", False, "Search returned 0 results.")
        first_title = results[0].get("title", "(no title)")[:70]
        return CheckResult(
            "Tavily search", True,
            f"Got {len(results)} results — first: \"{first_title}\"",
        )
    except Exception as exc:
        return CheckResult(
            "Tavily search", False,
            f"Tavily call failed: {exc}\nHint: check TAVILY_API_KEY in .env",
        )


# Runner

def run_checks(skip_live: bool = False) -> list[CheckResult]:
    checks: list[tuple[str, Callable[[], CheckResult]]] = [
        ("Python version",          check_python_version),
        ("Dependencies",            check_imports),
        ("Environment variables",   check_env_vars),
        ("Config load",             check_config_loads),
        ("Prompts",                 check_prompts_present),
        ("Graph compilation",       check_graph_builds),
    ]
    if not skip_live:
        checks += [
            ("LLM connection",          check_llm_connection),
            ("Tavily search",           check_tavily_search),
        ]

    results: list[CheckResult] = []
    width = max(len(name) for name, _ in checks) + 2

    print()
    print("=" * 62)
    print("  Content Foundry Agents — Smoke Test")
    print("=" * 62)

    for name, fn in checks:
        label = f"  {name}".ljust(width + 2)
        print(f"{label} ... ", end="", flush=True)
        try:
            result = fn()
        except Exception:
            result = CheckResult(name, False, traceback.format_exc())
        results.append(result)

        print("PASS" if result.passed else "FAIL")
        if not result.passed:
            # indent the message under the check line
            for line in result.message.splitlines():
                print(f"    {line}")

    # Summary
    failed = [r for r in results if not r.passed]
    total = len(results)

    print()
    print("=" * 62)
    if not failed:
        print(f"  All {total} checks passed.")
        print("  Ready to run:")
        print("    • API     →  uvicorn api.main:app --reload --port 8000")
        print("    • UI      →  streamlit run ui/app.py")
        print("    • Actions →  configure secrets and trigger weekly_propose.yml")
    else:
        print(f"  {len(failed)} of {total} checks FAILED:")
        for r in failed:
            print(f"    • {r.name}")
        print()
        print("  Fix the issues above, then re-run: python scripts/smoke_test.py")
    print("=" * 62)
    print()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke test for the content pipeline — verifies each component before running."
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip live LLM and search checks (env + imports + prompts only).",
    )
    args = parser.parse_args()

    results = run_checks(skip_live=args.no_llm)
    failed = [r for r in results if not r.passed]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
