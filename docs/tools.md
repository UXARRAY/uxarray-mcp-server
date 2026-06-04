# Tools Reference

The MCP server exposes a small set of front-door tools. Low-level UXarray
operations still exist as Python functions in `uxarray_mcp.tools`, but MCP
clients should use the intent-shaped tools below.

Most tools return structured dictionaries with a `_provenance` block. Plotting
returns MCP content blocks: an inline PNG plus JSON metadata.

## Front-Door Tools

### `get_capabilities`

Discover mesh topology, variables, applicable `run_analysis` operations, native
UXarray methods, and recommended next steps.

Parameters:

| Name | Type | Description |
|------|------|-------------|
| `grid_path` | `str` | Path to grid/mesh file, or `healpix:<zoom>` |
| `data_path` | `str` optional | Path to a data file |

### `analyze_dataset`

Run the deterministic first-look pipeline in one call: inspect mesh, validate
data when provided, inspect variables, calculate face areas, calculate a zonal
mean when possible, and produce mesh/variable plots when requested.

Parameters include `grid_path`, `data_path`, `variable_name`, `session_id`,
`dataset_handle`, `use_remote`, `endpoint`, and `include_plots`.

### `run_analysis`

Run one named operation without exposing dozens of separate MCP tools.

Supported operations:

| Operation | Purpose |
|---|---|
| `inspect_mesh` | Mesh topology and format |
| `inspect_variable` | Variable metadata and statistics |
| `validate_dataset` | NaN/Inf/fill-value checks |
| `calculate_area` | Face area statistics |
| `calculate_zonal_mean` | Latitude-band mean for a face-centered variable |
| `gradient`, `curl`, `divergence`, `azimuthal_mean` | Vector/radial diagnostics |
| `subset_bbox`, `subset_polygon`, `cross_section` | Spatial selections |
| `compare_fields`, `bias`, `rmse`, `pattern_correlation` | Same-grid comparisons |
| `remap_variable`, `regrid_dataset` | UXarray-backed remapping |
| `temporal_mean`, `anomaly` | Time-dimension summaries |
| `ensemble_mean`, `ensemble_spread` | Multi-file ensemble summaries |
| `export` | Write a persisted result or dataset to NetCDF/CSV |

Common parameters include `grid_path`, `data_path`, `variable_name`,
`target_grid_path`, `data_path_a`, `data_path_b`, `data_paths`, `lon_bounds`,
`lat_bounds`, `method`, `session_id`, `dataset_handle`, `use_remote`, and
`endpoint`. Each operation validates the parameters it requires and returns a
clear error if one is missing.

Examples:

```python
run_analysis(operation="inspect_mesh", grid_path="healpix:4")
run_analysis(operation="calculate_area", grid_path="/path/grid.nc")
run_analysis(
    operation="calculate_zonal_mean",
    grid_path="/path/grid.nc",
    data_path="/path/data.nc",
    variable_name="temperature",
)
```

### `plot_dataset`

Render plots through one plotting front door.

Supported `plot_type` values:

- `mesh`
- `mesh_geo`
- `variable`
- `zonal_mean`

Common parameters include `grid_path`, `data_path`, `variable_name`, `width`,
`height`, `cmap`, `vmin`, `vmax`, `title`, `use_remote`, `endpoint`,
`session_id`, and `dataset_handle`.

### `diagnose_endpoint`

Run endpoint diagnostics with concrete failure guidance.

Actions:

| Action | Purpose |
|---|---|
| `status` | Endpoint manager plus optional worker probe |
| `validate` | SDK auth, endpoint reachability, worker probe, optional sample path |
| `probe_path` | Check whether one exact path is readable locally or remotely |

### `probe_path_access`

Direct convenience path probe for cluster bring-up. This remains separately
registered because it is the safest first command when a new filesystem path is
suspect.

### `run_workflow` and `resume_workflow`

Run or resume the canonical persisted workflow: endpoint/path checks, mesh
inspection, variable inspection, validation, area, and zonal mean when valid.

### `manage_session`

Create sessions, register datasets, inspect session state, reset state, and
list operations through one session front door.

Actions: `create`, `register_dataset`, `get`, `reset`, `list_operations`,
`dataset`.

### `get_status`

Read workflow or operation status.

### `get_result`

Inspect a persisted result handle and artifact metadata.

## Remote Execution

`analyze_dataset`, `run_analysis`, `plot_dataset`, and `probe_path_access`
accept `use_remote=True` and `endpoint="name"` where remote execution applies.
Remote calls submit self-contained functions to a configured Globus Compute
endpoint and preserve provenance. If an endpoint is missing or unhealthy, the
dispatcher either falls back locally or reports a structured readiness error.

## MCP Prompts

Prompts are user-invokable slash commands. In Claude Code or Claude Desktop
they appear as `/first_look`, `/vorticity_analysis`, and `/hpc_diagnose`.

- `/first_look path` calls `get_capabilities` and `analyze_dataset`.
- `/vorticity_analysis grid_path data_path u_var v_var` calls
  `run_analysis(operation="curl")` and
  `run_analysis(operation="divergence")`.
- `/hpc_diagnose [endpoint]` calls
  `diagnose_endpoint(action="status")` and
  `diagnose_endpoint(action="validate")`.
