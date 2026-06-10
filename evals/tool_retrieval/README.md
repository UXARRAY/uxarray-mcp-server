# Tool-retrieval eval

## What this measures (plain language)

When an AI assistant has many tools to choose from, it has to pick the
right one for each user request. This is the same problem a person faces
opening a new menu in unfamiliar software: with five items, you scan all of
them; with fifty, you grep. Language models are no different.

Today, the MCP server exposes **11 tools** to clients (intent-shaped front
doors like `run_analysis`, `plot_dataset`, `analyze_dataset`). Under the
hood there are **~45 lower-level functions** (the `__all__` list in
`uxarray_mcp.tools`) that the front doors fan out to. Future versions may
expose more of that surface directly, especially if libraries like
ToolRegistry land a retrieval layer that fetches a relevant subset on
demand.

**The question this eval answers:** if we ask a simple retriever (BM25 — a
classic text-matching score, like what powers Elasticsearch and Lucene) to
pick the right tool from a list of N tool descriptions given a
natural-language prompt, how often does it get it right?

If the answer is "almost always" with the current catalog, the architecture
is safe to grow. If the answer is "rarely," we either keep the visible
surface small or invest in semantic (embedding-based) retrieval.

## What "good" looks like

For ~30 hand-written prompts, each labeled with the one tool that should
answer it:

- **Top-1 accuracy >90%** = naive retrieval works; deferred-tool catalog
  is safe.
- **Top-1 70–90%, top-3 >95%** = ranking is good enough if we let the AI
  pick from the top 3 retrieved tools.
- **Top-1 <70%** = naive text matching is not enough; need semantic
  retrieval (embeddings) or keep the surface small.

## What BM25 is, in one paragraph

BM25 is a 30-year-old text retrieval algorithm. It scores a document
against a query by counting how often the query's words appear in the
document, weighted by how rare each word is across the whole document
collection (rare words count more), with a saturation curve so a document
that mentions "zonal" 50 times isn't 50× better than one that mentions it
once. It is **not** semantic — "find the trade winds" won't retrieve a tool
described as "calculate easterly atmospheric flow." It is the cheapest
possible retriever that isn't keyword-exact, and it's what most production
systems start with before reaching for embeddings.

If BM25 works well enough, we don't need the embeddings infrastructure. If
it doesn't, we have a number that justifies the cost.

## How to run

```bash
uv run python -m evals.tool_retrieval.run
```

Writes a JSON report to `evals/results/retrieval_<timestamp>.json` and
prints a summary table.

## Reading the output

For each prompt the runner prints:

```
prompt                                    expected_tool          top1   rank
"compute area-weighted zonal mean of..."  calculate_zonal_mean   ✓      1
"plot the mesh wireframe"                 plot_mesh              ✓      1
"find the curl of the wind field"         calculate_curl         ✗      2
```

The summary reports:

- `top1_accuracy` — fraction of prompts where the right tool was ranked #1.
- `top3_accuracy` — fraction where it was in the top 3.
- `top5_accuracy` — fraction where it was in the top 5.
- `mean_rank` — average rank of the correct tool (lower is better).

## Caveats

- BM25 here scores against `(name + description + parameter names)`. The
  quality of the result depends entirely on how good the descriptions are.
  If BM25 does poorly, the fix may be **better docstrings**, not a switch
  to embeddings — and that is a much cheaper fix.
- The prompt set is hand-written. A larger, more adversarial set would
  give tighter numbers. This is a *starting* measurement, not a final one.
- A real production retriever would also use the prompt's context (prior
  conversation, dataset state). This eval is the worst case: cold query,
  no context.
