# Getting Started with UXarray MCP Server

This guide walks you through setting up the UXarray MCP Server from scratch.

**Note:** This guide uses Claude Desktop as an example MCP client. This server works with any MCP-compatible client (Cline, Zed, Continue, etc.). Configuration steps are similar — refer to your client's documentation for MCP setup.

---

## Prerequisites

- [ ] **Python 3.13+** — Check with: `python3 --version`
- [ ] **uv** — Install with: `pip install uv`
- [ ] **MCP Client** — Claude Desktop ([claude.ai](https://claude.ai)) or any MCP-compatible client
- [ ] **Git** (optional) — For cloning the repository

---

## Quick Setup (Automated)

```bash
cd /path/to/uxarray-mcp-server
bash SETUP.sh
```

Then skip to **Step 4: Configure Claude Desktop** below.

---

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

If you are new to Globus Compute, read [docs/globus-compute.md](docs/globus-compute.md)
before continuing with HPC setup. That guide explains the terms and the split
between local-machine setup, endpoint setup, and remote-worker packages.

### Step 2: Run Tests

```bash
uv run pytest tests/ --ignore=tests/test_remote_agent.py
```

**Expected output:**
```
142 passed
```

If you see green passes, the server is ready.

### Step 3: (Optional) Configure HPC

If you want to run computations on an HPC system via Globus Compute, think
about the setup in three layers:

1. the **local machine** running this repository
2. the **endpoint** running on the HPC machine
3. the **remote worker environment** that must also have `uxarray` and other
   scientific packages installed

First create a local config file:

```bash
cp config.yaml.example config.yaml
```

Then edit `config.yaml`:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-endpoint-uuid"   # get this from your HPC admin or globus-compute-endpoint list
  execution_mode: "auto"                # local | hpc | auto
  timeout_seconds: 300
```

Leave `endpoint_id` as `null` to run everything locally. HPC tools will only appear in Claude's tool list when an endpoint is configured.

Before that endpoint UUID will actually work, you must also:

- on the **local machine**:
  - run `uv sync --extra hpc`
  - run `uv run python -c "from globus_compute_sdk import Client; Client()"`
- on the **remote machine**:
  - create a virtual environment for the endpoint
  - install `globus-compute-endpoint` and `globus-compute-sdk`
  - install `uxarray`, `xarray`, `netCDF4`, and `h5netcdf`
  - run `globus-compute-endpoint configure <endpoint-name>`
  - start the endpoint and copy its UUID into `config.yaml`

### Step 4: Configure Claude Desktop

**A. Find your config file:**

```bash
# macOS
~/Library/Application Support/Claude/claude_desktop_config.json

# Linux
~/.config/Claude/claude_desktop_config.json

# Windows
%APPDATA%\Claude\claude_desktop_config.json
```

**B. Get your paths:**

```bash
which uv          # e.g. /opt/homebrew/bin/uv
pwd               # run from the project directory
```

**C. Edit the config:**

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

### Step 5: Restart Claude Desktop

Fully quit (`Cmd+Q` on macOS) and reopen. Closing the window is not enough.

### Step 6: Verify the connection

In Claude, ask:

```
Do you have access to an inspect_mesh tool?
```

Claude should confirm and describe the available tools.

---

## Try it out

**Inspect a HEALPix mesh:**
```
Use inspect_mesh with healpix:4
```

**Run the full scientific agent:**
```
Run a complete scientific analysis on healpix:4
```

**Check and change execution mode:**
```
What is the current execution mode?
Switch to HPC execution mode
```

**Analyze a file on HPC** (if endpoint configured):
```
Analyze /lus/grand/projects/climate/mesh.nc — use remote execution
```

**Prove that one exact remote file is readable first:**
```
Run validate_hpc_setup with probe_timeout_seconds=180 and sample_path="/path/to/file.nc"
Run probe_path_access on /path/to/file.nc with use_remote=True
```

---

## Troubleshooting

**"Command not found: uv"**
Install with `pip install uv`, then update your config with the full path from `which uv`.

**Tools not showing up in Claude**
1. Verify paths in the config are absolute and correct
2. Fully quit and reopen Claude Desktop
3. Check the Developer Console: View → Developer → Developer Tools → Console

**HPC tools not appearing**
Make sure `endpoint_id` is set in `config.yaml` (not `null`), then restart the server.

**I do not know what Globus Compute or an endpoint is**
Read [docs/globus-compute.md](docs/globus-compute.md) first. It explains what
gets installed locally versus remotely, what an endpoint does, and why the
remote worker also needs `uxarray`.

**Remote endpoint is online but a real file still will not open**
Start with a single-host endpoint template first, then run
`validate_hpc_setup(..., sample_path=...)` and `probe_path_access(..., use_remote=True)`.
Only switch back to PBS or SLURM after that works.

**Tests failing**
```bash
uv sync          # reinstall dependencies
uv run pytest -v # run with verbose output
```

---

## Verification Checklist

- [ ] `python3 --version` → 3.13+
- [ ] `which uv` → returns a path
- [ ] `uv sync` ran without errors
- [ ] `uv run pytest tests/ --ignore=tests/test_remote_agent.py` → all green
- [ ] Claude Desktop config has correct absolute paths
- [ ] Claude Desktop fully quit and reopened

---

## Resources

- [UXarray Docs](https://uxarray.readthedocs.io/)
- [FastMCP Docs](https://github.com/jlowin/fastmcp)
- [MCP Protocol](https://modelcontextprotocol.io/)
- [Globus Compute](https://globus-compute.readthedocs.io/)

---

**Need help?** Check the troubleshooting section above or contact your team.

---

## Optional: Run Tools on an HPC Cluster

For the full HPC setup, debugging workflow, and endpoint templates, use:

- [docs/globus-compute.md](docs/globus-compute.md) for the first-time-user Globus Compute explanation
- [docs/hpc.md](docs/hpc.md) for the generic cluster bring-up flow
- [docs/improv.md](docs/improv.md) for the exact Argonne Improv lessons learned
- [docs/workflows.md](docs/workflows.md) for sequential submit/poll/branch workflows
- `scripts/hpc_doctor.py` for local diagnostics
- `scripts/improv_endpoint.sh` for Improv endpoint templates
- `scripts/agentic_hpc_loop.py` for a working example of a multi-step remote workflow
