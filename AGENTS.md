# Agent Guidelines for uxarray-mcp-server

This file provides guidance for AI coding agents working on this repository.

## Project overview

**uxarray-mcp-server** is an MCP (Model Context Protocol) server that exposes
[UXarray](https://uxarray.readthedocs.io/) — a library for working with
unstructured climate and atmospheric meshes — to AI agents such as Claude.

It supports local execution and optional remote execution on HPC clusters via
[Globus Compute](https://globus-compute.readthedocs.io/).

Public MCP tools: `get_capabilities`, `analyze_dataset`, `run_analysis`,
`plot_dataset`, `diagnose_endpoint`, `probe_path_access`, `run_workflow`,
`resume_workflow`, `get_status`, `get_result`, and `manage_session`.

Low-level implementation functions such as `inspect_mesh`, `calculate_area`,
`plot_mesh`, and `endpoint_status` remain importable from `uxarray_mcp.tools`
for tests, scripts, and internal composition, but they are not registered as
individual MCP tools.

Documentation: `docs/` (Sphinx, built to ReadTheDocs).

## Key design decisions

- **Domain/tool separation** — pure computation lives in `domain/`, MCP wiring
  lives in `tools/`. The same domain functions run locally or get serialized
  and sent to an HPC worker via Globus Compute. Never put MCP, provenance, or
  I/O logic in `domain/`.

- **Small MCP front-door surface** — MCP clients see intent-shaped tools, not
  every implementation function. Route new analysis behavior through
  `run_analysis`, plotting through `plot_dataset`, endpoint diagnostics through
  `diagnose_endpoint`, and session state through `manage_session` /
  `get_status` / `get_result`.

- **Single remote execution path** — there are no separate `*_hpc` tools. The
  dispatchers accept `use_remote` and `endpoint` where remote execution is
  meaningful. When `use_remote=True` and an endpoint is unavailable, tools either
  fall back locally when the path is local/readable or raise a clear endpoint
  readiness error.

- **Provenance on everything** — every tool result must pass through
  `attach_provenance()`. No tool should return a dict without `_provenance`.

- **Validation gating** — `validate_dataset` runs before `calculate_zonal_mean`
  in the scientific agent. If validation fails, zonal mean is skipped rather
  than producing unreliable results.

- **Pre-flight health checks** — remote wrappers check endpoint manager state
  before submitting work. `diagnose_endpoint(action="status")` can also submit
  a lightweight worker probe to confirm a real scheduler worker responds.

- **AllCodeStrategies serialization** — remote functions are serialized with
  `AllCodeStrategies` so the HPC worker does not need `uxarray_mcp` installed,
  only `uxarray`, `xarray`, `netCDF4`, and `h5netcdf`.

- **Empty file guard** — plotting tools check `st_size == 0` before loading
  and check for empty PNG bytes after rendering. Raise `ValueError` with a
  clear message pointing to the likely cause.

- **Upfront remote expectation setting** — before invoking any tool with `use_remote=True`, the AI agent must inform the user right upfront in the text response about the target HPC endpoint, potential queue wait times, and the active timeout configuration. This ensures transparency when jobs are queued on batch schedulers (Slurm/PBS).


## Repository layout

```
src/uxarray_mcp/
  server.py                 # FastMCP server — small public front-door surface
  provenance.py             # attach_provenance() used by all tools
  domain/                   # Pure computation — no MCP, no I/O
    mesh.py                 # Grid loading, HEALPix support
    area.py                 # Face area statistics
    variable.py             # Variable metadata and stats
    zonal.py                # Zonal mean computation
    plotting.py             # render_mesh, render_variable, render_zonal_mean
  remote/                   # HPC execution layer
    config.py               # HPCConfig, load_config()
    agent.py                # UXarrayComputeAgent (Academy + Globus Compute)
    compute_functions.py    # Self-contained remote functions (no uxarray_mcp imports)
    health.py               # cached endpoint status + worker probes
  tools/                    # MCP tool functions
    frontdoor.py            # Public MCP dispatch tools (run_analysis, plot_dataset, etc.)
    inspection.py           # Core local implementation functions
    plotting.py             # Visualization implementation functions
    remote_tools.py         # HPC-enabled implementation wrappers
    execution_control.py    # Endpoint diagnostics and mode/config helpers
    capabilities.py         # get_capabilities — tool discovery
tests/
  test_inspect_mesh.py
  test_inspect_variable.py
  test_calculate_area.py
  test_calculate_zonal_mean.py
  test_validate_dataset.py
  test_plotting.py
  test_capabilities.py
  test_scientific_agent.py
  test_execution_control.py
  test_hpc_safety.py        # Pre-flight + fallback (mocked Globus SDK)
  test_remote_agent.py      # Academy agent tests (requires hpc extra)
  test_server.py            # Tool registration verification
docs/                       # Sphinx documentation (MyST Markdown + RST)
  release.md                # Release automation notes (PyPI + conda-forge)
scripts/
  hpc_doctor.py             # CLI diagnostic tool (also exposed as ``uxarray-mcp doctor``)
  improv_endpoint.sh        # Argonne Improv endpoint setup + Python 3.12 upgrade
  ucar_endpoint.sh          # NCAR/Casper (UCAR) endpoint setup
  chrysalis_endpoint.sh     # Argonne Chrysalis endpoint setup
  hpc_build_yac.py          # Build YAC + YAXT on a Globus Compute worker
  yac_smoke_test.py         # Verify worker-side YAC import + basic surface
  agentic_hpc_loop.py       # Example HPC workflow script
conda/recipe/meta.yaml      # Seed recipe for conda-forge feedstock
config.yaml.example         # Template — private config is normally written by the CLI
```

## Tech stack

- **Python** ≥ 3.11
- **FastMCP** ≥ 3.4.0 — MCP server framework
- **UXarray** ≥ 2025.12.0 — unstructured mesh analysis
- **Matplotlib** ≥ 3.9.0 + **Holoviews** ≥ 1.19.0 — visualization
- **PyYAML** ≥ 6.0 — config file parsing
- **uv** — package management and script runner (not conda, not pip directly)
- Optional HPC: `globus-compute-sdk` ≥ 4.5.0, `academy-py` ≥ 0.3.1

## Code style

- **Formatter + linter**: `ruff` — run automatically via pre-commit.
- **Type checker**: `mypy` — run automatically via pre-commit.
  - Use type annotations in all new public functions.
  - `ignore_missing_imports = true` is set, so third-party stubs are not
    required.
- **Imports**: sorted by ruff/isort. First-party = `uxarray_mcp`.
- Comments should explain *why*, not *what*.
- Use `from __future__ import annotations` in files that use `X | Y` syntax,
  since Python 3.11 is the minimum and PEP 604 union syntax needs it there.

All checks are enforced via pre-commit — **every commit must pass
`uv run pre-commit run --all-files`**.

## Setting up a development environment

```bash
uv sync --dev          # core + dev tools
uv sync --extra hpc --dev  # add Globus Compute + Academy

# Verify
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py
```

## Testing

```bash
# Core tests (no HPC required, fast)
uv run pytest tests/ --ignore=tests/test_remote_agent.py -v

# HPC tests (requires uv sync --extra hpc)
uv run pytest tests/test_remote_agent.py tests/test_hpc_safety.py -v
```

When to add tests:
- Any new public MCP tool — register it in `server.py`, export it from
  `tools/__init__.py`, document it in `docs/tools.md`, and add tests.
- Any new implementation operation — prefer adding it behind an existing
  front-door tool (`run_analysis`, `plot_dataset`, `diagnose_endpoint`, or
  `manage_session`) unless there is a strong reason for a new public MCP tool.
- Any new error path — especially file-not-found and empty-file guards.
- Any bug fix — add a test that would have caught it.

When NOT to modify existing tests:
- Non-functional refactors that preserve behavior.

## HPC configuration

Use the CLI:

```bash
uxarray-mcp setup
uxarray-mcp endpoints add improv <your-endpoint-uuid> --path-prefix /lus/
```

This writes ``~/.config/uxarray-mcp/config.yaml``. For dev clones, a
``./config.yaml`` at the repo root is also discovered (gitignored). See
``config.yaml.example`` for the canonical multi-endpoint schema.

Reference dev test paths on Improv:

```
/home/jain/uxarray/test/meshfiles/mpas/QU/480/grid.nc
/home/jain/uxarray/test/meshfiles/mpas/QU/480/data.nc
/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc
/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_data_subset.nc
```

Remote paths should use canonical shared filesystem paths for the target
cluster. On Improv, prefer `/gpfs/fs1/home/<user>/...` over shell aliases when
probing worker access.

## Git workflow

- `main` must always be deployable and pass CI.
- All changes go through feature branches and PRs.
- Prefer **squash and merge** for small changes, **merge commit** for large
  features with meaningful commit history.
- Rebase onto `main` (do not merge) to resolve conflicts before opening a PR.
- Never commit directly to `main`.
- Keep changes minimal. Avoid over-engineering.

## Adding dependencies

New runtime dependencies go in `pyproject.toml` under `[project] dependencies`.
HPC-only dependencies go under `[project.optional-dependencies] hpc`.
Dev-only tools go under `[dependency-groups] dev`.

Note the addition in the PR description. Run `uv sync` after editing to
regenerate `uv.lock`.

## Common mistakes to avoid

- Importing `mcp` or `fastmcp` in `domain/` — domain functions must be
  importable without MCP installed (they run on the remote worker).
- Returning a plain dict from a tool without calling `attach_provenance()`.
- Adding a new public MCP tool when an existing front-door operation would do.
- Forgetting to register an intentional new public MCP tool with `mcp.tool()` in
  `server.py`.
- Forgetting to export a new tool from `tools/__init__.py`.
- Using `/home/...` paths on Improv when the file actually lives under
  `/gpfs/fs1/home/...` — check `probe_path_access` first on a new cluster.
- Adding a `local import io` inside a function when `io` is used for testable
  byte I/O — import it at module level so tests can patch it.
