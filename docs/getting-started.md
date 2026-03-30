# Getting Started

This guide walks you through setting up the UXarray MCP Server from scratch.

```{note}
This guide uses Claude Desktop as the MCP client. Other MCP-compatible clients should work since the server uses standard stdio transport, but have not been tested.
```

## Prerequisites

- **Python 3.13+** — Check with: `python3 --version`
- **uv** — Install with: `pip install uv`
- **MCP Client** — Claude Desktop or any MCP-compatible client
- **Git** (optional) — For cloning the repository

## Quick Setup

```bash
cd /path/to/uxarray-mcp-server
bash SETUP.sh
```

Then skip to **Configure Claude Desktop** below.

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

### Step 2: Run tests

```bash
uv run pytest tests/ --ignore=tests/test_remote_agent.py
```

If you see all green passes, the server is ready.

### Step 3: (Optional) Configure HPC

If you want to run computations on an HPC system via Globus Compute:

```bash
cp config.yaml.example config.yaml
```

Then edit `config.yaml`:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-endpoint-uuid"
  execution_mode: "auto"      # local | hpc | auto
  timeout_seconds: 300
```

Leave `endpoint_id` as `null` to run everything locally. HPC tools will only appear when an endpoint is configured.

### Step 4: Configure Claude Desktop

Find your config file:

| Platform | Path |
|----------|------|
| macOS    | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux    | `~/.config/Claude/claude_desktop_config.json` |
| Windows  | `%APPDATA%\Claude\claude_desktop_config.json` |

Get your paths:

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

### Step 5: Restart Claude Desktop

Fully quit (`Cmd+Q` on macOS) and reopen. Closing the window is not enough.

### Step 6: Verify the connection

In Claude, ask:

```
Do you have access to an inspect_mesh tool?
```

Claude should confirm and describe the available tools.

## Try It Out

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

## Troubleshooting

**"Command not found: uv"**
: Install with `pip install uv`, then update your config with the full path from `which uv`.

**Tools not showing up in Claude**
: 1. Verify paths in the config are absolute and correct
  2. Fully quit and reopen Claude Desktop
  3. Check the Developer Console: View > Developer > Developer Tools > Console

**HPC tools not appearing**
: Make sure `endpoint_id` is set in `config.yaml` (not `null`), then restart the server.

**Tests failing**
: Run `uv sync` to reinstall dependencies, then `uv run pytest -v` for verbose output.
