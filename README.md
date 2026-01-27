# UXarray MCP Server

An MCP (Model Context Protocol) server that provides AI agents with tools for analyzing unstructured meshes using UXarray.

## Features

- **inspect_mesh**: Analyze mesh topology (faces, nodes, edges, format)
- Support for multiple formats: MPAS, UGRID, SCRIP, ESMF, Exodus, and more
- Integration with Claude Desktop and other AI clients

## Installation

```bash
# Install dependencies
uv sync
```

## Testing Locally

Run the test script to verify the tool works:

```bash
uv run python test_local.py
```

This will test the `inspect_mesh` tool with sample mesh files from the uxarray test directory.

## Connecting to Claude Desktop

### Step 1: Find your Claude Desktop config file

The config file location depends on your OS:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

### Step 2: Add the MCP server configuration

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "uxarray": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/dayanabdulla/Desktop/uxarray-mcp-server",
        "run",
        "python",
        "-m",
        "uxarray_mcp.server"
      ]
    }
  }
}
```

### Step 3: Restart Claude Desktop

Close and reopen Claude Desktop completely.

### Step 4: Test in Claude Desktop

Try asking Claude:

> "Use the inspect_mesh tool to analyze this file: /Users/dayanabdulla/Desktop/uxarray/test/meshfiles/mpas/QU/oQU480.231010.nc"

## Example Output

```
This is an MPAS format mesh with:
- 1,791 faces (ocean cells)
- 3,947 nodes (corner points)
- 5,754 edges
- Hexagonal cells (max 6 nodes per face)
- File size: 4.61 MB
```

## Tools Available

### `inspect_mesh(file_path: str)`

Analyzes an unstructured mesh file and returns topology information.

**Supported Formats:**
MPAS, UGRID, SCRIP, ESMF, Exodus, FESOM, ICON, and more

## Project Structure

```
uxarray-mcp-server/
├── src/uxarray_mcp/
│   ├── server.py       # MCP tools (inspect_mesh)
│   ├── __init__.py     # Package exports
│   └── __main__.py     # Server entry point
├── test_local.py       # Local testing script
├── pyproject.toml      # Dependencies
└── README.md           # This file
```

## Running the Server

Claude Desktop will automatically start the server when configured. To test manually:

```bash
uv run python -m uxarray_mcp.server
```

(Press Ctrl+C to stop)

## Development

**Add new tools:** Edit `src/uxarray_mcp/server.py` and add functions with the `@mcp.tool()` decorator.

**Test changes:** Run `uv run python test_local.py` after modifications.

**Update dependencies:** Run `uv add <package-name>` to add new packages.

## Bi-Weekly Milestones

- **[DONE] Bi-Weekly 1 (Jan 19-30):** `inspect_mesh` tool with local file support
- **[TODO] Bi-Weekly 2 (Jan 31-Feb 13):** `inspect_variables`, `calculate_area`, remote execution
- **[TODO] Bi-Weekly 3 (Feb 14-27):** Regridding with GPU acceleration
- **[TODO] Bi-Weekly 4 (Feb 28-Mar 13):** Autonomous agent with resource management

## Resources

- [UXarray Documentation](https://uxarray.readthedocs.io/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
