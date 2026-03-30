# Tools Reference

All tools available through the MCP server. Each tool returns structured data with a `_provenance` block for traceability.

## Core Tools

### `inspect_mesh`

Analyze mesh topology — faces, nodes, edges, format detection.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `file_path` | `str` | Path to mesh file, or `healpix:<zoom>` to generate a HEALPix mesh |

**Returns:** `format`, `n_face`, `n_node`, `n_edge`, `n_max_face_nodes`, `file_size_mb`, `_provenance`

**Supported formats:** MPAS, UGRID, SCRIP, ESMF, Exodus, FESOM, ICON, HEALPix

---

### `inspect_variable`

Inspect data variables on a mesh — location, shape, statistics, attributes.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the grid/mesh file |
| `data_path` | `str` | Path to the data file |
| `variable_name` | `str` (optional) | Specific variable to inspect, or all if omitted |

**Returns:** `variables` list with `name`, `dims`, `shape`, `dtype`, `location`, `statistics`, `attrs`; plus `_provenance`

---

### `calculate_area`

Calculate face areas for a mesh.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `file_path` | `str` | Path to mesh file, or `healpix:<zoom>` |

**Returns:** `total_area`, `mean_area`, `min_area`, `max_area`, `area_units`, `n_face`, `_provenance`

---

### `calculate_zonal_mean`

Latitude-band average of a face-centered variable.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the grid/mesh file |
| `data_path` | `str` | Path to the data file |
| `variable_name` | `str` | Name of the face-centered variable to average |
| `lat_spec` | `tuple`, `float`, `list`, or `None` | Latitude specification (see below) |
| `conservative` | `bool` | Area-weighted averaging over bands (default: `False`) |

**`lat_spec` options:**

- `None` — default bands from -90 to 90 in 10-degree steps
- `(start, end, step)` — custom range
- `float` — single latitude
- `list` — explicit band edges

**Returns:** `variable_name`, `latitudes`, `zonal_mean_values`, `conservative`, `grid_info`, `_provenance`

---

### `validate_dataset`

Check dataset integrity — NaN coverage, Inf values, and common fill value detection.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the grid/mesh file |
| `data_path` | `str` | Path to the data file |

**Returns:** `passed`, `n_variables_checked`, `n_variables_failed`, per-variable details, `_provenance`

---

### `get_capabilities`

Discover which tools and UXarray features apply to a specific grid and dataset. Filters results based on grid topology and variable locations.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the grid/mesh file |
| `data_path` | `str` (optional) | Path to the data file |

**Returns:** Available MCP tools, applicable native UXarray methods, and recommendations.

---

### `get_execution_mode`

Returns the current execution mode and whether an HPC endpoint is configured.

**Returns:** `mode`, `endpoint_id`, `endpoint_status`, `description`

---

### `set_execution_mode`

Switch execution mode without editing config files.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `mode` | `str` | One of `"local"`, `"hpc"`, or `"auto"` |

**Returns:** `mode`, `previous_mode`, `endpoint_id`, `message`

---

## HPC Tools

These tools are only registered when an HPC endpoint is configured. They have the same interface as their core counterparts, plus a `use_remote` flag.

### `inspect_mesh_hpc`
### `calculate_area_hpc`
### `inspect_variable_hpc`
### `calculate_zonal_mean_hpc`

Each accepts the same parameters as the core version, plus:

| Name | Type | Description |
|------|------|-------------|
| `use_remote` | `bool` | Set to `True` to execute on HPC via Globus Compute (default: `False`) |

Each HPC call runs a pre-flight health check before submitting to avoid hanging on a down endpoint. Falls back to local execution if the endpoint is unreachable.

---

## Scientific Agent

### `run_scientific_agent`

Autonomous four-stage pipeline that inspects a mesh, plans operations, executes them (locally or on HPC), and verifies results.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `file_path` | `str` | Path to mesh file, HPC path, or `healpix:<zoom>` |
| `data_path` | `str` (optional) | Path to a data file containing variables |
| `variable_name` | `str` (optional) | Specific variable to analyze. If omitted and data is provided, the first face-centered variable is used |

**Returns:** `file_path`, `execution_venue`, `reasoning_trace`, `mesh_summary`, `area_results`, `variable_results`, `zonal_mean_results`, `validation_summary`, `verification`, `_provenance`

See [Scientific Agent](scientific-agent.md) for details on the four-stage loop and auto-routing logic.
