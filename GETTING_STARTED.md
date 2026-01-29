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
