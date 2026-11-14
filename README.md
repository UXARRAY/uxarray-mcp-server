# UXarray MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets an AI client
inspect, compute on, subset, remap and plot unstructured climate-model meshes
with [UXarray](https://uxarray.readthedocs.io) — on your laptop, or on an HPC
system through Globus Compute when the data lives there.

Thirteen tools. Every result carries its provenance and says what it did
**not** verify; a computation whose preconditions fail (an area with no
sphere radius, a vorticity without velocity units, a subset that selects
nothing) is refused with a repair instead of returned as a number.

## Install

Python 3.12 or newer.

```bash
uv tool install uxarray-mcp          # or: pip install uxarray-mcp
uxarray-mcp doctor                   # local check, no HPC needed
```

Connect Claude Desktop:

```bash
uxarray-mcp install-claude --config-path "~/Library/Application Support/Claude/claude_desktop_config.json"
```

or add to any MCP client config:

```json
{"mcpServers": {"uxarray": {"command": "uxarray-mcp", "args": ["serve"]}}}
```

Then ask: *"Inspect `/data/mpas/x1.655362.grid.nc`, compute its face areas in
square metres, and plot the mesh over the North Atlantic."*

## Tools

| Tool | Does |
|---|---|
| `list_datasets` | Files in a directory with format, role, `n_face`, size class — read from headers, no mesh opened |
| `inspect_dataset` | Topology, sphere coverage, variables, validation, plot cost hint. Start here; `first_look=True` adds areas, a zonal mean and two plots. |
| `compute` | `area`, `zonal_mean`, `zonal_anomaly`, `azimuthal_mean`, `temporal_mean`, `anomaly`, `ensemble_mean`, `ensemble_spread` |
| `vector_calc` | `gradient`, `curl`, `divergence` with physical-units guard |
| `compare` | Area-weighted bias / rmse / pattern correlation between two files |
| `remap` | Mesh-to-mesh, to lon/lat, or node↔face↔edge; UXarray or YAC (conservative) backends |
| `subset` | `bbox`, `polygon`, `cross_section`, `circle`, `nearest` → result handle |
| `plot` | `mesh`, `field`, `profile` PNGs; meshes above 200k faces are rasterized |
| `export` | Result or variable to NetCDF / CSV, with a fidelity report |
| `session` | Register a dataset once, reuse a handle |
| `endpoint` | Status, worker probe and validation of Globus Compute endpoints |
| `get_operation` | Collect a remote result that outlived its call |
| `guide` | Step-by-step plans: first_look, vorticity, cyclone_structure, eddy_activity, model_evaluation, climatology_anomaly, hpc_diagnose |

Parameters, refusal rules and result shapes: [docs/tools.md](docs/tools.md)
(which also covers the optional REST/OpenAPI server and tool hints).

## When your data is on a cluster

Everything above runs on your laptop. If the files live on an HPC system
you can also run the *same tools there* without copying data: you start one
process on the cluster (a [Globus Compute](https://www.globus.org/compute)
endpoint, running as you), register it here, and any path under its prefix
is routed to it automatically. Results come back as a few kB of JSON with
`venue: hpc:<name>`; the first call after idling waits for the scheduler.

```bash
uxarray-mcp endpoints add chrysalis <endpoint-uuid> --path-prefix /lcrc/
uxarray-mcp doctor --endpoint chrysalis
```

[docs/hpc.md](docs/hpc.md) starts with "do you need this?", then the three
one-time setup steps, keeping the worker current, site notes for Chrysalis /
Improv / Casper, YAC, and a troubleshooting table. Read
[SECURITY.md](SECURITY.md) before sharing an endpoint — it is shell access
as your HPC user.

## Layout

```
src/uxarray_mcp/core/     science (uxarray, numpy, matplotlib); what a worker imports
src/uxarray_mcp/server/   the thirteen tools, result contract, state, MCP app
src/uxarray_mcp/remote/   Globus Compute executor, the one shipped function, health
```

[docs/architecture.md](docs/architecture.md) explains the three rules this
layout enforces. A worked example on real data:
[case-studies/conus-precipitation-gdex](case-studies/conus-precipitation-gdex/README.md).

## Development

```bash
uv sync --dev
uv run pre-commit run --all-files
uv run pytest -m "not hpc and not live and not yac"
uv sync --extra hpc --dev && uv run pytest -m hpc       # Globus layer, no cluster needed
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Apache-2.0.
