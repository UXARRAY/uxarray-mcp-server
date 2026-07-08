# Agent Guidelines for uxarray-mcp-server

This file provides guidance for AI coding agents working on this repository.

## Project overview

**uxarray-mcp-server** is a multi-protocol server that exposes
[UXarray](https://uxarray.readthedocs.io/) — a library for working with
unstructured climate and atmospheric meshes — to AI agents and HTTP
clients.  It is powered by
[toolregistry](https://github.com/Oaklight/ToolRegistry) +
[toolregistry-server](https://github.com/Oaklight/toolregistry-server),
which provide:

- **MCP** (stdio / SSE / streamable HTTP) for Claude Desktop, Claude
  Code, and any MCP-compatible client.
- **OpenAPI / REST** (optional extra) for curl, OpenAI Assistants,
  Anthropic Messages API, Gemini, LangChain, plain scripts.
- **Python API** — `from uxarray_mcp.app import make_registry`.

It supports local execution and optional remote execution on HPC clusters via
[Globus Compute](https://globus-compute.readthedocs.io/).

### Tool surface — two profiles

The tool surface is built by `uxarray_mcp.registry.build_registry()`:

- **`core` (default, ~31 tools)** — 11 front-door gateway tools at the
  top level, 12 control/status tools under `session/` and `hpc/`
  namespaces, `io-list_datasets`, and 7 prompt helpers under `prompt/`.
  No deferred tools, no BM25 discovery.  This is what clients see by
  default when running `uxarray-mcp serve`.

- **`deferred-full` (~64 loaded, ~32 visible)** — core set stays visible.
  32 raw implementation tools are loaded with `defer=True` so they don't
  appear in the initial tool list, plus `discover_tools`.  Agents discover
  the deferred tools via `discover_tools` (BM25 search), and operators
  promote them from the admin panel.

### Core tools

Front-door / gateway (top level): `get_capabilities`, `analyze_dataset`,
`run_analysis`, `plot_dataset`, `diagnose_endpoint`, `probe_path_access`,
`run_workflow`, `resume_workflow`, `get_status`, `get_result`,
`manage_session`.

Session state (`session/`): `create_session`, `register_dataset`,
`get_session_state`, `reset_session_state`, `get_result_handle`,
`get_operation_status`, `list_operations`, `get_workflow_status`.

HPC control (`hpc/`): `endpoint_status`, `get_execution_mode`,
`set_execution_mode`, `validate_hpc_setup`.

IO (`io/`): `list_datasets`.

Prompt helpers (`prompt/`): `first_look`, `vorticity_analysis`,
`cyclone_structure`, `eddy_activity`, `model_evaluation`,
`climatology_anomaly`, `hpc_diagnose`.

Low-level implementation functions such as `inspect_mesh`, `calculate_area`,
`plot_mesh`, and `calculate_curl` remain importable from `uxarray_mcp.tools`
for tests, scripts, and internal composition.  In `deferred-full` profile
they are available through `discover_tools`; in `core` they are not
registered.

Documentation: `docs/` (Sphinx, built to ReadTheDocs).

## Key design decisions

- **Domain/tool separation** — pure computation lives in `domain/`, server
  wiring lives in `registry.py` + `app.py`.  The same domain functions
  run locally or get serialized and sent to an HPC worker via Globus
  Compute.  Never put MCP, provenance, or I/O logic in `domain/`.

- **Two-profile surface** — the core profile keeps a small, predictable
  baseline for existing clients.  New tools start in `deferred-full` and
  get promoted when they are stable, commonly useful, documented, and
  have clear provenance/security behavior.

- **Policy tags from day one** — every tool carries `ToolTag` values
  (`READ_ONLY`, `FILE_SYSTEM`, `NETWORK`, `SLOW`) and custom tags
  (`experimental`, `stateful`) so downstream policy code (admin filters,
  auth gates, audit logs) has concrete metadata.

- **Prompt-as-tool** — the former `@mcp.prompt()` decorators (`first_look`,
  `vorticity_analysis`, `hpc_diagnose`) are now regular tools under the
  `prompt/` namespace.  They return instruction text that guides the LLM
  through a multi-step analysis.  This removes the `fastmcp` dependency.

- **Single remote execution path** — there are no separate `*_hpc` tools.
  The dispatchers accept `use_remote` and `endpoint` where remote execution
  is meaningful.  When `use_remote=True` and an endpoint is unavailable,
  tools either fall back locally when the path is local/readable or raise a
  clear endpoint readiness error.

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
  registry.py             # build_registry() — namespace plan, tags, prompt-as-tool
  app.py                  # UXarrayApp, make_registry(), make_mcp_server() — multi-transport
  cli.py                  # uxarray-mcp serve/setup/doctor/endpoints/install-claude
  provenance.py           # attach_provenance() used by all tools
  domain/                 # Pure computation — no MCP, no I/O
    mesh.py               # Grid loading, HEALPix support
    area.py               # Face area statistics
    variable.py           # Variable metadata and stats
    zonal.py              # Zonal mean computation
    plotting.py           # render_mesh, render_variable, render_zonal_mean
  remote/                 # HPC execution layer
    config.py             # HPCConfig, load_config()
    agent.py              # UXarrayComputeAgent (Academy + Globus Compute)
    compute_functions.py  # Self-contained remote functions (no uxarray_mcp imports)
    health.py             # cached endpoint status + worker probes
  tools/                  # Tool implementations
    frontdoor.py          # Public dispatch tools (run_analysis, plot_dataset, etc.)
    inspection.py         # Core local implementation functions
    plotting.py           # Visualization implementation functions
    remote_tools.py       # HPC-enabled implementation wrappers
    execution_control.py  # Endpoint diagnostics and mode/config helpers
    capabilities.py       # get_capabilities — tool discovery
tests/
  test_server.py          # Registry profile shape, tags, prompts, live calls
  test_inspect_mesh.py
  test_inspect_variable.py
  test_calculate_area.py
  test_calculate_zonal_mean.py
  test_validate_dataset.py
  test_plotting.py
  test_capabilities.py
  test_scientific_agent.py
  test_execution_control.py
  test_hpc_safety.py      # Pre-flight + fallback (mocked Globus SDK)
  test_remote_agent.py    # Academy agent tests (requires hpc extra)
evals/                    # BM25 tool retrieval + schema rejection regression
docs/                     # Sphinx documentation (MyST Markdown + RST)
  release.md              # Release automation notes (PyPI + conda-forge)
scripts/
  hpc_doctor.py           # CLI diagnostic tool (also exposed as ``uxarray-mcp doctor``)
  improv_endpoint.sh      # Argonne Improv endpoint setup + Python 3.12 upgrade
  ucar_endpoint.sh        # NCAR/Casper (UCAR) endpoint setup
  chrysalis_endpoint.sh   # Argonne Chrysalis endpoint setup
  hpc_build_yac.py        # Build YAC + YAXT on a Globus Compute worker
  yac_smoke_test.py       # Verify worker-side YAC import + basic surface
  agentic_hpc_loop.py     # Example HPC workflow script
conda/recipe/meta.yaml    # Seed recipe for conda-forge feedstock
config.yaml.example       # Template — private config is normally written by the CLI
```

## Tech stack

- **Python** ≥ 3.12, < 3.13 (pinned for Globus Compute pickle compat)
- **toolregistry** ≥ 0.11.0 — tool registration, schema generation, policy tags
- **toolregistry-server** ≥ 0.4.0 — MCP + OpenAPI adapters
- **UXarray** ≥ 2026.6.0 — unstructured mesh analysis
- **Matplotlib** ≥ 3.9.0 + **Holoviews** ≥ 1.19.0 — visualization
- **PyYAML** ≥ 6.0 — config file parsing
- **uv** — package management and script runner (not conda, not pip directly)
- Optional HPC: `globus-compute-sdk` ≥ 4.5.0, `academy-py` ≥ 0.3.1
- Optional REST: `toolregistry-server[openapi]`

## Code style

- **Formatter + linter**: `ruff` — run automatically via pre-commit.
- **Type checker**: `mypy` — run automatically via pre-commit.
  - Use type annotations in all new public functions.
  - `ignore_missing_imports = true` is set, so third-party stubs are not
    required.
- **Imports**: sorted by ruff/isort. First-party = `uxarray_mcp`.
- Comments should explain *why*, not *what*.
- Use `from __future__ import annotations` in files that use `X | Y` syntax,
  since Python 3.12 is the minimum.

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
- Any new tool — add it to the appropriate bucket in `registry.py`
  (`_CONTROL_TOOLS`, `_CORE_EXTRA_TOOLS`, or `_DEFERRED_TOOLS`), export
  it from `tools/__init__.py`, document it in `docs/tools.md`, and add
  tests.  The `test_namespace_plan_covers_every_public_tool` test will
  fail if a tool in `__all__` is not assigned to any bucket.
- Any new implementation operation — prefer adding it behind an existing
  front-door tool (`run_analysis`, `plot_dataset`, `diagnose_endpoint`, or
  `manage_session`) unless there is a strong reason for a new public tool.
  New operations start in `_DEFERRED_TOOLS` and graduate to core via the
  promotion path.
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

- Importing `mcp` or `toolregistry` in `domain/` — domain functions must be
  importable without server dependencies installed (they run on the remote
  worker).
- Returning a plain dict from a tool without calling `attach_provenance()`.
- Adding a new tool to `tools/__init__.__all__` without assigning it to a
  bucket in `registry.py` — the coverage test will catch this.
- Adding a deferred tool without a `search_hint` in `_SEARCH_HINTS` —
  BM25 discovery works much better with domain synonyms.
- Using `/home/...` paths on Improv when the file actually lives under
  `/gpfs/fs1/home/...` — check `probe_path_access` first on a new cluster.
- Adding a `local import io` inside a function when `io` is used for testable
  byte I/O — import it at module level so tests can patch it.
