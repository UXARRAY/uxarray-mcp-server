# Agent Guidelines for uxarray-mcp-server

This file provides guidance for AI coding agents working on this repository.

## Project overview

**uxarray-mcp-server** is an MCP (Model Context Protocol) server that exposes
[UXarray](https://uxarray.readthedocs.io/) — a library for working with
unstructured climate and atmospheric meshes — to AI agents such as Claude.

It supports local execution and optional remote execution on HPC clusters via
[Globus Compute](https://globus-compute.readthedocs.io/).

Key tools: `inspect_mesh`, `inspect_variable`, `calculate_area`,
`calculate_zonal_mean`, `validate_dataset`, `plot_mesh`, `plot_variable`,
`plot_zonal_mean`, `run_scientific_agent`, `validate_hpc_setup`,
`probe_path_access`.

Documentation: `docs/` (Sphinx, built to ReadTheDocs).

## Key design decisions

- **Domain/tool separation** — pure computation lives in `domain/`, MCP wiring
  lives in `tools/`. The same domain functions run locally or get serialized
  and sent to an HPC worker via Globus Compute. Never put MCP, provenance, or
  I/O logic in `domain/`.

- **Conditional HPC tool registration** — HPC tools (`*_hpc`) are only
  registered with the FastMCP server when `config.yaml` has a non-null
  `endpoint_id`. This keeps the tool list clean for local-only users.

- **Provenance on everything** — every tool result must pass through
  `attach_provenance()`. No tool should return a dict without `_provenance`.

- **Validation gating** — `validate_dataset` runs before `calculate_zonal_mean`
  in the scientific agent. If validation fails, zonal mean is skipped rather
  than producing unreliable results.

- **Pre-flight health checks** — HPC tool wrappers call `_endpoint_is_ready()`
  before submitting work. They fall back to local execution on failure rather
  than hanging.

- **AllCodeStrategies serialization** — remote functions are serialized with
  `AllCodeStrategies` so the HPC worker does not need `uxarray_mcp` installed,
  only `uxarray`, `xarray`, `netCDF4`, and `h5netcdf`.

- **Empty file guard** — plotting tools check `st_size == 0` before loading
  and check for empty PNG bytes after rendering. Raise `ValueError` with a
  clear message pointing to the likely cause.

## Repository layout

```
src/uxarray_mcp/
  server.py                 # FastMCP server — conditional tool registration
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
    health.py               # check_endpoint_health()
  tools/                    # MCP tool functions
    inspection.py           # Core local tools
    plotting.py             # Visualization tools
    remote_tools.py         # HPC-enabled wrappers with pre-flight + fallback
    scientific_agent.py     # Autonomous 4-stage agent (Analyze→Plan→Execute→Verify)
    execution_control.py    # get/set_execution_mode, validate_hpc_setup, probe_path_access
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
scripts/
  hpc_doctor.py             # CLI diagnostic tool
  improv_endpoint.sh        # Argonne Improv endpoint setup
  agentic_hpc_loop.py       # Example HPC workflow script
config.yaml.example         # Template — copy to config.yaml (gitignored)
```

## Tech stack

- **Python** ≥ 3.11
- **FastMCP** ≥ 2.14.4 — MCP server framework
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
- Any new tool function — add both unit (mocked) and integration (real data)
  tests following the patterns in `test_plotting.py`.
- Any new error path — especially file-not-found and empty-file guards.
- Any bug fix — add a test that would have caught it.

When NOT to modify existing tests:
- Non-functional refactors that preserve behavior.

## HPC configuration

Copy `config.yaml.example` to `config.yaml` (gitignored) and set:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-uuid-here"
  execution_mode: "auto"   # local | hpc | auto
  timeout_seconds: 300
```

The Improv endpoint UUID used during development is
`00000000-0000-0000-0000-000000000000`. Test files live at:

```
/home/jain/uxarray/test/meshfiles/mpas/QU/480/grid.nc
/home/jain/uxarray/test/meshfiles/mpas/QU/480/data.nc
/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc
/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_data_subset.nc
```

Remote paths use canonical GPFS paths (`/home/jain/...`), not `/gpfs/fs1/...`
aliases — both work, but the canonical form is more stable.

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
- Forgetting to register a new tool with `mcp.tool()` in `server.py`.
- Forgetting to export a new tool from `tools/__init__.py`.
- Using `/home/...` paths on Improv when the file actually lives under
  `/gpfs/fs1/home/...` — check `probe_path_access` first on a new cluster.
- Adding a `local import io` inside a function when `io` is used for testable
  byte I/O — import it at module level so tests can patch it.
