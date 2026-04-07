# UXarray MCP Server

An MCP server that exposes [UXarray](https://uxarray.readthedocs.io/) tools to
AI clients such as Claude. It supports:

- local execution for normal mesh analysis
- optional remote execution on HPC systems through Globus Compute
- diagnostics and provenance for scientific workflows

## Install

Core local setup:

```bash
uv sync
```

With HPC support:

```bash
uv sync --extra hpc
```

## Most Users Should Read These in Order

1. [GETTING_STARTED.md](GETTING_STARTED.md) for the short setup path
2. [docs/getting-started.md](docs/getting-started.md) for the full walkthrough
3. [docs/globus-compute.md](docs/globus-compute.md) if you are new to Globus Compute
4. [docs/hpc.md](docs/hpc.md) for generic cluster bring-up
5. [docs/improv.md](docs/improv.md) if you are on Argonne Improv
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
- `plot_variable` — face-centered variable as filled polygon map; supports `cmap`, `vmin`, `vmax`, `title`
- `plot_zonal_mean` — latitude vs. value line chart; supports `line_color`, `title`

HPC diagnostics:

- `get_execution_mode` / `set_execution_mode`
- `validate_hpc_setup`
- `probe_path_access`

Optional remote wrappers (registered only when an endpoint is configured):

- `inspect_mesh_hpc`
- `inspect_variable_hpc`
- `calculate_area_hpc`
- `calculate_zonal_mean_hpc`

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

Copy `config.yaml.example` to `config.yaml` and set your endpoint UUID when you
are ready to use HPC:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-endpoint-uuid"
  execution_mode: "auto"
  timeout_seconds: 300
```

If `endpoint_id` is `null`, the server runs locally only.

## Development Checks

```bash
uv run pre-commit run --all-files
uv run pytest tests/ --ignore=tests/test_remote_agent.py
uv sync --extra docs --dev
uv run sphinx-build -b html docs docs/_build/html
```

## Documentation Index

- [GETTING_STARTED.md](GETTING_STARTED.md)
- [docs/getting-started.md](docs/getting-started.md)
- [docs/globus-compute.md](docs/globus-compute.md)
- [docs/hpc.md](docs/hpc.md)
- [docs/improv.md](docs/improv.md)
- [docs/tools.md](docs/tools.md)
- [docs/workflows.md](docs/workflows.md)
- [docs/scientific-agent.md](docs/scientific-agent.md)
