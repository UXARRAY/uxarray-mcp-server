# HPC Setup

By default, all tools run locally on your machine. If you have access to an HPC cluster (like Improv, Chrysalis, or any SLURM/PBS system), you can offload heavy computations there instead.

## How It Works

You set up a small background process (called an "endpoint") on your cluster. When you call a tool with `use_remote=True`, the MCP server sends the job to that endpoint via Globus. It runs on the cluster using the full resources available there, and the result comes back to Claude.

The job travels from your laptop to the Globus cloud to your cluster and back. No open ports or inbound SSH required.

## Step 1: Create a Globus Account

Sign up for free at [globus.org](https://www.globus.org). Use your institutional email if your cluster requires it.

## Step 2: Set Up the Endpoint on Your Cluster

SSH into your cluster and run:

```bash
# Load a conda-compatible Python module (name varies by cluster)
module load miniforge3   # or anaconda3, miniconda, etc.

# Create a dedicated environment
conda create -n globus-env python=3.11 -y
conda activate globus-env

# Install the endpoint software and remote worker packages
pip install globus-compute-endpoint uxarray xarray netCDF4 h5netcdf

# Create and start your endpoint
globus-compute-endpoint configure uxarray-endpoint
globus-compute-endpoint start uxarray-endpoint
```

When the endpoint starts, it may show one or more Globus auth URLs. Open each
URL in your browser, complete the login, and paste the matching code back at
the prompt.

After both codes are accepted, you'll see:

```
>>> Endpoint ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx <<<
```

Copy that UUID — you'll need it in Step 4.

## Step 3: Authenticate the Local Client (One-Time)

Back on your laptop, run this once to authenticate the MCP server's connection to Globus:

```bash
cd /path/to/uxarray-mcp-server
uv run python -c "from globus_compute_sdk import Client; Client()"
```

A browser auth URL will appear. Visit it, log in, paste the code back. This only needs to be done once — the token is saved locally.

```{warning}
Run the command above in an interactive terminal. Do not use a heredoc such as
`python - <<'PY' ... PY`, or Globus will fail to read the pasted authorization
code from stdin.
```

## Step 4: Add Your Endpoint UUID

Create a local config file if you don't have one:

```bash
cp config.yaml.example config.yaml
```

Then edit `config.yaml`:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-uuid-here"
  execution_mode: "auto"
  timeout_seconds: 300
```

Restart Claude Desktop after saving.

## Step 5: Validate HPC Readiness

Start with the built-in diagnostic instead of a real remote dataset:

```
Run validate_hpc_setup
```

Or validate one exact remote path directly:

```
Run validate_hpc_setup with probe_timeout_seconds=180 and sample_path="/path/to/file.nc"
Run probe_path_access on /path/to/file.nc with use_remote=True
```

This goes deeper than `get_execution_mode`. It checks:

- local Globus auth and SDK availability
- endpoint-manager status
- a tiny real remote-task submission

That last step is important: an endpoint can be `online` while the spawned user
endpoint still fails to submit jobs or start workers.

On PBS systems such as Improv, a common failure looks like:

```text
/bin/sh: qsub: command not found
```

If that happens, add the PBS tools to the endpoint environment, restart the
endpoint, then rerun `validate_hpc_setup`.

## New Cluster Bring-Up: Single-Host Validation First

Before you debug PBS or SLURM worker lifecycle, prove that the endpoint can run
one task on the endpoint host and read one real file. Replace the user endpoint
template with a single-host `LocalProvider` configuration:

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

Use this mode to verify:

- `validate_hpc_setup(probe_timeout_seconds=180, sample_path="/path/to/file.nc")`
- `probe_path_access("/path/to/file.nc", use_remote=True)`

Once those pass, switch the template back to PBS or SLURM and debug scheduler
submission separately.

## Common Misses

- `get_execution_mode()` saying `online` is not enough. Always run `validate_hpc_setup()` before the first real remote job.
- The remote worker may need the canonical filesystem path, not a login-node alias. Prefer `readlink -f` and the real shared filesystem path.
- PBS systems may need `/opt/pbs/bin` in the child endpoint environment.
- Remote worker packages matter separately from local packages. The endpoint can be healthy while `uxarray` is still missing remotely.
- Stale `daemon.pid` files and multiple login nodes can make the child endpoint fail even when the manager is healthy.
- Local Globus auth must be done from an interactive terminal, not a heredoc.

## Step 6: Use Remote Execution

Now any HPC-capable tool accepts a `use_remote` flag:

```
Use calculate_area_hpc on healpix:2 with use_remote=True
```

Claude will send the job to your cluster and return the result.

## Execution Modes

| Mode | Behavior |
|------|----------|
| `local` | Always run on your machine |
| `hpc` | Always send to the HPC endpoint (fails if endpoint is down) |
| `auto` | Local for small meshes on local paths; HPC for large meshes or HPC filesystem paths |

**Auto mode** uses two signals to decide:
- **File path** — paths on known HPC filesystems (`/home/`, `/lus/`, `/grand/`, `/scratch/`, `/projects/`, `/gpfs/`) route to HPC
- **Mesh size** — meshes with more than 1 million faces route to HPC

You can switch modes at runtime from Claude without editing config files:

```
Switch to HPC execution mode
Set execution back to local
```

## Keeping the Endpoint Running

The endpoint process needs to be running on your cluster whenever you want to use `use_remote=True`. If you log out, it may stop. To check:

```bash
globus-compute-endpoint list
```

To restart if stopped:

```bash
module load miniforge3
conda activate globus-env
globus-compute-endpoint start uxarray-endpoint
```

```{note}
The endpoint UUID in `config.yaml` is personal — it's tied to your Globus account and your cluster allocation. Each user needs to set up their own endpoint.
```
