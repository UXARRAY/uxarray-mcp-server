# UXarray MCP Server

**Bringing AI-assisted analysis to unstructured climate meshes — the first
MCP server for computational geoscience.**

GitHub: <https://github.com/UXARRAY/uxarray-mcp-server>
| Contact: Rajeev Jain (jain@anl.gov)

---

## The gap

The Model Context Protocol (MCP) ecosystem has grown to over 18,000 servers
(GitHub, web, DevOps, databases), yet none target the computational
geoscience stack. Researchers working with next-generation unstructured
meshes (MPAS, UGRID, HEALPix, ICON) still context-switch between writing
UXarray code, managing HPC jobs, and interpreting results. There is no
agent-native path from a natural-language question to a provenance-tracked
scientific result on an unstructured grid.

## What this project does

UXarray MCP Server bridges that gap. It wraps
[UXarray](https://uxarray.readthedocs.io/) — the community Python library
for unstructured mesh analysis — as a set of AI-callable tools, so an
assistant (Claude, Cursor, or any MCP/OpenAPI client) can open meshes,
compute diagnostics, plot fields, and run multi-step science workflows from
plain-language prompts.

```
┌─────────────┐   ┌──────────────┐                  ┌───────────────────┐
│  AI client  │◀─▶│ uxarray-mcp  │◀── Globus ──────▶│  HPC endpoint     │
│  (Claude…)  │   │ (your laptop)│   Compute (opt)   │ (Slurm/PBS worker)│
└─────────────┘   └──────────────┘                  └───────────────────┘
```

Local by default. HPC is opt-in: when a Globus Compute endpoint is
configured, the same tool calls transparently dispatch to a remote cluster
— the user's workflow does not change.

## Capabilities (v0.1.2, UXarray 2026.7.0)

| Category | Operations |
|---|---|
| **Inspect** | Open MPAS / UGRID / HEALPix / shapefile meshes; list variables; validate grid+data |
| **Analyze** | Face area, zonal mean, zonal anomaly, gradient, curl (vorticity), divergence, azimuthal mean, subsetting, cross-sections |
| **Compare** | Bias, RMSE, pattern correlation, ensemble mean/spread, temporal mean, anomaly (climatology) |
| **Transform** | Remap between grids, remap to rectilinear lon/lat |
| **Plot** | Mesh wireframe, geographic map, variable field, zonal-mean profile — inline images |
| **Guided workflows** | Cyclone structure, eddy activity, model evaluation, climatology anomaly, vorticity analysis, first look, HPC diagnostics |

25 operations through a single `run_analysis` dispatcher.
31 tools visible by default (`core` profile); 64 tools total in
`deferred-full`, with the extra 33 found on demand via BM25 (`discover_tools`).
Every result carries a provenance record (tool, version, inputs, venue).

## Architecture highlights

- **Domain/tool separation.** Pure computation lives in `domain/`; server
  wiring in `registry.py` + `app.py`. The same domain functions run locally
  or get serialized to an HPC worker via Globus Compute — no
  `uxarray_mcp` install needed on the worker.
- **Two profiles.** `core` keeps a small, predictable surface for most
  clients. `deferred-full` loads the complete toolbox; agents discover tools
  via BM25 search over names, docstrings, and domain synonyms.
- **Multi-protocol.** One `UXarrayApp` object serves **MCP** (stdio, SSE,
  streamable HTTP) and **OpenAPI/REST** from the same tool surface, powered
  by [toolregistry-server](https://github.com/Oaklight/toolregistry-server)
  0.4.
- **Policy tags.** Every tool carries metadata (`READ_ONLY`, `FILE_SYSTEM`,
  `NETWORK`, `SLOW`) so hosts can build safe, filtered subsets in one call.
- **Tested HPC endpoints.** Validated on Chrysalis (LCRC), Improv (ALCF),
  and UCAR/Casper — warm round-trips typically 0.5–5 s; cold PBS spin-up
  3–4 min.

## Quick start (local, no HPC)

```bash
uv tool install --python 3.12 uxarray-mcp
uxarray-mcp setup
uxarray-mcp install-claude        # wire into Claude Desktop
# restart Claude, then ask it to analyze a mesh file
```

Or serve as REST:

```bash
uxarray-mcp openapi --port 8000   # OpenAPI surface for any HTTP client
```

## Why it matters for the MPAS / WRF community

- **Lowers the barrier.** A researcher can explore an MPAS output and run
  real diagnostics — gradient, vorticity, zonal anomaly, model evaluation —
  without writing code. The AI translates intent into UXarray calls.
- **Same library, same results.** It drives UXarray directly, so outputs
  match a hand-written notebook. The functions are also importable for
  scripts and pipelines.
- **Scales to HPC transparently.** Meshes too large for a laptop are
  analyzed on the cluster; only the JSON result comes back. Globus Compute
  handles authentication, serialization, and job scheduling.
- **Reproducible by construction.** Provenance on every result means you
  can trace what ran, where, with which inputs and library version.

## Status

Open source (Apache-2.0) under the
[UXARRAY](https://github.com/UXARRAY) GitHub org. Python 3.12, UXarray
2026.7.0. Active development — issues and contributions welcome.
