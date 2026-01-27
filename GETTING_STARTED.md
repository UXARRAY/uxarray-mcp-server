# Getting Started with UXarray MCP Server

This guide walks you through setting up the UXarray MCP Server from scratch.

---

## Prerequisites

Before you begin, ensure you have:

- [ ] **Python 3.13+** - Check with: `python3 --version`
- [ ] **pip** - Check with: `pip --version`
- [ ] **Claude Desktop** - Download from [claude.ai](https://claude.ai)
- [ ] **Git** (optional) - For cloning test files

---

## Quick Setup (Automated)

Run the setup script:

```bash
cd ~/Desktop/uxarray-mcp-server
bash SETUP.sh
```

This will:
1. [OK] Check prerequisites
2. [OK] Install dependencies
3. [OK] Test locally
4. [OK] Configure Claude Desktop

Then skip to **Step 6: Restart Claude Desktop** below.

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
cd ~/Desktop/uxarray-mcp-server
uv sync
```

This installs:
- uxarray (mesh analysis)
- fastmcp (MCP server)
- academy-py (HPC middleware)
- globus-compute-sdk (remote execution)
- pytest (testing)

### Step 3: Get Test Mesh Files

Clone the uxarray repository for test files:

```bash
cd ~/Desktop
git clone https://github.com/UXARRAY/uxarray.git
```

Test files will be at: `~/Desktop/uxarray/test/meshfiles/`

### Step 4: Test Locally

```bash
cd ~/Desktop/uxarray-mcp-server
uv run python test_local.py
```

**Expected output:**
```
[TEST] Testing UXarray MCP Server - inspect_mesh tool

============================================================
Testing MPAS Ocean Mesh
============================================================

[OK] Successfully inspected mesh!

Format: MPAS
Faces: 1,791
Nodes: 3,947
Edges: 5,754
...
```

If you see [OK], the tool works correctly!

### Step 5: Configure Claude Desktop

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
cd ~/Desktop/uxarray-mcp-server && pwd
# Output example: /Users/yourname/Desktop/uxarray-mcp-server
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
        "/Users/yourname/Desktop/uxarray-mcp-server",
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

### Step 6: Restart Claude Desktop

**Important:** You must completely quit and reopen:

1. Click `Claude` menu → `Quit Claude` (or press Cmd+Q)
2. Wait 10 seconds
3. Reopen Claude Desktop from Applications

**Don't just close the window!** You must fully quit the app.

### Step 7: Test the Integration

In Claude Desktop, type:

```
Do you have access to an inspect_mesh tool?
```

**If connected:** Claude will say "Yes" and describe the tool.

**If NOT connected:** Claude will say it doesn't have access to tools.

### Step 8: Demo the Tool

Try this prompt:

```
Use inspect_mesh to analyze this file:
/Users/yourname/Desktop/uxarray/test/meshfiles/mpas/QU/oQU480.231010.nc

What can you tell me about it?
```

(Replace `/Users/yourname` with your actual username)

**Expected response:**
Claude will call the tool and respond with mesh statistics like:
- Format: MPAS
- 1,791 faces
- 3,947 nodes
- etc.

---

## Troubleshooting

### Problem: "Command not found: uv"

**Solution:** Install uv with `pip install uv`, then update Claude config with full path from `which uv`

### Problem: "Tool not found" in Claude Desktop

**Solutions:**
1. Check config file has correct paths (no typos, absolute paths)
2. Verify uv path: `which uv`
3. Verify project path: `cd ~/Desktop/uxarray-mcp-server && pwd`
4. Make sure you fully quit Claude Desktop (not just closed window)
5. Check Claude Desktop's Developer Console for errors:
   - View → Developer → Developer Tools → Console tab

### Problem: "File not found" errors

**Solution:** 
- Use absolute paths to mesh files
- Verify test files exist: `ls ~/Desktop/uxarray/test/meshfiles/mpas/QU/`
- Clone uxarray if needed: `git clone https://github.com/UXARRAY/uxarray.git ~/Desktop/uxarray`

### Problem: Import errors when testing

**Solution:**
```bash
cd ~/Desktop/uxarray-mcp-server
uv sync  # Reinstall dependencies
```

### Problem: Red notification when Claude Desktop opens

**Common causes:**
1. uv not in PATH - use full path in config
2. Project path wrong - verify with `pwd`
3. Syntax error in config JSON - validate with `cat config.json | python -m json.tool`

---

## Verification Checklist

Before asking for help, verify:

- [ ] Python 3.13+ installed: `python3 --version`
- [ ] uv installed: `which uv`
- [ ] Dependencies installed: `uv sync` ran successfully
- [ ] Local test passes: `uv run python test_local.py` shows [OK]
- [ ] Config file exists: `cat ~/Library/Application\ Support/Claude/claude_desktop_config.json`
- [ ] Config has correct paths (uv and project directory)
- [ ] Claude Desktop fully quit and reopened
- [ ] Test files exist: `ls ~/Desktop/uxarray/test/meshfiles/`

---

## Next Steps

Once setup is complete:

1. **Try different mesh files:**
   ```
   Compare these meshes:
   1. /path/to/mesh1.nc
   2. /path/to/mesh2.nc
   ```

2. **Read the documentation:**
   ```bash
   cat README.md
   cat PROJECT_SUMMARY.md
   ```

3. **Prepare for Bi-Weekly 2:**
   - Add `inspect_variables` tool
   - Add `calculate_area` tool
   - Implement remote execution

---

## Resources

- **UXarray Docs:** https://uxarray.readthedocs.io/
- **FastMCP Docs:** https://github.com/jlowin/fastmcp
- **MCP Protocol:** https://modelcontextprotocol.io/
- **Project Issues:** Check with your mentor

---

**Need help?** Contact Rajeev Jain or check the troubleshooting section above.
