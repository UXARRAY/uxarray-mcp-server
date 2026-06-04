# UXarray MCP Server

An MCP server that exposes [UXarray](https://uxarray.readthedocs.io/) tools to
AI clients such as Claude. It supports:

- local execution for normal mesh analysis
- optional remote execution on HPC systems through Globus Compute
- diagnostics and provenance for scientific workflows

## How it runs

The server runs as a subprocess of the MCP client (Claude Code, Claude Desktop,
or any FastMCP transport) and dispatches tool calls either locally or to a
configured Globus Compute endpoint on an HPC cluster. Same MCP tool, same
schema — `use_remote: bool` on every tool decides which path runs.

**Local mode** — analysis on your machine, files on your disk:

```
 ┌────────────────┐         ┌─────────────────────────────┐
 │  Claude Code   │  stdio  │  uv run python -m           │      reads
 │  / Desktop     │ ◀─────▶ │  uxarray_mcp                │ ───▶  local
 │                │  pipe   │  (subprocess on your box)   │       mesh files
 └────────────────┘         └─────────────────────────────┘
```

**HPC mode** — analysis on facility hardware, files stay on facility storage:

```
 ┌────────────────┐  stdio  ┌─────────────────────────┐  Globus  ┌─────────────────────────┐
 │  Claude Code   │ ◀─────▶ │  uxarray_mcp on laptop  │ ◀──────▶ │  Worker on HPC endpoint │      reads
 │  / Desktop     │  pipe   │  (dispatches when       │  Compute │  (uxarray reads file    │ ───▶ facility
 │                │         │   use_remote=True)      │  RPC     │   from facility GPFS)   │      mesh files
 └────────────────┘         └─────────────────────────┘          └─────────────────────────┘      (never copied)
```

The dispatcher falls back to local execution if a remote call is requested
but the endpoint is missing or unhealthy.

## Install

```bash
# Stable user path (after the package is published)
uv tool install uxarray-mcp
uxarray-mcp setup
uxarray-mcp install-claude --print-only   # prints the Claude Desktop block
```

```bash
# Stable user path with HPC support
uv tool install "uxarray-mcp[hpc]"
uxarray-mcp setup
uxarray-mcp endpoints add improv <your-endpoint-uuid> --set-default
uxarray-mcp doctor --endpoint improv --timeout-seconds 180
```

```bash
# Developer / contributor path, and best path when using repo scripts/docs
git clone https://github.com/UXARRAY/uxarray-mcp-server.git
cd uxarray-mcp-server
uv sync                 # core local install
uv sync --extra hpc     # add Globus Compute deps
```

```bash
# User install directly from GitHub before a PyPI release exists
uv tool install "git+https://github.com/UXARRAY/uxarray-mcp-server.git"
uxarray-mcp setup
uxarray-mcp endpoints add improv <your-endpoint-uuid>
uxarray-mcp install-claude --print-only   # prints the Claude Desktop block
```

The ``uxarray-mcp`` CLI exposes:

| subcommand          | what it does                                             |
| ------------------- | -------------------------------------------------------- |
| ``serve``           | run the MCP server on stdio (Claude / FastMCP transport) |
| ``setup``           | write a starter config to ``~/.config/uxarray-mcp/``     |
| ``endpoints add``   | register a named Globus Compute endpoint                 |
| ``endpoints list``  | show configured endpoints + discovery path               |
| ``doctor``          | validate auth, endpoint health, optional remote probes   |
| ``install-claude``  | print or merge the Claude Desktop ``mcpServers`` block   |

Config is discovered in this order: ``$UXARRAY_MCP_CONFIG`` →
``./config.yaml`` in the current working directory →
``~/.config/uxarray-mcp/config.yaml`` → the editable-install repo config
fallback. The project-local file wins inside a checkout so development
endpoints are not shadowed by an empty user config.

## Most Users Should Read These in Order

1. [GETTING_STARTED.md](GETTING_STARTED.md) for the short setup path
2. [docs/getting-started.md](docs/getting-started.md) for the full walkthrough
3. [docs/globus-compute.md](docs/globus-compute.md) if you are new to Globus Compute
4. [docs/hpc.md](docs/hpc.md) for generic cluster bring-up
5. [docs/improv.md](docs/improv.md) if you are on Argonne Improv
6. [docs/ucar.md](docs/ucar.md) if you are on NCAR Casper
7. [docs/chrysalis.md](docs/chrysalis.md) if you are on Argonne Chrysalis
6. [docs/workflows.md](docs/workflows.md) for sequential remote workflows

## Main Tools

Analysis:

- `inspect_mesh` — topology, format detection, face/node/edge counts
- `inspect_variable` — variable metadata, location, and statistics
- `calculate_area` — face area statistics
- `calculate_zonal_mean` — latitude-band averaging (conservative or standard)
- `validate_dataset` — NaN, Inf, and fill value checks
- `run_scientific_agent` — autonomous Analyze → Plan → Execute → Verify pipeline
- `subset_bbox` / `subset_polygon` / `extract_cross_section` — spatial queries and regional reductions
- `calculate_gradient`, `calculate_curl`, `calculate_divergence`, `calculate_azimuthal_mean` — vector calculus and radial summaries
- `compare_fields`, `calculate_bias`, `calculate_rmse`, `calculate_pattern_correlation` — same-grid comparison metrics
- `remap_variable` / `regrid_dataset` — UXarray-backed remapping to a target grid
- `calculate_temporal_mean`, `calculate_anomaly`, `calculate_ensemble_mean`, `calculate_ensemble_spread` — temporal and ensemble summaries
- `export_to_netcdf`, `export_to_csv`, `write_result` — persist derived results to downstream formats

Stateful workflows:

- `create_session`, `register_dataset`, `get_session_state`, `reset_session_state`
- `run_workflow`, `resume_workflow`, `get_workflow_status`
- `get_result_handle`, `get_operation_status`, `list_operations`

Visualization (returns inline PNG):

- `plot_mesh` — mesh wireframe
- `plot_mesh_geo` — geographic mesh plot with boundary-aware rendering
- `plot_variable` — face-centered variable as filled polygon map; supports `cmap`, `vmin`, `vmax`, `title`
- `plot_zonal_mean` — latitude vs. value line chart; supports `line_color`, `title`

HPC diagnostics:

- `get_execution_mode` / `set_execution_mode`
- `endpoint_status`
- `validate_hpc_setup`
- `probe_path_access`

All inspection, computation, and plotting tools accept ``use_remote: bool``
and ``endpoint: str | None``. When ``use_remote=True`` the dispatcher submits
to the configured (or named) Globus Compute endpoint and falls back to local
execution if the endpoint is missing or unhealthy. There are no separate
``*_hpc`` tool names on the MCP surface — the same tool runs locally or
remotely based on the flag.

Full parameter and return details live in [docs/tools.md](docs/tools.md).

## Helper Scripts

- `scripts/hpc_doctor.py`
  First-pass CLI doctor for local auth, endpoint status, remote no-op
  execution, and optional real-path probing.
- `scripts/improv_endpoint.sh`
  Writes Improv endpoint templates for single-host validation or PBS debug.
- `scripts/agentic_hpc_loop.py`
  Example submit/poll/branch workflow using Globus Compute futures directly.

## HPC in One Paragraph

Remote execution has three separate layers:

1. the local machine running this repository
2. the endpoint running on the HPC machine
3. the remote worker environment that must also have `uxarray`, `xarray`,
   `netCDF4`, and `h5netcdf`

Most confusing failures happen because only one or two of those layers are set
up. Start with [docs/globus-compute.md](docs/globus-compute.md) and use
`validate_hpc_setup()` before real remote jobs.

## Configuration

Use the CLI for the common case:

```bash
uxarray-mcp setup
uxarray-mcp endpoints add improv <your-endpoint-uuid> --path-prefix /lus/ --set-default
```

This writes ``~/.config/uxarray-mcp/config.yaml`` with the canonical
multi-endpoint schema. For dev clones, ``./config.yaml`` at the repo root
still works (and is gitignored). The full schema:

```yaml
hpc:
  default_endpoint: "ucar"
  endpoints:
    ucar:
      endpoint_id: "your-ucar-endpoint-uuid"
      path_prefixes: ["/glade/"]
    improv:
      endpoint_id: "your-improv-endpoint-uuid"
      path_prefixes: ["/gpfs/fs1/", "/home/jain/"]
  execution_mode: "auto"
  timeout_seconds: 300
```

Remote tools accept `endpoint="ucar"` or `endpoint="improv"`; when omitted,
the server routes by path prefix before falling back to `default_endpoint`.

## Development Checks

```bash
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py
uv sync --extra docs --dev
uv run sphinx-build -b html docs docs/_build/html
```

## Publishing

Releases follow the UXarray pattern: publish a GitHub Release from a version tag
such as `v0.1.0`; the release workflow builds and publishes to PyPI with trusted
publishing. Conda packages are handled through a separate conda-forge feedstock;
`conda/recipe/meta.yaml` is a seed recipe for `uxarray-mcp-feedstock`.

```bash
uv build
uv tool install dist/uxarray_mcp-*.whl --force
uxarray-mcp --help
```

See [docs/release.md](docs/release.md) for the full PyPI and Conda workflow.

## Documentation Index

- [GETTING_STARTED.md](GETTING_STARTED.md)
- [docs/getting-started.md](docs/getting-started.md)
- [docs/globus-compute.md](docs/globus-compute.md)
- [docs/hpc.md](docs/hpc.md)
- [docs/improv.md](docs/improv.md)
- [docs/ucar.md](docs/ucar.md)
- [docs/chrysalis.md](docs/chrysalis.md)
- [docs/tools.md](docs/tools.md)
- [docs/workflows.md](docs/workflows.md)
- [docs/scientific-agent.md](docs/scientific-agent.md)
