# Evals

This folder holds **evaluations** ("evals" for short) of the MCP server's
behavior. The goal is to turn opinions about how the server should behave
into **numbers** that can be re-measured when the code changes — the same
way `tests/` turns "the code should be correct" into a runnable assertion.

## What is an "eval"? (for non-AI-engineers)

In AI-driven software, an **eval** is the same thing a unit test is in
regular software, with one wrinkle: the system under test includes a
language model whose output is not bit-for-bit reproducible. So an eval
scores aggregate behavior across many inputs ("on this set of 20 prompts,
18 picked the right tool") rather than asserting one specific output.

You write an eval the same way you write a regression test:

1. Pick a behavior you care about. ("The server should reject a malformed
   request before it spends compute on it.")
2. Build a small fixed set of inputs that exercise that behavior. (Say, 20
   deliberately-wrong prompts.)
3. Run them through the system and record a numeric score.
4. Commit the inputs, the runner, and the result so the next person can
   re-run and compare.

Evals do **not** prove correctness. They measure *how often* the system
does the right thing on a fixed sample. They are most useful for catching
regressions ("we used to pick the right tool 90% of the time, now it's
60%") and for putting numbers on architectural decisions.

## What's in here

| Folder | What it measures |
|---|---|
| [`schema_rejection/`](schema_rejection/) | How often the typed tool boundary catches malformed calls before any work happens — the "did we waste compute on garbage?" number |
| [`tool_retrieval/`](tool_retrieval/) | How often a simple text retriever (BM25) finds the right tool by description — the "is our tool catalog still navigable as it grows?" number |

Both run end-to-end in under 30 seconds on a laptop with no external
dependencies. They are cheap enough to add to CI.

## How to run

```bash
uv run python -m evals.schema_rejection.run
uv run python -m evals.tool_retrieval.run
```

Each runner writes a JSON file under `results/` named with a timestamp.
Result files are gitignored — they regenerate on each run; the runner
itself is the source of truth.

## When to add a new eval

Add one when you're about to make a decision and want a number to defend
it. Some good triggers:

- We're considering exposing more tools — does retrieval still work?
- We're refactoring an entry-point — does it still reject malformed input?
- A bug class has appeared twice — write the eval before the third time.

Bad triggers (use `tests/` instead):

- Asserting a single specific output for a single specific input.
- Checking a function's signature or contract.
- Anything that should be a unit test of a Python function.
