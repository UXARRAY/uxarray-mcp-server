# UXarray MCP Server

An MCP (Model Context Protocol) server that gives AI agents a mesh-aware assistant — not just a flat tool shelf. Built on [UXarray](https://uxarray.readthedocs.io/) with support for local execution and remote HPC via Globus Compute.

## Features

- **Autonomous scientific agent** — Analyze → Plan → Execute → Verify loop with full reasoning trace
- **Provenance on every output** — every tool result carries `_provenance` with timestamp, versions, venue, and artifacts
- **Validation-gated workflows** — dataset validation runs before zonal mean; failures skip unreliable downstream steps
- **Dynamic tool registration** — HPC tools only appear in the tool list when an endpoint is configured
- **Execution mode control** — switch between `local`, `hpc`, and `auto` from the Claude UI without touching config files
- **Local + HPC execution** — files on HPC filesystems or meshes >1M faces are automatically routed to Globus Compute

## Installation

```bash
# Core (local execution only)
uv sync

# With HPC support (Globus Compute + Academy)
uv sync --extra hpc
```

## Testing

```bash
# Core tests (no HPC required)
uv run pytest tests/ --ignore=tests/test_remote_agent.py

# Full suite including HPC safety tests
uv run pytest tests/
```

## Tools Available

### Core Tools

#### `inspect_mesh(file_path)`
Analyze mesh topology — faces, nodes, edges, format detection.

- `file_path`: Path to mesh file, or `healpix:<zoom>` to generate a HEALPix mesh

Returns: `format`, `n_face`, `n_node`, `n_edge`, `n_max_face_nodes`, `file_size_mb`, `_provenance`

Supported formats: MPAS, UGRID, SCRIP, ESMF, Exodus, FESOM, ICON, HEALPix

---

#### `inspect_variable(grid_path, data_path, variable_name=None)`
Inspect data variables on a mesh — location, shape, statistics, attributes.

Returns: `variables` list with `name`, `dims`, `shape`, `dtype`, `location` (faces/nodes/edges), `statistics`, `attrs`; plus `_provenance`

---

#### `calculate_area(file_path)`
Calculate face areas for a mesh.

Returns: `total_area`, `mean_area`, `min_area`, `max_area`, `area_units`, `n_face`, `_provenance`

---

#### `calculate_zonal_mean(grid_path, data_path, variable_name, lat_spec=None, conservative=False)`
Latitude-band average of a face-centered variable.

- `lat_spec`: `None` → (-90, 90, 10°); `(start, end, step)` tuple; `float` for single latitude; `list` of explicit bands
- `conservative`: area-weighted averaging over bands (vs intersection-weighted)

Returns: `latitudes`, `zonal_mean_values`, `conservative`, `grid_info`, `_provenance`

---

#### `validate_dataset(grid_path, data_path)`
Check dataset integrity — NaN coverage, fill value consistency, dimension alignment.

Returns: `passed`, `n_variables_checked`, `n_variables_failed`, per-variable details, `_provenance`

---

#### `run_scientific_agent(file_path, data_path=None, variable_name=None)`
Autonomous four-stage pipeline. Inspects the mesh, plans which operations to run, executes them (locally or on HPC), and verifies the results.

- Auto-routes to HPC for files on known HPC filesystems (`/home/`, `/lus/`, `/scratch/`, etc.) or meshes >1M faces
- Skips zonal mean if validation fails
- Returns full `reasoning_trace`, `mesh_summary`, `area_results`, `variable_results`, `zonal_mean_results`, `validation_summary`, `verification`, and `_provenance`

```
Ask Claude: "Run a full scientific analysis on healpix:4"
Ask Claude: "Analyze /lus/grand/projects/climate/mesh.nc with data.nc"
```

---

#### `get_execution_mode()`
Returns the current execution mode (`local`, `hpc`, or `auto`) and whether an HPC endpoint is configured.

---

#### `set_execution_mode(mode)`
Switch execution mode without editing config files. Accepts `"local"`, `"hpc"`, or `"auto"`.

```
Ask Claude: "Switch to HPC execution mode"
Ask Claude: "Set execution back to local"
```

---

### HPC Tools *(only registered when an endpoint is configured)*

#### `inspect_mesh_hpc(file_path, use_remote=False)`
#### `calculate_area_hpc(file_path, use_remote=False)`
#### `inspect_variable_hpc(grid_path, data_path, variable_name=None, use_remote=False)`
#### `calculate_zonal_mean_hpc(grid_path, data_path, variable_name, lat_spec=None, conservative=False, use_remote=False)`

Same interface as core tools. Set `use_remote=True` to execute on HPC via Globus Compute. Falls back to local if the endpoint is unreachable.

Each HPC call runs a pre-flight health check before submitting to avoid hanging on a down endpoint.

---

## HPC Configuration

Edit `config.yaml`:

```yaml
hpc:
  globus_compute:
    endpoint_id: "your-endpoint-uuid"  # null for local-only
  execution_mode: "auto"               # local | hpc | auto
  timeout_seconds: 300
```

**`auto` mode** (default): local for small meshes on local paths; HPC for large meshes or HPC filesystem paths.

**Setup:**
1. Deploy a Globus Compute endpoint on your HPC system
2. Add the endpoint UUID to `config.yaml`
3. Install UXarray on the remote environment (the server uses `AllCodeStrategies` serialization so `uxarray_mcp` itself does not need to be installed remotely)
4. Restart the MCP server — HPC tools will appear automatically

## Provenance

Every tool result includes a `_provenance` block:

```json
{
  "_provenance": {
    "tool": "run_scientific_agent",
    "inputs": { "file_path": "healpix:4" },
    "execution_venue": "local",
    "timestamp_utc": "2026-03-18T...",
    "uxarray_version": "2025.12.0",
    "python_version": "3.13.0",
    "warnings": [],
    "artifacts": [
      { "type": "mesh_topology", "n_face": 3072, "format": "HEALPix" },
      { "type": "face_areas", "total_area": 5.1e14 }
    ],
    "selected_variable": "temperature",
    "validation_summary": { "passed": true, "n_variables_checked": 3 }
  }
}
```

## MCP Client Integration

Works with any MCP-compatible client. Example for Claude Desktop:

**`~/Library/Application Support/Claude/claude_desktop_config.json`:**

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

Replace paths using `which uv` and `pwd`. Restart Claude Desktop fully after editing.

## Project Structure

```
uxarray-mcp-server/
├── .github/workflows/
│   └── ci.yml                        # Split core + HPC CI lanes
├── docs/
│   └── architecture.html             # Interactive architecture diagram
├── src/uxarray_mcp/
│   ├── server.py                     # MCP server — dynamic tool registration
│   ├── provenance.py                 # Provenance tracking for all tool outputs
│   ├── domain/                       # Pure computation layer (no MCP/IO)
│   │   ├── mesh.py
│   │   ├── area.py
│   │   ├── variable.py
│   │   └── zonal.py
│   ├── remote/
│   │   ├── config.py                 # HPC configuration loader
│   │   ├── agent.py                  # Academy agent (Globus Compute orchestration)
│   │   ├── compute_functions.py      # Remote-serializable functions
│   │   └── health.py                 # Endpoint health checks
│   └── tools/
│       ├── inspection.py             # Core local tools
│       ├── remote_tools.py           # HPC-enabled wrappers (with pre-flight checks)
│       ├── scientific_agent.py       # Autonomous 4-stage agent
│       ├── execution_control.py      # get/set execution mode
│       └── capabilities.py           # Tool self-description
├── tests/
│   ├── conftest.py
│   ├── test_inspect_mesh.py
│   ├── test_inspect_variable.py
│   ├── test_calculate_area.py
│   ├── test_calculate_zonal_mean.py
│   ├── test_scientific_agent.py
│   ├── test_capabilities.py
│   ├── test_hpc_safety.py            # HPC pre-flight + fallback tests
│   ├── test_remote_agent.py          # Academy agent tests (requires hpc extra)
│   └── test_server.py
├── config.yaml                       # HPC endpoint + execution mode config
├── pyproject.toml
├── pytest.ini
└── README.md
```

## Running the Server

Claude Desktop starts the server automatically. To test manually:

```bash
uv run python -m uxarray_mcp.server
```

## Development

```bash
# Run all core tests
uv run pytest tests/ --ignore=tests/test_remote_agent.py -v

# Run HPC tests (requires uv sync --extra hpc)
uv run pytest tests/test_remote_agent.py tests/test_hpc_safety.py -v

# Add a new tool: create function in src/uxarray_mcp/tools/, register in server.py
```

## Resources

- [UXarray Documentation](https://uxarray.readthedocs.io/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Globus Compute](https://globus-compute.readthedocs.io/)
- [Academy](https://github.com/proxystore/academy)
