# Getting Started with UXarray MCP Server

This guide walks you through setting up the UXarray MCP Server from scratch.

**Note:** This guide uses Claude Desktop as an example MCP client. This server works with any MCP-compatible client (Cline, Zed, Continue, etc.). Configuration steps are similar - refer to your client's documentation for MCP setup.

---

## Prerequisites

Before you begin, ensure you have:

- [ ] **Python 3.13+** - Check with: `python3 --version`
- [ ] **pip** - Check with: `pip --version`
- [ ] **MCP Client** - Claude Desktop ([claude.ai](https://claude.ai)) or any MCP-compatible client
- [ ] **Git** (optional) - For cloning the repository

---

## Quick Setup (Automated)

Run the setup script:

```bash
cd /path/to/uxarray-mcp-server
bash SETUP.sh
```

This will:
1. Check prerequisites
2. Install dependencies
3. Run automated tests
4. Provide next steps

Then skip to **Step 5: Configure Claude Desktop** below.

---

## Manual Setup (Step-by-Step)

### Step 1: Install uv

```bash
pip install uv
```

Verify installation:
```bash
which uv
# Should output: /path/to/uv
```

### Step 2: Install Project Dependencies

```bash
cd /path/to/uxarray-mcp-server
uv sync
```

This installs:
- uxarray (mesh analysis)
- fastmcp (MCP server)
- pytest (testing)

### Step 3: Run Tests

Run the automated test suite:

```bash
uv run pytest
```

**Expected output:**
```
tests/test_inspect_mesh.py .......                                       [ 87%]
tests/test_server.py .                                                   [100%]

=============================== 8 passed in 1.32s ==============================
```

If you see green passes, the tool is ready!

### Step 4: Configure Claude Desktop

**A. Find your config file location:**

```bash
# macOS
CONFIG_FILE="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

# Linux
# CONFIG_FILE="$HOME/.config/Claude/claude_desktop_config.json"

# Windows
# CONFIG_FILE="%APPDATA%\Claude\claude_desktop_config.json"
```

**B. Get required paths:**

```bash
# Find uv path
which uv
# Output example: /opt/anaconda3/bin/uv

# Get project path
cd /path/to/uxarray-mcp-server && pwd
# Output example: /Users/yourname/path/to/uxarray-mcp-server
```

**C. Create/edit the config file:**

On macOS:
```bash
nano "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
```

Add this content (replace paths with YOUR actual paths from step B):

```json
{
  "mcpServers": {
    "uxarray": {
      "command": "/opt/anaconda3/bin/uv",
      "args": [
        "--directory",
        "/Users/yourname/path/to/uxarray-mcp-server",
        "run",
        "python",
        "-m",
        "uxarray_mcp.server"
      ]
    }
  }
}
```

**Critical:** Use absolute paths, not `~` or relative paths!

### Step 5: Restart Claude Desktop

**Important:** You must completely quit and reopen:

1. Click `Claude` menu → `Quit Claude` (or press Cmd+Q)
2. Wait 10 seconds
3. Reopen Claude Desktop from Applications

**Don't just close the window!** You must fully quit the app.

### Step 6: Test the Integration

In Claude Desktop, type:

```
Do you have access to an inspect_mesh tool?
```

**If connected:** Claude will say "Yes" and describe the tool.

**If NOT connected:** Claude will say it doesn't have access to tools.

### Step 7: Demo the Tool

Try these prompts:

**With a local mesh file:**
```
Use inspect_mesh to analyze this file:
/path/to/your/mesh.nc
```

**Generate a HEALPix mesh:**
```
Use inspect_mesh with healpix:2 to generate and analyze a HEALPix mesh
```

**Expected response:**
Claude will call the tool and respond with mesh statistics like:
- Format: MPAS (or HEALPix)
- Number of faces, nodes, edges
- Maximum nodes per face
- File size

---

## Troubleshooting

### Problem: "Command not found: uv"

**Solution:** Install uv with `pip install uv`, then update Claude config with full path from `which uv`

### Problem: "Tool not found" in Claude Desktop

**Solutions:**
1. Check config file has correct paths (no typos, absolute paths)
2. Verify uv path: `which uv`
3. Verify project path: `cd /path/to/uxarray-mcp-server && pwd`
4. Make sure you fully quit Claude Desktop (not just closed window)
5. Check Claude Desktop's Developer Console for errors:
   - View → Developer → Developer Tools → Console tab

### Problem: Import errors when testing

**Solution:**
```bash
cd /path/to/uxarray-mcp-server
uv sync  # Reinstall dependencies
```

### Problem: Red notification when Claude Desktop opens

**Common causes:**
1. uv not in PATH - use full path in config
2. Project path wrong - verify with `pwd`
3. Syntax error in config JSON - validate with `cat config.json | python -m json.tool`

### Problem: Tests failing

**Solution:**
```bash
# Make sure you're in the project directory
cd /path/to/uxarray-mcp-server

# Reinstall dependencies
uv sync

# Run tests with verbose output
uv run pytest -v
```

---

## Verification Checklist

Before asking for help, verify:

- [ ] Python 3.13+ installed: `python3 --version`
- [ ] uv installed: `which uv`
- [ ] Dependencies installed: `uv sync` ran successfully
- [ ] Tests pass: `uv run pytest` shows all green
- [ ] Config file exists: `cat ~/Library/Application\ Support/Claude/claude_desktop_config.json`
- [ ] Config has correct paths (uv and project directory)
- [ ] Claude Desktop fully quit and reopened

---

## Next Steps

Once setup is complete:

1. **Try different mesh files:**
   Test with various mesh formats (MPAS, UGRID, SCRIP, etc.)

2. **Generate HEALPix meshes:**
   Experiment with different zoom levels: `healpix:1`, `healpix:2`, `healpix:3`

3. **Read the documentation:**
   ```bash
   cat README.md
   ```

4. **Start developing:**
   Add new tools following the patterns in `src/uxarray_mcp/tools/inspection.py`

---

## Resources

- **UXarray Docs:** https://uxarray.readthedocs.io/
- **FastMCP Docs:** https://github.com/jlowin/fastmcp
- **MCP Protocol:** https://modelcontextprotocol.io/
- **Project Repository:** Check with your team

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
