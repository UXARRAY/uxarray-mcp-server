# Architecture

```
MCP client (Claude, Cline, …)
        │  tools/list · tools/call
        ▼
server/   registry.py  – twelve tools, flat, tagged, schema trimmed
          tools.py     – resolve handles → route local/remote → core.ops → contract
          contract.py  – refusals, warning codes, provenance, JSON safety
          state.py     – sessions, dataset handles, results, operations (JSON files)
          app.py       – MCPAdapter + artifact resources
        │
        ├──────────────── local ──────────────────┐
        ▼                                         ▼
core/   ops.py  – name → function table      remote/  executor.py – Executor + operation_id
        mesh · facts · inspect · area ·                shim.py     – the ONE shipped function
        zonal · vector_calc · compare ·                health.py   – manager status, worker probe
        remap · subset · temporal · export ·           config.py   – endpoints, path prefixes
        coverage · plotting · catalog
        (uxarray, numpy, matplotlib only)        Globus Compute → worker: `from uxarray_mcp.core import ops`
```

## The rules

**`core/` is the only place science lives, and it imports no server code.**
Nothing under `core/` may import `mcp`, `toolregistry`, pydantic, or any
`uxarray_mcp.server`/`remote` module. `tests/test_core_isolation.py` runs
`import uxarray_mcp.core` in a subprocess with those packages blocked. This
is what lets a worker run `pip install --no-deps uxarray-mcp` beside
`globus-compute-endpoint` without a pydantic conflict, and it is why remote
execution needs no second implementation of anything.

**One function crosses the wire.** `remote/shim.py: run_op(op, kwargs)` is
serialized by Globus Compute (`AllCodeStrategies`) and calls
`core.ops.call(op, **kwargs)` on the worker. Adding an operation means
adding it to `core/ops.py`; it is immediately available remotely.

**Every remote call is an operation.** `remote/executor.py` writes an
operation record before submitting, so a call that outlives the caller's
timeout returns `{"status": "running", "operation_id"}` and `get_operation`
collects it later. Failures are classified into stable error codes.

**Results are contracts, not dicts.** `server/contract.py: finish()` adds
`status`, `physically_interpretable`, `warning_codes`, `preconditions` and
`_provenance`, and makes the payload JSON-safe (no NaN, no numpy). A failed
precondition raises `Refusal`, which `guard` turns into an
`outcome: "input_required"` payload with repairs. Core functions report
coverage (`mesh_coverage`, `profile_coverage`, `source_coverage`, …); the
server decides what refuses and what warns.

**Payload is budget.** Every reply is re-sent on every later turn of a
conversation. Tool schemas total ~13 kB (`tests/test_server.py` ratchets
it); typical results are 1–2 kB; version-drift warnings are emitted once per
process; images above 256 kB are returned as resource links, not base64.

**Plotting is pixel-bounded.** Above `RASTERIZE_ABOVE_FACES` (200 000) a
mesh or field is rasterized to the requested width×height rather than drawn
as one polygon per face. The reply says which path ran (`render_mode`).

## Adding an operation

1. Write the function in the right `core/` module: plain kwargs, returns a
   JSON-safe dict with any coverage block and `warning_codes`; put a data
   object to persist under `_payload`.
2. Register it in `core/ops.py` and expose it through the right tool in
   `server/tools.py` (a new `statistic=`/`shape=`/`kind=` value, not a new
   tool). Add refusable checks there with `contract.check`.
3. One test in `tests/test_core_<module>.py` (a real number) and one in
   `tests/test_tools.py` (happy path + the refusal). Add a row to
   `docs/tools.md`.
