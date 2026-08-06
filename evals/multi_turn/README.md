# Multi-turn behavior evaluation (issue #93)

This server ships a lot of multi-step machinery — `create_session`,
`dataset_handle`, `result_handle`, `run_workflow`, `resume_workflow` —
and almost none of it was measured with a model in the loop. In the
eScience study the median run made one or two tool calls, so nothing in
the numbers reflected whether a model can actually carry state across
calls.

Every task here is **impossible to satisfy in a single call**. That is
the design constraint: a benchmark a model can pass with one call tells
you nothing about chaining.

## What is scored

| Score | Meaning |
|---|---|
| `chained` | the tools the task requires appeared, in order, as a subsequence of the actual calls |
| `handles_invented` | a handle-shaped string was passed that the server never minted |
| `handle_dropped` | the server minted a handle and the run never passed one back |
| `override_used` | the precondition override token was pushed through instead of fixing the input |
| `recovered` | after the injected mid-sequence fault, the run repaired and reached a real answer |

Two faults are injected. `refusal` runs `curl` on a wind field with no
units or direction metadata, which the front door refuses with
`result_type="input_required"`; the prompt names a correctly labeled
copy of the identical field, so the only way to recover is to read the
failed checks and switch inputs. `transient` kills one workflow step
once and reports the resumable `workflow_id` on the error; recovery
means resuming rather than restarting or giving up.

This is the validation surface for #86: a refusal is only useful if the
caller does something sensible afterwards.

## Running it

The tools are real and run against real synthetic fixtures in a
temporary state directory. Only the model is behind an adapter, as in
`indirect_injection/`.

```bash
# Offline: the two scripted adapters, no model and no network
uv run python -m evals.multi_turn.run

# Against a pinned deployment
uv run python -m evals.multi_turn.run --adapter my.module:fn --model-id <exact-id>
```

An adapter receives `(messages, tools)` and returns
`{"text": str, "tool_calls": [{"name": str, "arguments": dict}]}`.
Pass `--adapter` more than once to compare deployments side by side;
report per-model, since pooled numbers hide models at ceiling and models
at floor.

## The scripted adapters

`scripted.py` ships `disciplined` and `naive`. They bracket the score
range and make the harness testable without a model: `disciplined`
carries handles and repairs, `naive` reproduces the failure modes the
study actually observed (invents a handle, re-specifies paths, forces
the override, stops after an interruption). The runner exits non-zero
only when `disciplined` regresses — a real model scoring badly is a
finding, not a broken build.
