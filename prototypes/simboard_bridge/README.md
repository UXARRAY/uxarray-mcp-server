# SimBoard ↔ uxarray-mcp bridge (prototype)

Two thin tools that let an MCP agent chain
**SimBoard (find runs)** → **uxarray-mcp (analyze them)** in one conversation.

This lives under `prototypes/` and is intentionally **not** wired into the
registry (`registry.py`) yet. It's a proof of concept to share with Tom Vo
(SimBoard lead) and Rob Jacob before committing to the integration.

## What the demo looks like

```text
User:    "Find the latest completed Chrysalis run and compute its face areas."

Agent → simboard_list_simulations(machine="chrysalis", status="completed", limit=5)
SimBoard returns the matching simulations with execution IDs and metadata.

Agent → simboard_get_paths(sim_id="bae7fd01-...")
SimBoard returns:
  {
    "execution_id": "10011002.260610-072848",
    "machine": "chrysalis",
    "grid_name": "ne30pg2_r05_IcoswISC30E3r5",
    "artifacts": {
      "output":  "/lcrc/group/e3sm/ac.golaz/.../run",
      "archive": "/lcrc/group/e3sm/ac.golaz/.../archive/...",
    }
  }

Agent → run_analysis(operation="calculate_area",
                      grid_path="/lcrc/group/.../grid.nc",
                      use_remote=True, endpoint="chrysalis")
uxarray-mcp computes on Chrysalis (ANL/LCRC) via Globus Compute.
```

Two providers, one conversation, no glue code on either side.

The SimBoard REST API contract this bridge targets (the `-api` subdomain and
`/api/v1` prefix) is documented upstream in
[E3SM-Project/simboard#246](https://github.com/E3SM-Project/simboard/pull/246).

## Layout

- `client.py` — typed Python client against `simboard-dev-api.e3sm.org`.
  Uses `urllib` (stdlib) — no new dep.
- `tools.py` — two MCP-shaped functions (`simboard_list_simulations`,
  `simboard_get_paths`) that the server would expose.
- `example.py` — self-contained, **offline** demo of the full
  discovery → analysis chain (mocked SimBoard + local HEALPix grid).
  No network, no HPC, no data files needed.
- `smoke.py` — end-to-end smoke test against the live dev deployment.

## Running

Offline example (runs anywhere):

```bash
uv run python -m prototypes.simboard_bridge.example
```

Live smoke test (needs network access to the SimBoard dev API):

```bash
uv run python -m prototypes.simboard_bridge.smoke
```

## Endpoints used (all GET, no auth needed today)

| Tool | SimBoard endpoint |
|---|---|
| `simboard_list_simulations` | `GET /api/v1/cases` (and `/api/v1/simulations`) |
| `simboard_get_paths` | `GET /api/v1/simulations/{sim_id}` |

OpenAPI schema: <https://simboard-dev-api.e3sm.org/openapi.json>
Frontend: <https://simboard-dev.e3sm.org>

## Status / next steps

- [x] Confirmed live dev API at `simboard-dev-api.e3sm.org`.
- [x] Verified case + simulation list endpoints return rich metadata.
- [x] Verified simulation-detail returns archive/output/run_script paths
      with machine identity (Perlmutter/NERSC).
- [ ] Decide on auth model for production (today the dev API is open;
      production will need either OAuth token or service-account creds).
- [ ] Path translation: SimBoard returns NERSC paths; we'd route to the
      `nersc`-named Globus Compute endpoint via uxarray-mcp's existing
      `path_prefix` mechanism. No new code, just config.
- [ ] If we move past prototype: graduate `tools.py` to
      `src/uxarray_mcp/tools/simboard.py`, add unit tests, decide whether
      to expose as front-door tools or under `analyze_dataset` enrichment.

## Why this stays out of the main server (for now)

Until Tom blesses the integration, this is speculative work against a dev
deployment. Putting it in `src/` would advertise it as supported. The
prototype is enough to:

1. Demo the workflow to Rob/Tom.
2. Validate the API surface is what we need.
3. Quantify the work it would take to ship.
