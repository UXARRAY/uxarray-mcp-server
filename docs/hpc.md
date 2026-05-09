# HPC Setup

This page explains how to bring up remote execution on a new HPC machine.

If you do not already know what Globus Compute, an endpoint, or a worker is,
read [Globus Compute Primer](globus-compute.md) first.

## The Mental Model

There are three separate pieces:

1. **Your local machine**
   This repository runs here and submits remote work through the Globus Compute SDK.
2. **The endpoint on the HPC machine**
   This is the long-lived Globus Compute process that accepts submitted work.
3. **The worker environment on the HPC machine**
   This is where `uxarray`, `xarray`, and file access actually happen.

Many confusing failures come from installing something in only one of those places.

## What Must Exist Before HPC Tools Will Work

### On your local machine

- this repository checked out
- `uv sync --extra hpc` completed
- one-time local Globus auth completed
- `config.yaml` contains the endpoint UUID

### On the HPC machine

- a Python environment for the endpoint
- `globus-compute-endpoint` installed there
- the endpoint configured with `globus-compute-endpoint configure <name>`
- the endpoint running
- remote scientific packages installed in the same worker environment:
  - `uxarray`
  - `xarray`
  - `netCDF4`
  - `h5netcdf`

### On scheduler-backed clusters

If the endpoint uses PBS or SLURM, the child endpoint must also be able to find
the scheduler commands it needs. For PBS that usually means `qsub`, `qstat`,
and `qdel`.

## Local Setup

Install repository dependencies:

```bash
cd /path/to/uxarray-mcp-server
uv sync --extra hpc
```

Create a local config file:

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml`:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-endpoint-uuid"
  execution_mode: "auto"
  timeout_seconds: 300
```

For deployments that need more than one facility, define named endpoint
profiles instead of a single `globus_compute.endpoint_id`. Tools should pass
`endpoint="ucar"` explicitly, or use `default_endpoint`. File paths are
validated separately and are not used to choose the execution endpoint.

```yaml
hpc:
  default_endpoint: "ucar"
  endpoints:
    ucar:
      endpoint_id: "your-ucar-endpoint-uuid"
    improv:
      endpoint_id: "your-improv-endpoint-uuid"
  execution_mode: "auto"
  timeout_seconds: 300
```

Examples:

```python
inspect_mesh_hpc(
    "/glade/u/home/rajeevj/uxarray/test/meshfiles/mpas/QU/mesh.QU.1920km.151026.nc",
    use_remote=True,
    endpoint="ucar",
)
```

```python
inspect_mesh_hpc(
    "/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/QU/480/grid.nc",
    use_remote=True,
    endpoint="improv",
)
```

When `endpoint` is omitted, `default_endpoint` is used first, then the legacy
single endpoint. Unknown endpoint names fail before any Globus Compute submission
so a typo like `endpoint="ucra"` is not treated as a facility name. Raw Globus
Compute UUIDs can still be passed explicitly for one-off diagnostics.

Authenticate the local client once:

```bash
uv run python -c "from globus_compute_sdk import Client; Client()"
```

```{warning}
Run the command above in an interactive terminal. Do not use a heredoc.
Globus needs to read the pasted authorization code from stdin.
```

## Remote Setup on the HPC Machine

Create a dedicated endpoint virtual environment:

```bash
python3 -m venv ~/venvs/globus-compute
source ~/venvs/globus-compute/bin/activate
python -m pip install -U pip
python -m pip install globus-compute-endpoint globus-compute-sdk
```

Install the remote scientific packages in that same environment:

```bash
source ~/venvs/globus-compute/bin/activate
python -m pip install uxarray xarray netCDF4 h5netcdf
```

Configure the endpoint profile:

```bash
globus-compute-endpoint configure uxarray-endpoint
```

When you start the endpoint for the first time, Globus Compute may prompt for
browser-based authorization. Complete that flow and keep the endpoint UUID.

## First Bring-Up: Do Not Start With PBS or SLURM

For a brand-new cluster, do not start by debugging scheduler submission and
UXarray at the same time.

Start with a single-host validation mode first. This proves:

- the endpoint can run real remote code
- the worker environment can import packages
- the worker can read a real file

Use a `LocalProvider` template first:

```yaml
endpoint_setup: ""

engine:
  type: GlobusComputeEngine
  max_workers_per_node: 1
  provider:
    type: LocalProvider
    min_blocks: 0
    max_blocks: 1
    init_blocks: 1
    worker_init: |
      source ~/venvs/globus-compute/bin/activate

idle_heartbeats_soft: 10
idle_heartbeats_hard: 5760
```

On Argonne Improv, you can write this template with:

```bash
scripts/improv_endpoint.sh single-host improv-uxarray
```

Then start the endpoint:

```bash
source ~/venvs/globus-compute/bin/activate
globus-compute-endpoint start uxarray-endpoint
```

## What to Run First

From your local machine, do not start with `inspect_mesh_hpc`.

Run:

```bash
uv run python scripts/hpc_doctor.py --timeout-seconds 180
```

Then, if you have a real target file:

```bash
uv run python scripts/hpc_doctor.py \
  --timeout-seconds 180 \
  --sample-path /path/to/file.nc
```

Or from the MCP client:

```text
Run validate_hpc_setup
Run validate_hpc_setup with probe_timeout_seconds=180 and sample_path="/path/to/file.nc"
Run probe_path_access on /path/to/file.nc with use_remote=True
```

These checks validate, in order:

1. local config
2. local Globus auth and dependency availability
3. endpoint-manager status
4. a tiny real remote task
5. optional real-path accessibility

## Only After That, Run UXarray Tools

Once the remote runtime and file path are proven, then use:

```text
Use inspect_mesh_hpc on /path/to/grid.nc with use_remote=True
Use inspect_variable_hpc on /path/to/grid.nc and /path/to/data.nc with use_remote=True
```

## Switching Back to PBS or SLURM

After single-host validation succeeds, switch to your scheduler-backed
configuration.

On PBS systems you must also ensure the child endpoint can find scheduler
commands. If not, you will see failures such as:

```text
/bin/sh: qsub: command not found
```

That is a remote endpoint-environment problem, not a local MCP problem.

On Improv, the helper script writes a PBS debug template and adds PBS commands
to the environment:

```bash
scripts/improv_endpoint.sh pbs-debug <allocation> improv-uxarray
```

Then restart the endpoint and rerun `validate_hpc_setup`.

## Common Misses

### `get_execution_mode()` says `online`, but real jobs fail

That usually means the endpoint manager is healthy while the child endpoint or
worker is not. Use `validate_hpc_setup()` instead of trusting manager health.

### The file path looks correct on the login node, but the worker says it does not exist

Use the canonical shared filesystem path. The worker may not resolve shell
aliases like `/home/...` the same way your interactive login shell does.

Prefer:

```bash
readlink -f /path/to/file
```

### `uxarray` is missing remotely

That means the endpoint is alive but the scientific packages are not installed
in the worker environment.

### Multiple login nodes cause stale PID problems

If you start and stop the endpoint from different login nodes, you can get:

- stale `daemon.pid`
- child endpoint conflicts
- "another instance is running"

Use one login node only and run the endpoint inside `tmux`.

## Execution Modes

| Mode | Behavior |
|------|----------|
| `local` | Always run on your machine |
| `hpc` | Always send to the endpoint |
| `auto` | Use HPC for known HPC paths or large meshes |

Auto-routing uses:

- filesystem prefixes such as `/home/`, `/lus/`, `/scratch/`, `/projects/`, `/gpfs/`
- mesh size thresholds for very large grids

## Scripts and Guides

Use these together:

- [Globus Compute Primer](globus-compute.md)
- [Improv Playbook](improv.md)
- [Agentic Workflows](workflows.md)
- `scripts/hpc_doctor.py`
- `scripts/improv_endpoint.sh`
- `scripts/agentic_hpc_loop.py`
