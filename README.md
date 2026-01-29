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

## Testing

Run the automated test suite:

```bash
uv run pytest
```

Tests are self-contained and do not require external mesh files.

## MCP Client Integration

This server works with any MCP-compatible client. The examples below use Claude Desktop, but you can integrate with other MCP clients (e.g., Cline, Zed, Continue, etc.) by following similar configuration steps. Refer to your client's documentation for MCP server setup.

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
      "command": "/path/to/uv",
      "args": [
        "--directory",
        "/path/to/uxarray-mcp-server",
        "run",
        "python",
        "-m",
        "uxarray_mcp.server"
      ]
    }
  }
}
```

Replace `/path/to/uv` with output from `which uv` and `/path/to/uxarray-mcp-server` with your project directory.

### Step 3: Restart Claude Desktop

Close and reopen Claude Desktop completely.

### Step 4: Test in Claude Desktop

Try asking Claude:

> "Use the inspect_mesh tool to analyze a mesh file at: /path/to/your/mesh.nc"
>
> Or generate a HEALPix mesh: "Use inspect_mesh with healpix:2"

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

**Parameters:**
- `file_path`: Path to mesh file, or `healpix:<zoom>` to generate HEALPix mesh

**Returns:**
- `format`: Mesh format (MPAS, UGRID, SCRIP, HEALPix, etc.)
- `n_face`: Number of faces (cells)
- `n_node`: Number of nodes (vertices)
- `n_edge`: Number of edges
- `n_max_face_nodes`: Maximum nodes per face
- `file_size_mb`: File size in MB

**Supported Formats:**
MPAS, UGRID, SCRIP, ESMF, Exodus, FESOM, ICON, HEALPix, and more

## Project Structure

```
uxarray-mcp-server/
├── .github/workflows/
│   └── ci.yml                      # CI/CD pipeline
├── src/uxarray_mcp/
│   ├── server.py                   # MCP server entry point
│   ├── __init__.py                 # Package exports
│   ├── __main__.py                 # CLI entry point
│   └── tools/
│       ├── __init__.py             # Tool exports
│       └── inspection.py           # inspect_mesh tool
├── tests/
│   ├── conftest.py                 # Test fixtures
│   ├── test_inspect_mesh.py        # Unit & integration tests
│   └── test_server.py              # Server tests
├── pyproject.toml                  # Dependencies & config
├── pytest.ini                      # Pytest configuration
└── README.md                       # This file
```

## Running the Server

Claude Desktop will automatically start the server when configured. To test manually:

```bash
uv run python -m uxarray_mcp.server
```

(Press Ctrl+C to stop)

## Development

**Add new tools:** Create new functions in `src/uxarray_mcp/tools/` and register them in `server.py`.

**Test changes:** Run `uv run pytest` after modifications.

**Update dependencies:** Run `uv add <package-name>` to add new packages.

## Resources

- [UXarray Documentation](https://uxarray.readthedocs.io/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
