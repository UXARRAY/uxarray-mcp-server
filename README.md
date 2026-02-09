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

This server works with any MCP-compatible client. The examples below use Claude Desktop, but you can integrate with other MCP clients by following similar configuration steps. Refer to your client's documentation for MCP server setup.

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

### `inspect_variable(grid_path: str, data_path: str, variable_name: str = None)`

Inspects data variables in mesh datasets and returns their metadata.

**Parameters:**
- `grid_path`: Path to mesh grid file
- `data_path`: Path to data file with variables
- `variable_name`: Optional - inspect specific variable, or all if None

**Returns:**
- `variables`: List of variable info including:
  - `name`: Variable name
  - `dims`: Dimension names
  - `shape`: Array shape
  - `dtype`: Data type
  - `location`: Where data lives ("faces", "nodes", "edges", or "other")
  - `attrs`: Variable attributes (units, long_name, etc.)
  - `statistics`: Min, max, mean (if numeric)
- `grid_info`: Grid summary (n_face, n_node, n_edge)

**Example:**
Ask Claude: "Use inspect_variable to analyze variables in grid.nc and data.nc"

### `calculate_area(file_path: str)`

Calculates face areas for an unstructured mesh.

**Parameters:**
- `file_path`: Path to mesh file, or `healpix:<zoom>` to generate HEALPix mesh

**Returns:**
- `total_area`: Total surface area of the mesh
- `mean_area`: Mean face area
- `min_area`: Minimum face area
- `max_area`: Maximum face area
- `area_units`: Units of the area (m^2, km^2, etc.)
- `n_face`: Number of faces

**Example:**
Ask Claude: "Use calculate_area to compute face areas for mesh.nc"

### `calculate_zonal_mean(grid_path: str, data_path: str, variable_name: str, lat_spec: tuple | float | list = None, conservative: bool = False)`

Calculates zonal mean (latitude-band average) of a face-centered variable.

**Parameters:**
- `grid_path`: Path to mesh grid file
- `data_path`: Path to data file with variables
- `variable_name`: Name of the variable to compute zonal mean for (must be face-centered)
- `lat_spec`: Optional latitude specification:
  - `None`: Uses default (-90, 90, 10)
  - `tuple (start, end, step)`: Latitude range and interval
  - `float`: Single latitude for non-conservative
  - `list`: Explicit latitudes or band edges
- `conservative`: If True, performs area-weighted averaging over latitude bands. If False (default), performs intersection-weighted averaging at latitude lines.

**Returns:**
- `variable_name`: Name of the original variable
- `latitudes`: List of latitude values/bands
- `zonal_mean_values`: List of computed zonal mean values
- `conservative`: Whether conservative method was used
- `grid_info`: Grid summary (n_face, n_node, n_edge)

**Example:**
Ask Claude: "Use calculate_zonal_mean to compute the zonal mean of temperature from -60 to 60 degrees with 20 degree intervals"

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
