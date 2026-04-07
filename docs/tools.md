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

This is a manager-level status check only. An endpoint can report `online`
while real remote tasks still fail because of scheduler, environment, or child
endpoint issues.

---

### `set_execution_mode`

Switch execution mode without editing config files.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `mode` | `str` | One of `"local"`, `"hpc"`, or `"auto"` |

**Returns:** `mode`, `previous_mode`, `endpoint_id`, `message`

---

## Visualization Tools

These tools render mesh visualizations and return a base64-encoded PNG image that MCP clients display inline, alongside a JSON provenance block.

### `plot_mesh`

Render a mesh wireframe — topology only, no data.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `grid_path` | `str` | — | Path to mesh file, or `healpix:<zoom>` |
| `width` | `int` | `800` | Image width in pixels |
| `height` | `int` | `400` | Image height in pixels |

**Returns:** `ImageContent` (PNG) + `TextContent` with `image_size_bytes`, `grid_info`, `_provenance`

**Example prompts:**

```
Plot the mesh in /data/grid.nc
Plot healpix:4 at 1200x600
```

---

### `plot_variable`

Render a face-centered variable as a filled polygon (choropleth) map.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `grid_path` | `str` | — | Path to the mesh grid file |
| `data_path` | `str` | — | Path to the data file |
| `variable_name` | `str` | auto | Variable to plot. If omitted, the first face-centered variable is used |
| `width` | `int` | `800` | Image width in pixels |
| `height` | `int` | `400` | Image height in pixels |
| `cmap` | `str` | `"viridis"` | Matplotlib colormap name (see below) |
| `vmin` | `float` | data min | Minimum value for the colormap scale |
| `vmax` | `float` | data max | Maximum value for the colormap scale |
| `title` | `str` | variable name | Custom plot title |

**Returns:** `ImageContent` (PNG) + `TextContent` with `image_size_bytes`, `variable_name`, `grid_info`, `_provenance`

**Colormap guide:**

| Use case | Recommended colormaps |
|----------|-----------------------|
| Sequential (low → high) | `viridis`, `plasma`, `inferno`, `magma`, `cividis` |
| Diverging (anomalies, +/−) | `RdBu_r`, `coolwarm`, `bwr`, `seismic`, `PiYG` |
| Temperature | `RdYlBu_r`, `hot`, `afmhot` |
| Precipitation | `YlGnBu`, `Blues`, `GnBu` |
| Reversed | Append `_r` to any name: `viridis_r`, `plasma_r` |

**Example prompts:**

```
Plot the temperature variable in data.nc using the RdBu_r colormap
Plot precip with vmin=0, vmax=50 so the scale is fixed
Plot temperature anomaly with cmap=coolwarm, vmin=-5, vmax=5, title="Jan 2025 Anomaly"
```

---

### `plot_zonal_mean`

Render a zonal mean profile as a latitude vs. value line chart.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `grid_path` | `str` | — | Path to the mesh grid file |
| `data_path` | `str` | — | Path to the data file |
| `variable_name` | `str` | — | Name of the face-centered variable |
| `width` | `int` | `800` | Image width in pixels |
| `height` | `int` | `400` | Image height in pixels |
| `lat_spec` | `tuple/float/list` | default bands | Latitude band specification (see `calculate_zonal_mean`) |
| `conservative` | `bool` | `False` | Use area-weighted averaging |
| `line_color` | `str` | `"#1f77b4"` | Matplotlib color for the profile line (see below) |
| `title` | `str` | auto | Custom plot title |

**Color specification:**

Any valid matplotlib color works: named colors (`"red"`, `"steelblue"`, `"darkorange"`), hex strings (`"#e74c3c"`), or RGB tuples as strings.

**Example prompts:**

```
Plot the zonal mean of temperature
Plot zonal mean of precipitation in red with title "Annual Mean Precipitation"
Plot temperature zonal mean with 2-degree bands and area-weighted averaging
```

---

### `validate_hpc_setup`

Runs a deeper HPC readiness diagnostic than `get_execution_mode`.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `run_remote_probe` | `bool` | Submit a tiny remote task after status checks (default: `True`) |
| `probe_timeout_seconds` | `int` | Timeout for the remote probe (default: `30`) |
| `sample_path` | `str` (optional) | Exact remote path to probe after the runtime probe succeeds |

**Returns:** `passed`, `mode`, `endpoint_id`, `endpoint_status`, `checks`, `remote_probe`, `sample_path_probe`, `_provenance`

---

### `probe_path_access`

Proves whether the exact target path is readable on the remote worker.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `file_path` | `str` | Local or remote path to probe |
| `use_remote` | `bool` | Set to `True` to execute the probe remotely |
| `inspect_netcdf` | `bool` | Attempt a generic NetCDF open and summarize dims/variables |

**Returns:** Path readability details, file metadata, optional NetCDF summary, `_provenance`

---

## Helper Scripts

For repeatable bring-up and debugging, see:

- `scripts/hpc_doctor.py` — first-pass CLI doctor for local auth, endpoint status, remote no-op execution, and optional real-path probing
- `scripts/agentic_hpc_loop.py`
- `scripts/improv_endpoint.sh`

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
