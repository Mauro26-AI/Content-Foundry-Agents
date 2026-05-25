# Content Foundry Agents

**A multi-agent system for automated text content creation with Human-in-the-Loop control.**

Three specialized AI agents collaborate to turn raw web signals into publication-ready content — while keeping a human in control of every editorial decision that matters. The system handles the mechanical work (searching, curating, drafting); you handle the judgment (which angle, whether to publish).

The pipeline is **fully channel-agnostic and audience-agnostic**. The agents are completely customizable — topic areas, audience, voice, format, length — by editing five Markdown files in [`prompts/`](./prompts). The same codebase produces a LinkedIn post, a newsletter section, a blog draft, or a Twitter thread depending on what those files say.

**Default LLM: Google Gemini 2.5 Flash — free tier.**

---

## How it works

Three agents run in sequence, with two mandatory human checkpoints:

```
┌──────────────┐    ┌─────────────────┐    ⏸ You choose     ┌──────────────────────┐    ⏸ You approve
│ Trend Scout  │───▶│ News Strategist │──────an angle ─────▶│  Content Copywriter  │──────or regen ──▶ saved content
│ N parallel   │    │ LLM curation    │                      │ LLM generation       │
│ web searches │    │                 │                      │                      │
└──────────────┘    └─────────────────┘                      └──────────────────────┘
   Tavily API           your LLM                                  your LLM
```

1. **Trend Scout** runs every query from `prompts/search_topics.md` in parallel via Tavily, canonicalises URLs, and drops near-duplicate titles via Jaccard similarity — all before a single LLM token is spent.
2. **News Strategist** sends the deduplicated articles to the LLM with your editorial priorities (from `prompts/system_strategist.md`) and proposes N curated angles.
3. **You pick** which topic to develop.
4. **Content Copywriter** generates content following the structure, and constraints you defined in `prompts/system_copywriter.md` and `prompts/post_example.md`. You approve, regenerate with feedback, or discard.

---

## Customising the pipeline

**You shape what the system writes — and how — by editing five Markdown files in [`prompts/`](./prompts).**

| File | What it controls |
|------|-----------------|
| `prompts/search_topics.md`     | What the Trend Scout searches for. One query per line. |
| `prompts/system_strategist.md` | Who your reader is and what editorial priorities apply. |
| `prompts/system_copywriter.md` | The structure, format and constraints of the final content. |
| `prompts/revision_block.md`    | What gets injected when you ask for a regeneration. |
| `prompts/post_example.md`      | A concrete example of the output style you want (few-shot). |

See [prompts/README.md](./prompts/README.md) for placeholder syntax and a guide to re-targeting the pipeline for a different niche.

---

## Execution modes

The same agents run in two modes — local and automated.

### Mode 1 — FastAPI + Streamlit (local, interactive)

FastAPI owns the graph and the in-memory checkpointer. Streamlit is a thin HTTP client.

```bash
# terminal 1 — REST API on http://localhost:8000
uvicorn api.main:app --reload --port 8000

# terminal 2 — UI on http://localhost:8501
streamlit run ui/app.py
```

REST endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/runs` | Start Phase 1 (Scout + Strategist); returns picks |
| `GET`  | `/runs/{thread_id}` | Snapshot of the current state |
| `POST` | `/runs/{thread_id}/pick` | Select an editorial pick → drafts the content |
| `POST` | `/runs/{thread_id}/approve` | Finalize + save to `posts/` |
| `POST` | `/runs/{thread_id}/regenerate` | Rewrite with optional feedback |
| `POST` | `/runs/{thread_id}/discard` | Close run without saving |

---

### Mode 2 — GitHub Actions (asynchronous, automated)

Two coordinated workflows glued together by a GitHub Issue acting as a persistent state-store:

```
[Cron — every Monday by default]
    weekly_propose.yml
        → Trend Scout + News Strategist
        → Opens a GitHub Issue with editorial picks

[You — on the Issue, as a comment]
    /approve N             →  approve_generate.yml ▸ generate
                                  → Copywriter generates content
                                  → Commits to posts/YYYY-MM-DD.md
                                  → Closes Issue

    /reject                →  approve_generate.yml ▸ reject
                                  → Closes Issue, no content generated

    /regenerate N feedback →  approve_generate.yml ▸ regenerate
                                  → Copywriter rewrites with feedback
                                  → Posts revised draft as Issue comment
                                  → Does NOT commit, does NOT close
                                  → Iterate as many times as needed
```

**Why this design?**
- The Issue is the persistent state-store between phases. Phase 1 can fail and be re-run without triggering Phase 2.
- The human review window is unbounded — approve days later if you want.
- The `/regenerate` loop is non-destructive: each revision lands as an Issue comment; content is only written on `/approve`.
- No polling, no extra infrastructure. Mobile notifications come via the GitHub mobile app.

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- API keys: **Google Gemini** (free) + **Tavily** (free)

### Installation

```bash
git clone <repo-url>
cd content-foundry-agents

uv sync

cp .env.example .env
# Edit .env — minimum required: GOOGLE_API_KEY and TAVILY_API_KEY
```

Free API keys:
- **Google Gemini** → [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
- **Tavily** → [tavily.com](https://tavily.com)

### Customise the prompts

Open `prompts/` and edit the five files to match your audience, topics and target format. The defaults are empty templates — fill them in with your own editorial intent before running.

### Verify the install

```bash
python scripts/smoke_test.py           # all checks (Python, imports, env, prompts, LLM, Tavily)
python scripts/smoke_test.py --no-llm  # env + imports + prompts only (no live API calls)
```

---

## GitHub Actions Setup

1. Push the repo to GitHub.
2. Create the label `ai-curator` under Issues → Labels (or via `gh label create ai-curator`).
3. Add secrets under Settings → Secrets and variables → Actions:

| Secret | Required | Value |
|--------|----------|-------|
| `LLM_PROVIDER` | Yes | `google` or `openai` |
| `LLM_MODEL` | Yes | e.g. `gemini-2.5-flash` or `gpt-4o` |
| `GOOGLE_API_KEY` | If provider=google | Google AI Studio key |
| `OPENAI_API_KEY` | If provider=openai | OpenAI key |
| `TAVILY_API_KEY` | Yes | Tavily key |
| `LANGSMITH_TRACING` | Optional | `true` or `false` |
| `LANGSMITH_API_KEY` | Optional | LangSmith key |
| `LANGSMITH_PROJECT` | Optional | Project name in LangSmith |

Optionally add a **Repository Variable** `PROJECT_NAME` to brand the Issues the pipeline opens.

> `GITHUB_TOKEN` is injected automatically — do not add it.

4. Trigger manually: Actions → "📰 Weekly: Propose Topics" → Run workflow.

### Schedule

Edit `.github/workflows/weekly_propose.yml` to change the cadence:

```yaml
on:
  schedule:
    - cron: "0 7 * * 1"      # Weekly — every Monday at 07:00 UTC  ← default
    # - cron: "0 7 * * *"    # Daily
    # - cron: "0 7 */3 * *"  # Every 3 days
  workflow_dispatch:           # Always keep this — allows manual trigger
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Agent orchestration | LangGraph (StateGraph, interrupt, MemorySaver) |
| LLM | Gemini 2.5 Flash (default, free) / GPT-4o |
| Web search | Tavily API (free tier, 1000 req/month) |
| Package manager | uv + pyproject.toml |
| State persistence | LangGraph MemorySaver (local) / GitHub Issue (async) |
| API layer | FastAPI + uvicorn |
| Observability | LangSmith (optional, free tier) |
| CI/CD + async HITL | GitHub Actions + Issues |
| Dashboard | Streamlit (HTTP client of the API) |
| Language | Python 3.11+ |

---

## License

MIT
