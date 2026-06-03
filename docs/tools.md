# Tools Reference

All tools available through the MCP server.

Most analysis and control tools return structured dictionaries with a
`_provenance` block for traceability. The plotting tools are different: they
return two MCP content blocks, an inline PNG image plus a JSON text block that
contains the provenance metadata.

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

### `list_datasets`

Scan a local directory for NetCDF, HDF5, and GRIB files and group results by
subdirectory with heuristic grid-vs-data classification.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `directory` | `str` | Local path to scan |
| `recursive` | `bool` | Recurse into subdirectories (default: `False`) |
| `max_files` | `int` | Cap the result set to avoid huge trees (default: `200`) |

**Returns:** `directory`, `total_files`, `truncated`, grouped `files`, `recommendations`, `_provenance`

Use this when you have a directory full of climate files and need a quick map
of likely grid files, data files, and next-step tool calls.

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

Returns the current execution mode and endpoint manager status.

**Returns:** `mode`, `endpoint_name`, `endpoint_configured`, `endpoint_status`, `description`, `status_note`

`endpoint_status` is one of:

| Value | Meaning |
|---|---|
| `"registered"` | Manager is running; Slurm/PBS will allocate workers on demand |
| `"offline"` | Manager is not running — SSH in and start it |
| `"unreachable"` | Cannot contact Globus Compute |
| `"no_endpoint"` | No endpoint configured |

`"registered"` does **not** mean workers are actively running. Use
`endpoint_status(probe=True)` or `validate_hpc_setup()` to confirm a real
worker responds.

---

### `set_execution_mode`

Switch execution mode without editing config files.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `mode` | `str` | One of `"local"`, `"hpc"`, or `"auto"` |

**Returns:** `mode`, `previous_mode`, `endpoint_name`, `endpoint_configured`, `message`

---

### `validate_hpc_setup`

Runs a deeper HPC readiness diagnostic than `get_execution_mode`.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `run_remote_probe` | `bool` | Submit a tiny remote task after status checks (default: `True`) |
| `probe_timeout_seconds` | `int` | Timeout for the remote probe (default: `30`) |
| `sample_path` | `str` (optional) | Exact remote path to probe after the runtime probe succeeds |

**Returns:** `passed`, `mode`, `endpoint_name`, `endpoint_configured`, `endpoint_status`, `checks`, `remote_probe`, `sample_path_probe`, `_provenance`

Use this when an endpoint is `"registered"` but real remote calls hang or
fall back locally. It surfaces problems like missing local Globus auth,
missing `globus_compute_sdk`, scheduler bootstrap failures (`qsub: command not found`),
and worker environment issues.

---

### `probe_path_access`

Proves whether the exact target path is readable. This is the right first check
on a new cluster before trying UXarray-specific tools.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `file_path` | `str` | Local or remote path to probe |
| `use_remote` | `bool` | Set to `True` to execute the probe remotely |
| `inspect_netcdf` | `bool` | Attempt a generic NetCDF open and summarize dims/variables |

**Returns:** Path readability details, file metadata, optional NetCDF summary, `_provenance`

---

## Session And Workflow Tools

### `create_session`

Create a persisted scientific session for datasets, workflows, results, and
operation tracking.

**Parameters:** `name` (optional)

**Returns:** `session_id`, `name`, `created_at`, `_provenance`

---

### `register_dataset`

Register a grid/data pair in a session so later calls can use a
`dataset_handle` instead of repeating file paths.

**Parameters:** `session_id`, `grid_path`, `data_path` (optional), `name` (optional)

**Returns:** `dataset_handle`, `dataset`, `dataset_count`, `_provenance`

---

### `run_workflow`

Run the persisted canonical workflow:
`validate_hpc_setup` → `probe_path_access` → `inspect_*` → `validate_dataset`
→ `calculate_area` → `calculate_zonal_mean` when applicable.

**Parameters:** `file_path` or `dataset_handle`, optional `data_path`, `variable_name`, `session_id`, `sample_path`

**Returns:** Workflow record with `workflow_id`, `status`, per-step states, `events`, `result_handle`, `_provenance`

---

### `resume_workflow`, `get_workflow_status`, `get_result_handle`, `get_operation_status`, `list_operations`, `get_session_state`, `reset_session_state`

Inspect or manage persisted workflow/session state.

These tools let clients:

- resume a previously failed or partial workflow
- inspect per-step status and progress events
- inspect persisted result handles and artifact paths
- list tracked long-running operations
- reset session-scoped results, workflows, and operation history

---

## Advanced Analysis Tools

### `subset_bbox`, `subset_polygon`, `extract_cross_section`

Spatial query tools for cropping or slicing a mesh or face-centered variable.

**Returns:** selection metadata, subset summary, `result_handle`, `_provenance`

---

### `compare_fields`, `calculate_bias`, `calculate_rmse`, `calculate_pattern_correlation`

Same-grid comparison metrics for aligned fields.

`compare_fields` also persists a difference field artifact and returns a
`difference_field_handle` that can be exported later.

---

### `remap_variable`, `regrid_dataset`

Transfer one variable or multiple face-centered variables onto a target grid
using UXarray-supported remapping methods.

**Key parameters:** source grid/data, `target_grid_path`, variable selection,
`method`, `remap_to`

---

### `calculate_temporal_mean`, `calculate_anomaly`

Time-aware summaries for variables with a `time` dimension.

`calculate_temporal_mean` supports a whole-time mean or grouped means via
`groupby`. `calculate_anomaly` currently uses the temporal mean as the v1
baseline.

---

### `calculate_ensemble_mean`, `calculate_ensemble_spread`

Ensemble summaries across explicitly provided `data_paths`. All ensemble
members must share the same dims and shape in v1.

---

### `export_to_netcdf`, `export_to_csv`, `write_result`

Persist a prior `result_handle` or registered session dataset to NetCDF or CSV.

Use these tools when a derived result needs to be shared outside the MCP
response channel or fed into a downstream workflow.

---

## Helper Scripts

For repeatable bring-up and debugging, see:

- `scripts/hpc_doctor.py` — first-pass CLI doctor for local auth, endpoint status, remote no-op execution, and optional real-path probing
- `scripts/agentic_hpc_loop.py`
- `scripts/improv_endpoint.sh`

## Plotting Tools

These tools return:

- an inline PNG image block that MCP clients can render directly
- a JSON text block with `_provenance`, image metadata, and selected inputs

### `plot_mesh`

Render a mesh wireframe from a grid file or a `healpix:<zoom>` mesh spec.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the mesh file or `healpix:<zoom>` |
| `width` | `int` | Image width in pixels (default: `800`) |
| `height` | `int` | Image height in pixels (default: `400`) |

**JSON metadata returns:** `image_size_bytes`, `grid_info`, `_provenance`

---

### `plot_variable`

Render a face-centered variable as a filled polygon map.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the grid/mesh file |
| `data_path` | `str` | Path to the data file |
| `variable_name` | `str` (optional) | Variable to plot, or first face-centered variable if omitted |
| `width` | `int` | Image width in pixels (default: `800`) |
| `height` | `int` | Image height in pixels (default: `400`) |
| `cmap` | `str` | Matplotlib colormap name (default: `"viridis"`) |
| `vmin` | `float` (optional) | Lower bound for the color scale |
| `vmax` | `float` (optional) | Upper bound for the color scale |
| `title` | `str` (optional) | Custom plot title |

**JSON metadata returns:** `image_size_bytes`, `variable_name`, `grid_info`, `_provenance`

---

### `plot_zonal_mean`

Compute and render a zonal-mean profile as latitude versus value.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the grid/mesh file |
| `data_path` | `str` | Path to the data file |
| `variable_name` | `str` | Face-centered variable to average and plot |
| `width` | `int` | Image width in pixels (default: `800`) |
| `height` | `int` | Image height in pixels (default: `400`) |
| `lat_spec` | `tuple`, `float`, `list`, or `None` | Latitude specification for zonal bands |
| `conservative` | `bool` | Area-weighted conservative averaging (default: `False`) |
| `line_color` | `str` | Matplotlib color string (default: `"#1f77b4"`) |
| `title` | `str` (optional) | Custom plot title |

**JSON metadata returns:** `image_size_bytes`, `variable_name`, `latitudes`, `zonal_mean_values`, `_provenance`

## Vector Calculus Tools

These tools compute differential operators on face-centered fields using
UXarray's Green-Gauss finite-volume method. All require face-centered variables
and return statistics over the unstructured mesh.

---

### `calculate_gradient`

Compute the spatial gradient (∂/∂x, ∂/∂y) of a scalar field.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the mesh grid file |
| `data_path` | `str` | Path to the data file |
| `variable_name` | `str` | Face-centered scalar variable |

**Returns:** `variable_name`, `components` (list of output variable names), `component_stats` (min/max/mean per component), `n_face`, `interpretation`, `_provenance`

---

### `calculate_curl`

Compute the curl of a 2-D vector field — equivalent to **relative vorticity** for wind:

> ζ = ∂v/∂x − ∂u/∂y

This is the primary diagnostic for identifying cyclones, anticyclones, and jet-stream
structure on unstructured meshes. Positive vorticity = cyclonic (counterclockwise in
Northern Hemisphere). Negative = anticyclonic.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the mesh grid file |
| `data_path` | `str` | Path to the data file |
| `u_variable` | `str` | Zonal (east–west) component, e.g. `"uReconstructZonal"` |
| `v_variable` | `str` | Meridional (north–south) component, e.g. `"uReconstructMeridional"` |

**Returns:** `u_variable`, `v_variable`, `interpretation`, `n_face`, `stats` (min/max/mean/std), `_provenance`

---

### `calculate_divergence`

Compute the horizontal divergence of a 2-D vector field:

> ∇·V = ∂u/∂x + ∂v/∂y

Negative divergence (convergence) drives rising motion and convection. Positive
divergence indicates sinking motion. Used together with `calculate_curl` to
characterise the full kinematic structure of atmospheric flow.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the mesh grid file |
| `data_path` | `str` | Path to the data file |
| `u_variable` | `str` | Zonal (east–west) component |
| `v_variable` | `str` | Meridional (north–south) component |

**Returns:** `u_variable`, `v_variable`, `interpretation`, `n_face`, `stats` (min/max/mean/std), `_provenance`

---

### `calculate_azimuthal_mean`

Compute the azimuthal (radial) mean of a variable around a centre point, producing a
radial profile. Useful for:

- **Tropical cyclone structure** — radial profiles of wind, pressure, SST
- **Polar vortex analysis** — radial decay from the pole
- **Storm-centred composites** — any feature with approximate radial symmetry

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to the mesh grid file |
| `data_path` | `str` | Path to the data file |
| `variable_name` | `str` | Face-centered variable to average |
| `center_lon` | `float` | Longitude of centre point (degrees) |
| `center_lat` | `float` | Latitude of centre point (degrees) |
| `outer_radius` | `float` | Maximum radius in great-circle degrees |
| `radius_step` | `float` | Radial bin width in great-circle degrees |

**Returns:** `variable_name`, `center`, `outer_radius_deg`, `radius_step_deg`, `radii_deg`, `azimuthal_mean_values`, `n_face`, `_provenance`

---

## HPC Diagnostics

### `endpoint_status`

Check the status of one or all configured HPC endpoints.

By default this is a **fast, cached manager check** — it queries the Globus
cloud about the endpoint manager process without submitting any tasks.
Use `probe=True` to also submit a lightweight task that confirms a real
scheduler worker responds (takes 15–90 s).

**Status values:**

| Value | Meaning |
|---|---|
| `"registered"` | Manager is running; Slurm/PBS will allocate workers on demand. Normal idle state. |
| `"active"` | Manager running + a probe task confirmed a real worker responded (`probe=True` only). |
| `"offline"` | Manager not running — SSH in and run `globus-compute-endpoint start <name>`. |
| `"unreachable"` | Cannot contact Globus Compute (auth or network error). |
| `"no_endpoint"` | No endpoint configured for this name. |

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `endpoint` | `str` (optional) | Named endpoint to check; omit for all configured endpoints |
| `force` | `bool` | Bypass cache and re-query the SDK (default: `False`) |
| `probe` | `bool` | Also submit a lightweight task to confirm a worker responds (default: `False`) |
| `probe_timeout_seconds` | `int` | Timeout for worker probe (default: `60`, only used when `probe=True`) |

**Returns:** `endpoints` (list of rows with `name`, `endpoint_name`,
`endpoint_configured`, `status`, `cached`, `cache_age_seconds`, `node`,
`python`, `slurm_job_id`, `error`), `mode`, `default_endpoint`, `_provenance`.
Raw endpoint UUIDs are read from private local config but are not returned in
public tool payloads.

**Examples:**

```
# Fast manager check (always safe to call, results cached 10 s)
endpoint_status()
→ {"endpoints": [{"name": "chrysalis", "status": "registered", ...}], ...}

# Confirm a real worker actually runs (submits a Slurm job)
endpoint_status(endpoint="chrysalis", probe=True)
→ {"endpoints": [{"name": "chrysalis", "status": "active",
                  "node": "chr-0497", "python": "3.13.13", ...}], ...}
```

---

## Remote (HPC) Execution

The core inspection, computation, and plotting tools accept an optional
`use_remote` flag — there are no separate `*_hpc` tool names. When `True`,
the dispatcher offloads the call to a configured Globus Compute endpoint;
when `False` (the default) or when no endpoint is configured, it runs
locally.

| Name | Type | Description |
|------|------|-------------|
| `use_remote` | `bool` | Execute on a configured Globus Compute endpoint (default: `False`) |
| `endpoint` | `str` (optional) | Named endpoint to target when several are configured |

Tools that support `use_remote`: `inspect_mesh`, `inspect_variable`,
`calculate_area`, `calculate_zonal_mean`, `plot_mesh`, `plot_variable`,
`plot_zonal_mean`. Each remote call runs a pre-flight health check before
submitting to avoid hanging on a down endpoint, and falls back to local
execution if the endpoint is unreachable.

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

---

## MCP Prompts

Prompts are user-invokable slash commands. In Claude Code or Claude Desktop
they appear as `/first_look`, `/vorticity_analysis`, and `/hpc_diagnose`. The
client injects the prompt text into the conversation and the AI calls the
appropriate tools automatically — no need to know tool names or parameter order.

### `/first_look path`

Runs the full `get_capabilities` → `analyze_dataset` pipeline on a mesh or
dataset file. Returns topology summary, data quality report, zonal mean
profile, and mesh + variable plots.

**Argument:** path to a local file or `healpix:<zoom>`.

---

### `/vorticity_analysis grid_path data_path u_var v_var`

Runs `calculate_curl` and `calculate_divergence` on the provided wind
components and asks the AI to interpret the atmospheric dynamics — where is
vorticity extreme (cyclones/anticyclones)? Where does convergence signal
rising motion?

**Arguments:** grid file path, data file path, zonal wind variable name,
meridional wind variable name.

---

### `/hpc_diagnose [endpoint]`

Runs `endpoint_status` (fast cached check) followed by `validate_hpc_setup`
(deep SDK + remote probe), then guides the user through fixing any failures —
re-authentication, restarting the endpoint manager, fixing the worker
environment.

**Argument:** named endpoint (`improv`, `ucar`), or omit to check all.
