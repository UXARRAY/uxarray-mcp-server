# Schema-rejection eval

## What this measures (plain language)

When someone asks an AI assistant to "compute vorticity from the wind file,"
the AI translates that into a call like:

```
run_analysis(operation="curl", grid_path=..., data_path=..., u_variable=..., v_variable=...)
```

There are many ways this call can be **wrong**:

- The AI omitted `u_variable` because it didn't read the data file carefully.
- The AI typed `operation="curl_calculation"` instead of `operation="curl"`.
- The AI passed `grid_path="/path/that/does/not/exist.nc"`.
- The AI passed a string where a list was expected, or vice versa.

For each of these, three things can happen:

1. **Caught at the schema boundary.** The server's parameter checks reject
   the call before any actual analysis runs. Best case — costs nothing.
2. **Caught at the file/IO boundary.** The call passes schema validation,
   tries to open a file, and fails with a clear error. Acceptable.
3. **Silent failure.** The call passes both, runs to completion, and
   returns a wrong-looking number with no error at all. **This is the bug
   class** — the AI gets back something that looks like an answer when it
   shouldn't.

**This eval asks: how often does the typed boundary actually catch a bad
call?**

## What "good" looks like

For ~20 deliberately-malformed inputs:

- **>70% caught at schema or IO layer** = the boundary is doing real work.
- **<30%** = the boundary is too loose; the AI can drive it into silent
  failures by sending well-formed-looking nonsense.
- **0 silent failures** = required. If we produce a plausible-looking
  number from a malformed request, that is a bug we must fix.

## How to run

```bash
uv run python -m evals.schema_rejection.run
```

Writes a JSON report to `evals/results/schema_<timestamp>.json` and prints
a summary table. Returns non-zero exit if any silent failure occurred —
suitable for CI.

## What this does NOT measure

This eval cannot catch the kind of silent failure where the schema accepts
the call, the file opens cleanly, and the **answer is physically wrong**
(e.g., curl returned in the wrong units because of sphere-radius scaling).
That class needs a downstream validator with physical priors — expected
magnitude, expected units, expected sign — which is a separate piece of
work.

## Reading the output

The runner classifies each call into one of:

| Outcome | Meaning |
|---|---|
| `schema_rejected` | Server raised before any file IO. Best case. |
| `io_rejected` | Server tried to open a file/path and failed visibly. Acceptable. |
| `runtime_error` | Computation started but raised an exception. Acceptable but worse. |
| `silent_pass` | Returned a result dict without an error. **Bug if the input was malformed.** |

The headline number is `caught_rate = (schema_rejected + io_rejected + runtime_error) / total`.
We want that as high as possible. The danger number is the `silent_pass` count —
we want that to be **zero** for malformed inputs.
