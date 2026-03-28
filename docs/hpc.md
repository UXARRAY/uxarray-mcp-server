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

# Install the endpoint software and uxarray
pip install globus-compute-endpoint uxarray

# Create and start your endpoint
globus-compute-endpoint configure uxarray-endpoint
globus-compute-endpoint start uxarray-endpoint
```

When the endpoint starts, it will show a Globus auth URL **twice** — each one needs its own unique code from the browser. Open each URL in a new browser tab, complete the login, and paste the code back at each prompt.

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

## Step 5: Use Remote Execution

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
