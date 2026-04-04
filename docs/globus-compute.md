# Globus Compute Primer

This page is for users who are new to Globus Compute and HPC endpoints.

The short version:

- This repository runs **locally** by default.
- To run on an HPC machine, you need a **Globus Compute endpoint** running on that machine.
- Your laptop and the cluster need **different software installed in different places**.
- An endpoint reporting `online` is only the start. You still need to prove that the remote worker can run code and read the real file you care about.

## What Globus Compute Is

Globus Compute is a system for sending Python functions from one machine to another.

In this repository, that means:

1. Claude or another MCP client asks this server to run a tool.
2. The server decides whether to run the tool locally or remotely.
3. If remote execution is selected, the server submits a Python function through Globus Compute.
4. A worker process on your HPC endpoint runs that function and sends the result back.

You do not need inbound SSH tunnels or open ports from the internet to your cluster.

## Terms

### Local machine

Your laptop or workstation, where:

- this repository lives
- the MCP server runs
- the Globus Compute SDK submits remote work

### Endpoint

A named Globus Compute service that you configure on the HPC side.

Examples:

- `improv-uxarray`
- `uxarray-endpoint`

An endpoint has a stable UUID. You put that UUID in `config.yaml` on your local machine.

### Endpoint manager

The lightweight process that stays connected to Globus and accepts work for an endpoint.

This is what `get_execution_mode()` or `validate_hpc_setup()` may report as `online`.

### User endpoint / child endpoint

The process the endpoint manager starts for your actual user session and configuration.

This is where many real failures happen:

- stale PID files
- wrong scheduler commands
- broken environment
- multiple login-node conflicts

### Worker

The Python process that actually imports packages like `uxarray`, opens files, and runs computations.

An endpoint can be `online` while the worker still fails because:

- `uxarray` is not installed remotely
- the scheduler cannot start jobs
- the file path is wrong for the cluster filesystem

## What Gets Installed Where

There are three distinct environments to think about.

### 1. Local machine: the MCP server

Install in this repository checkout:

```bash
uv sync
uv sync --extra hpc
```

This gives you:

- the MCP server itself
- `globus_compute_sdk` for submitting remote jobs
- local diagnostics like `scripts/hpc_doctor.py`

### 2. HPC login node: the endpoint software

Install in a dedicated remote virtual environment:

```bash
python3 -m venv ~/venvs/globus-compute
source ~/venvs/globus-compute/bin/activate
python -m pip install -U pip
python -m pip install globus-compute-endpoint globus-compute-sdk
```

This gives you:

- `globus-compute-endpoint`
- the runtime needed to start the endpoint manager

### 3. HPC worker environment: scientific packages

The worker also needs the scientific packages used by the submitted functions:

```bash
source ~/venvs/globus-compute/bin/activate
python -m pip install uxarray xarray netCDF4 h5netcdf
```

Without this, remote execution may work, but UXarray tools will fail with errors such as:

```text
ModuleNotFoundError: No module named 'uxarray'
```

## Authentication: Two Separate Places

You authenticate twice.

### Local authentication

Your local machine must authenticate once so it can submit work through Globus Compute:

```bash
cd /path/to/uxarray-mcp-server
uv run python -c "from globus_compute_sdk import Client; Client()"
```

Use a normal interactive terminal. Do not use a heredoc.

### Remote authentication

When you first start the endpoint on the cluster, Globus Compute may ask you to visit one or more URLs and paste authorization codes back into the terminal.

That authorizes the endpoint itself.

## Minimal End-to-End Setup

### On the HPC machine

1. Create and activate the endpoint virtualenv.
2. Install `globus-compute-endpoint`, `globus-compute-sdk`, `uxarray`, `xarray`, `netCDF4`, and `h5netcdf`.
3. Configure the endpoint:

```bash
globus-compute-endpoint configure uxarray-endpoint
```

4. Write a first-pass endpoint template. For a brand-new cluster, start with a single-host `LocalProvider` configuration, not PBS or SLURM.
5. Start the endpoint:

```bash
globus-compute-endpoint start uxarray-endpoint
```

6. Copy the endpoint UUID.

### On the local machine

1. Install repository dependencies with `uv sync --extra hpc`.
2. Authenticate the local Globus client once.
3. Copy `config.yaml.example` to `config.yaml`.
4. Add the endpoint UUID to `config.yaml`.
5. Run:

```bash
uv run python scripts/hpc_doctor.py --timeout-seconds 180
```

## What to Validate First

Do not start by debugging a large UXarray workflow.

Validate in this order:

1. The endpoint manager is reachable.
2. A tiny remote no-op function runs.
3. One exact remote file path is readable.
4. A generic NetCDF open works on that file.
5. Only then run UXarray-specific tools.

That is exactly why this repository now includes:

- `validate_hpc_setup(...)`
- `probe_path_access(...)`
- `scripts/hpc_doctor.py`

## Common Failure Modes

### `online` but still broken

`online` usually means the endpoint manager is alive. It does **not** prove the child endpoint or worker can actually run jobs.

### `qsub: command not found`

On PBS systems, the child endpoint may not have scheduler commands on `PATH`.

That must be fixed in the endpoint environment, not on your laptop.

### The file exists interactively but not remotely

The worker may need the canonical shared filesystem path, not the shell alias you typed on a login node.

Prefer:

```bash
readlink -f /path/to/file
```

and use the real shared path, for example `/gpfs/...`.

### `uxarray` missing remotely

This means the endpoint is alive but the worker environment is incomplete.

Install the scientific packages in the remote endpoint venv.

### Stale PID files or multiple login nodes

If you start and stop endpoints from different login nodes, you can get:

- stale `daemon.pid`
- "another instance is running"
- child-endpoint startup conflicts

Run the endpoint from one login node only, ideally inside `tmux`.

## Recommended Reading Order

If you are new to this entire stack, read in this order:

1. [Getting Started](getting-started.md)
2. [HPC Setup](hpc.md)
3. [Improv Playbook](improv.md) if you are on Argonne Improv
4. [Agentic Workflows](workflows.md) once the endpoint is healthy
