# Tools Reference

Everything on this page runs **locally on your machine by default** — no HPC
account, Globus identity, or endpoint needed. `use_remote` and `endpoint`
parameters exist on most tools, but you only need them once you've configured
an HPC endpoint (see [Remote Execution](#remote-execution) at the bottom of
this page, or skip straight to [remote-hpc.md](remote-hpc.md)). Ignore them
until then.

The MCP server exposes a small set of front-door tools. Low-level UXarray
operations still exist as Python functions in `uxarray_mcp.tools`, but MCP
clients should use the intent-shaped tools below.

Most tools return structured dictionaries with a `_provenance` block. Plotting
returns MCP content blocks: an inline PNG plus JSON metadata.

The visible tool set depends on the profile (`core` by default, or
`deferred-full`), and the server can expose these tools over MCP stdio/SSE/HTTP
or OpenAPI/REST. See {doc}`serving` for profiles, transports, and tool
discovery.

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
`dataset_handle`, and `include_plots`.

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
| `zonal_anomaly` | Per-face deviation from its latitude-band zonal mean |
| `gradient`, `curl`, `divergence`, `azimuthal_mean` | Vector/radial diagnostics |
| `subset_bbox`, `subset_polygon`, `cross_section` | Spatial selections |
| `compare_fields`, `bias`, `rmse`, `pattern_correlation` | Same-grid comparisons |
| `remap_variable`, `regrid_dataset` | UXarray-backed remapping |
| `remap_to_rectilinear` | Remap a variable onto a regular lon/lat grid |
| `temporal_mean`, `anomaly` | Time-dimension summaries |
| `ensemble_mean`, `ensemble_spread` | Multi-file ensemble summaries |
| `export` | Write a persisted result or dataset to NetCDF/CSV |

Common parameters include `grid_path`, `data_path`, `variable_name`,
`target_grid_path`, `data_path_a`, `data_path_b`, `data_paths`, `lon_bounds`,
`lat_bounds`, `method`, `session_id`, and `dataset_handle`. Each operation
validates the parameters it requires and returns a clear error if one is
missing.

`gradient`, `curl`, and `divergence` echo the `scale_by_radius` convention in
their result and provenance. `gradient` and `curl` accept `scale_by_radius`
(default `False`). When `False`, results stay on the unit sphere (the historical
behavior). Set it to `True` to divide by `uxgrid.sphere_radius` for physical
units; the grid must define `sphere_radius`.

`curl` and `divergence` also emit **vector-component warnings**: if the two
inputs are the same field, or neither carries a velocity/flux-like `units`
attribute, a warning is added to `_provenance.warnings`. The computation still
runs (the math is valid), but the result is flagged as possibly non-physical.

`zonal_anomaly` and `remap_to_rectilinear` are backed by
`UxDataArray.zonal_anomaly` and `UxDataArray.remap.to_rectilinear`, available in
the pinned UXarray (`>=2026.6.0`).

Examples:

```python
run_analysis(operation="inspect_mesh", grid_path="healpix:4")
run_analysis(operation="calculate_area", grid_path="/path/grid.nc")
run_analysis(
    operation="zonal_anomaly",
    grid_path="/path/grid.nc",
    data_path="/path/data.nc",
    variable_name="temperature",
)
run_analysis(
    operation="remap_to_rectilinear",
    grid_path="/path/grid.nc",
    data_path="/path/data.nc",
    variable_name="temperature",
    target_lon=[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330],
    target_lat=[-60, -30, 0, 30, 60],
)
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
`height`, `cmap`, `vmin`, `vmax`, `title`, `session_id`, and `dataset_handle`.

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

Everything below only matters once you've configured an HPC endpoint (see
[remote-hpc.md](remote-hpc.md)). Skip this section entirely for local-only use.

`analyze_dataset`, `run_analysis`, `plot_dataset`, and `probe_path_access`
accept `use_remote=True` and `endpoint="name"` where remote execution applies.
Remote calls submit self-contained functions to a configured Globus Compute
endpoint and preserve provenance. If an endpoint is missing or unhealthy, the
dispatcher either falls back locally or reports a structured readiness error.

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

`remap_variable`, `regrid_dataset`, and `remap_to_rectilinear` (all
`run_analysis` operations) accept `use_remote=True` and `endpoint="name"` too.
When run remotely the remap executes on the HPC worker and compact summary
statistics are returned (for `remap_to_rectilinear`, the small rectilinear
array is returned and persisted locally); large source meshes never cross the
network.

## MCP Prompts

Prompts are user-invokable slash commands that return a guided, multi-step
analysis plan (instruction text, not results) — the assistant then runs the
chained operations and interprets them. In Claude Code or Claude Desktop they
appear as `/first_look`, `/vorticity_analysis`, etc.

General:

- `/first_look path` calls `get_capabilities` and `analyze_dataset`.
- `/hpc_diagnose [endpoint]` calls `diagnose_endpoint(action="status")` and
  `diagnose_endpoint(action="validate")`.

Science workflows (each composes existing `run_analysis` operations around a
scientific question):

- `/vorticity_analysis grid_path data_path u_var v_var` — rotation and
  divergence of a wind field (`curl` + `divergence`).
- `/cyclone_structure grid_path data_path variable_name center_lon center_lat [u_var v_var outer_radius]`
  — radial structure of a storm/vortex (`azimuthal_mean` + `subset_bbox`,
  optionally `curl`).
- `/eddy_activity grid_path data_path variable_name` — departures from the
  latitudinal background state (`calculate_zonal_mean` + `zonal_anomaly` +
  `gradient`).
- `/model_evaluation grid_path data_path_a data_path_b variable_name` — verify a
  field against a reference (`bias` + `rmse` + `pattern_correlation`).
- `/climatology_anomaly data_path variable_name [grid_path]` — time-mean state
  and departures (`temporal_mean` + `anomaly`, optionally `calculate_zonal_mean`).
