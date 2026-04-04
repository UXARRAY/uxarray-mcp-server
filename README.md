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

1. [GETTING_STARTED.md](GETTING_STARTED.md)
2. [docs/globus-compute.md](docs/globus-compute.md) if you are new to Globus Compute
3. [docs/hpc.md](docs/hpc.md) for generic cluster bring-up
4. [docs/improv.md](docs/improv.md) if you are on Argonne Improv
5. [docs/workflows.md](docs/workflows.md) for sequential remote workflows

## Main Tools

Core tools:

- `inspect_mesh`
- `inspect_variable`
- `calculate_area`
- `calculate_zonal_mean`
- `validate_dataset`
- `run_scientific_agent`

HPC diagnostics:

- `get_execution_mode`
- `set_execution_mode`
- `validate_hpc_setup`
- `probe_path_access`

Optional remote wrappers:

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
