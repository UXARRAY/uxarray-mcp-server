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

If you want to run computations on an HPC system via Globus Compute, edit `config.yaml`:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-endpoint-uuid"   # get this from your HPC admin or globus-compute-endpoint list
  execution_mode: "auto"                # local | hpc | auto
  timeout_seconds: 300
```

Leave `endpoint_id` as `null` to run everything locally. HPC tools will only appear in Claude's tool list when an endpoint is configured.

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

By default, all tools run locally on your machine. If you have access to an HPC cluster (like Improv, Chrysalis, or any SLURM/PBS system), you can offload heavy computations there instead. The job travels from your laptop → Globus cloud → your cluster → back to Claude. No open ports or inbound SSH required.

### How it works

You set up a small background process (called an "endpoint") on your cluster. When you call a tool with `use_remote=True`, the MCP server sends the job to that endpoint via Globus, it runs on the cluster using the full resources available there, and the result comes back to Claude.

### Step 1: Create a Globus account

Sign up for free at [globus.org](https://www.globus.org). Use your institutional email if your cluster requires it.

### Step 2: Set up the endpoint on your cluster

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

When the endpoint starts, it will show a Globus auth URL **twice** — each one needs its own unique code from the browser. Open each URL in a new browser tab, complete the login, and paste the code back at each prompt. After both codes are accepted, you'll see:

```
>>> Endpoint ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx <<<
```

Copy that UUID — you'll need it in Step 4.

### Step 3: Authenticate the local client (one-time)

Back on your laptop, run this once to authenticate the MCP server's connection to Globus:

```bash
cd /path/to/uxarray-mcp-server
uv run python -c "from globus_compute_sdk import Client; Client()"
```

A browser auth URL will appear. Visit it, log in, paste the code back. This only needs to be done once — the token is saved locally.

### Step 4: Add your endpoint UUID to config.yaml

Open `config.yaml` in the project root and add your UUID:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-uuid-here"

  execution_mode: "auto"
  timeout_seconds: 300
```

Restart Claude Desktop after saving.

### Step 5: Use remote execution

Now any HPC-capable tool accepts a `use_remote` flag:

```
Use calculate_area_hpc on healpix:2 with use_remote=True
```

Claude will send the job to your cluster and return the result.

### Keeping the endpoint running

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

> **Note:** The endpoint UUID in `config.yaml` is personal — it's tied to your Globus account and your cluster allocation. Each user needs to set up their own endpoint.
