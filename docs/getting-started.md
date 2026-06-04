# Getting Started

This guide walks you through setting up the UXarray MCP Server from scratch.

```{note}
This guide uses Claude Desktop as the MCP client. Other MCP-compatible clients should work since the server uses standard stdio transport, but have not been tested.
```

## Prerequisites

- **Python 3.11+** — Check with: `python3 --version`
- **uv** — Install with: `pip install uv`
- **MCP Client** — Claude Desktop or any MCP-compatible client
- **Git** (optional) — For cloning the repository

## Quick Setup

### User Install

After the package is published, install the MCP server as a command-line tool:

```bash
uv tool install uxarray-mcp
uxarray-mcp setup
```

For HPC support, include the optional Globus Compute dependencies:

```bash
uv tool install "uxarray-mcp[hpc]"
uxarray-mcp setup
```

Then skip to **Configure Claude Desktop** below. If you need the cluster helper
scripts in `scripts/`, use the repository checkout path instead.

### Repository Checkout

```bash
cd /path/to/uxarray-mcp-server
bash SETUP.sh
```

This script installs core dependencies and runs the local test suite. Then skip
to **Configure Claude Desktop** below.

## Manual Setup

### Step 1: Install dependencies

**Core only (local execution):**

```bash
cd /path/to/uxarray-mcp-server
uv sync
```

**With HPC support** (Globus Compute + Academy — optional):

```bash
uv sync --extra hpc
```

If you are new to Globus Compute, read [Globus Compute Primer](globus-compute.md)
before continuing with HPC setup. That guide explains what an endpoint is and
what gets installed locally versus remotely.

### Step 2: Run tests

```bash
uv run pytest tests/ --ignore=tests/test_remote_agent.py
```

If you see all green passes, the server is ready.

### Step 3: (Optional) Configure HPC

If you want to run computations on an HPC system via Globus Compute, think
about the setup in three layers:

1. the **local machine** running this repository
2. the **endpoint** running on the HPC machine
3. the **remote worker environment** that must also have `uxarray` and the
   scientific I/O packages installed

Then configure the local side with the CLI. This writes a private user config
under `~/.config/uxarray-mcp/`; do not commit endpoint UUIDs to the repository.

```bash
uxarray-mcp setup
uxarray-mcp endpoints add <name> <endpoint-uuid> --set-default
```

The equivalent private config schema is:

```yaml
hpc:
  execution_mode: "auto"      # local | hpc | auto
  timeout_seconds: 300
  default_endpoint: "improv"
  endpoints:
    improv:
      endpoint_id: "your-endpoint-uuid"
```

Omit endpoints to run everything locally. The same MCP tools are always
registered; use `use_remote=True` and an optional `endpoint="name"` to request
remote execution.

Before that endpoint UUID will work, you must also:

- on the **local machine**:
  - run `uv sync --extra hpc`
  - run `uv run python -c "from globus_compute_sdk import Client; Client()"`
- on the **remote machine**:
  - create a Python environment for the endpoint
  - install `globus-compute-endpoint` and `globus-compute-sdk`
  - install `uxarray`, `xarray`, `netCDF4`, and `h5netcdf`
  - run `globus-compute-endpoint configure <endpoint-name>`
  - start the endpoint and add its UUID with `uxarray-mcp endpoints add`

Before you try a real remote file, authenticate the local machine once:

```bash
uv run python -c "from globus_compute_sdk import Client; Client()"
```

```{warning}
Run the command above in a normal interactive terminal. Do not wrap it in a
heredoc such as `python - <<'PY' ... PY`, or the Globus prompt will fail with
an EOF error because stdin is already consumed.
```

### Step 4: Configure Claude Desktop

Find your config file:

| Platform | Path |
|----------|------|
| macOS    | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux    | `~/.config/Claude/claude_desktop_config.json` |
| Windows  | `%APPDATA%\Claude\claude_desktop_config.json` |

For a repository checkout, get your paths:

```bash
which uv          # e.g. /opt/homebrew/bin/uv
pwd               # run from the project directory
```

Edit the config:

```json
{
  "mcpServers": {
    "uxarray": {
      "command": "/opt/homebrew/bin/uv",
      "args": [
        "--directory",
        "/Users/yourname/uxarray-mcp-server",
        "run",
        "python",
        "-m",
        "uxarray_mcp.server"
      ]
    }
  }
}
```

Use **absolute paths** — no `~` or relative paths.

If you installed with `uv tool install`, the config block is simpler:

```json
{
  "mcpServers": {
    "uxarray": {
      "command": "uxarray-mcp",
      "args": ["serve"]
    }
  }
}
```

If your MCP client cannot find `uxarray-mcp`, replace `command` with the full
path printed by `which uxarray-mcp`.

### Step 5: Restart Claude Desktop

Fully quit (`Cmd+Q` on macOS) and reopen. Closing the window is not enough.

### Step 6: Verify the connection

In Claude, ask:

```
Do you have access to the UXarray MCP front-door tools?
```

Claude should confirm and describe the available tools.

## Try It Out

**Inspect a HEALPix mesh:**

```
Use run_analysis with operation="inspect_mesh" and grid_path="healpix:4"
```

**Run the full scientific agent:**

```
Run a complete scientific analysis on healpix:4
```

**Create a reusable session and run the persisted workflow:**

```
Create a session called baseline-analysis
Register /path/to/grid.nc and /path/to/data.nc in that session
Run the workflow for temperature using the registered dataset
```

**Check and change execution mode:**

```
Diagnose my configured endpoint status
```

**Validate the full HPC path before a real job:**

```
Run diagnose_endpoint with action="validate"
```

**Validate one exact remote file before debugging UXarray parsing:**

```
Run diagnose_endpoint with action="validate" and file_path="/path/to/file.nc"
Run probe_path_access on /path/to/file.nc with use_remote=True
```

For the full HPC playbook and reusable scripts, see:

- [HPC Setup](hpc.md)
- [Improv Playbook](improv.md)
- [Agentic HPC Workflows](workflows.md)

## Troubleshooting

**"Command not found: uv"**
: Install with `pip install uv`, then update your config with the full path from `which uv`.

**Tools not showing up in Claude**
: 1. Verify paths in the config are absolute and correct
  2. Fully quit and reopen Claude Desktop
  3. Check the Developer Console: View > Developer > Developer Tools > Console

**Remote calls fall back locally**
: Run `diagnose_endpoint(action="status")` or
  `diagnose_endpoint(action="validate")` and make sure the
  endpoint manager and worker probe both pass. The tool list itself is unified;
  there are no separate HPC-only tool names.

**Endpoint is registered but remote tasks still fail**
: Endpoint status only confirms the endpoint manager is reachable.
  Run `diagnose_endpoint(action="validate")` to catch deeper issues such as missing local Globus
  auth, missing `globus_compute_sdk`, PBS submission failures like
  `qsub: command not found`, or child-endpoint startup problems.

**I do not know what Globus Compute or an endpoint is**
: Read [Globus Compute Primer](globus-compute.md) first.
  It explains local machine vs endpoint vs remote worker packages.

**Brand-new cluster bring-up is getting stuck in PBS/SLURM**
: Start with a single-host endpoint template first. Prove that
  `diagnose_endpoint(action="validate", file_path=...)` and
  `probe_path_access(..., use_remote=True)`
  work on one real file, then switch the endpoint back to PBS/SLURM.

**I want reusable CLI helpers, not just MCP prompts**
: Use `scripts/hpc_doctor.py` for local diagnostics,
  `scripts/agentic_hpc_loop.py` for sequential remote workflows, and
  `scripts/improv_endpoint.sh` when configuring Argonne Improv.

**Tests failing**
: Run `uv sync` to reinstall dependencies, then `uv run pytest -v` for verbose output.
