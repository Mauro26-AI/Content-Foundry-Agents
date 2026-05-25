# Prompts

This directory holds **every prompt** the pipeline uses. The Python agents are
generic — they read these files and substitute placeholders. To repurpose the
project for a different audience, channel, language or content format, you
only need to edit the files in this folder. No code changes required.

## Files

| File | Used by | What to put in it |
|------|---------|-------------------|
| `search_topics.md`     | Trend Scout            | One search query per line. Lines starting with `#` are comments. Optimise for *recall* (multiple synonyms, year markers); the Strategist does the precision pass. |
| `system_strategist.md` | News Strategist        | System prompt that defines your audience, the editorial priorities, and what to avoid. Placeholder: `{max_picks}`. |
| `system_copywriter.md` | Content Copywriter     | System prompt with voice, structural rules, length, and any platform constraints (LinkedIn / Twitter thread / blog post / newsletter…). Placeholders: `{few_shot_examples}`, `{headline}`, `{summary}`, `{relevance}`, `{sources}`. |
| `revision_block.md`    | Content Copywriter     | Appended to the copywriter prompt when the human asks for a regeneration. Placeholders: `{previous_draft}`, `{regeneration_feedback}`. |
| `post_example.md`      | Content Copywriter     | One or more **few-shot examples** of the final post style you want. Separate multiple examples with a bare `---` line preceded by a blank line. |

## Placeholders

Placeholders are written `{name}` and replaced via `str.replace` (not
`str.format`). This means **literal curly braces in your prompt are safe** —
you can paste JSON, code snippets or set notation without escaping.

Only the placeholders listed in the table above are recognised. Anything else
inside `{…}` is left untouched.

## Example: re-targeting the project

To turn this pipeline into a "Kubernetes weekly digest" for SRE blog readers:

1. Replace the queries in `search_topics.md`:
   ```
   Kubernetes 1.30 release notes operator pattern 2026
   GitOps Argo CD Flux production lessons
   eBPF observability service mesh Cilium
   ```
2. Rewrite `system_strategist.md` to describe the SRE audience and what
   topics matter (rollouts, incident retros, cost, security).
3. Rewrite `system_copywriter.md` to target a 600-word technical blog post
   with H2 headings instead of a 300-word LinkedIn post.
4. Replace `post_example.md` with one of your own past blog posts.

No Python changes. Re-run the pipeline.
