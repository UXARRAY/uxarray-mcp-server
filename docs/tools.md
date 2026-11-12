# Tools

Thirteen tools. Everything runs on your machine unless a path belongs to a
configured HPC endpoint or you pass `use_remote=True` (see [hpc.md](hpc.md)).
Required parameters are marked `*`.

## What every result carries

```json
{
  "status": "complete | warning | unverified",
  "physically_interpretable": true,
  "warning_codes": ["MESH_NOT_GLOBAL"],
  "warnings": [],
  "preconditions": {"status": "satisfied", "checks": [...], "failed_checks": []},
  "_provenance": {"tool": "compute", "inputs": {...}, "venue": "local | hpc:<name>",
                  "timestamp_utc": "...", "uxarray_version": "...", "server_version": "..."}
}
```

**Refusals.** When a declared precondition fails — an area with no sphere
radius, a vorticity without velocity units, a subset that selects nothing, a
remap whose target lies outside the source — the tool does not return a
number. It returns `outcome: "input_required"` with `refusal.failed_checks`
and a `repairs` list naming the argument to change. To run anyway pass
`acknowledge="i-understand-this-result-may-not-be-physical"`; the result then
comes back `status: "unverified"`, `physically_interpretable: false`.

**Remote calls that outlive the timeout** return
`{"status": "running", "operation_id": "op_…"}`. Collect with
[`get_operation`](#get_operation). Remote failures return `status: "error"`
with an `error_code` (`ENDPOINT_OFFLINE`, `NO_WORKER`, `WORKER_LOST`,
`FILE_NOT_FOUND_ON_WORKER`, `WORKER_MISSING_PACKAGE`, `REMOTE_FAILED`).

Paths may be local files, `healpix:<zoom>` (virtual HEALPix mesh, zoom ≤ 13),
or remote URIs (`s3://`, `gs://`, `https://`, kerchunk references).
Longitudes are −180..180.

---

### `list_datasets`

List mesh and data files in a directory with header-only facts. Each file
reports `format` (ugrid, mpas, scrip, exodus, esmf, icon), `role` (grid, data,
grid+data), `n_face`, `n_time`, `size_class` and face-centered variable
names, read from the header without opening the mesh (3 ms on a 25 GB SCRIP
file).

`directory`*, `recursive` (false), `max_files` (200), `use_remote`, `endpoint`

### `inspect_dataset`

Topology (`n_face`, `n_node`, `n_edge`, `format`), `mesh_coverage`
(`sphere_fraction`, `closed`, `euler_characteristic`), `size_class`, a
`plot_hint` saying whether a plot will be drawn polygon by polygon or
rasterized, and — with `data_path` — the variables (dims, units, stats) and
a NaN/Inf/fill `validation` block. This is the one call to make first.
`first_look=True` also computes face areas (Earth radius), the zonal mean of
the first face-centered variable (10° bands) and writes mesh and field plots
(`plots.<kind>.image_path`) — a complete first pass in one call.

`grid_path`*, `data_path`, `variable_name`, `validate` (true), `first_look`
(false), `use_remote`, `endpoint`, `session_id`, `dataset_handle`

### `compute`

One statistic on a mesh or face-centered variable.

| `statistic` | needs | notes |
|---|---|---|
| `area` | `grid_path`, `sphere_radius` unless the grid declares one | 6371000 m for Earth; steradians are refused |
| `zonal_mean` | `grid_path`, `data_path`, `variable_name` | `lat_spec` one latitude or list; `lat_step` with `[start, stop]` for a regular range; `conservative` for band means |
| `zonal_anomaly` | same | per-face deviation from its band mean |
| `azimuthal_mean` | same + `center_lon`, `center_lat`, `outer_radius`, `radius_step` (degrees) | radial profile about a point |
| `temporal_mean` | `data_path`, `variable_name` | `time_min`/`time_max` ISO labels, `groupby`; reports `temporal_coverage` |
| `anomaly` | `data_path`, `variable_name` | `baseline` (`temporal_mean`) |
| `ensemble_mean`, `ensemble_spread` | `variable_name`, `data_paths` | member units/grid consistency reported |

Bins that miss the mesh are refused (`*_COVERAGE_ZERO`); partially filled
bins warn (`PROFILE_COVERAGE_PARTIAL`). Results that produce a field persist
it and return `result_handle`.

### `vector_calc`

`operation`: `gradient` (`variable_name`) | `curl` | `divergence`
(`u_variable`, `v_variable`). Physical units need a sphere radius (grid
attribute or `sphere_radius=6371000`); otherwise refused. Curl and
divergence also require velocity-like units and identifiable components.

`operation`*, `grid_path`*, `data_path`*, `scale_by_radius` (true),
`time_index`, `level_index`, `use_remote`, `endpoint`, `acknowledge`

### `compare`

Area-weighted `bias`, `rmse`, `pattern_correlation` and difference
statistics for one variable across two files on the same mesh (`metric=`
narrows). Declared unit disagreement (K vs degC) is refused; undeclared
units warn with `UNITS_UNDECLARED`. Local only.

`variable_name`*, `data_path_a`*, `data_path_b`*, `grid_path`, `metric`,
`acknowledge`

### `remap`

Mesh-to-mesh (`target_grid_path`) or to a lon/lat grid (`target_lon`,
`target_lat` as 1-D lists). `method`: `nearest_neighbor`,
`inverse_distance_weighted`, `bilinear` on UXarray's engine;
`conservative`, `nnn`, `dnn`, `average` on YAC (must be installed where the
remap runs; only `conservative` preserves the integral and every other
method carries `REMAP_METHOD_NOT_CONSERVATIVE`). `whole_dataset=True`
regrids every variable. `source_coverage` reports how much of the target the
source reaches; zero is refused. Returns `result_handle`.
`destination="face"|"node"|"edge"` with `statistic` (mean|max|min|sum)
instead carries a field between elements of the same mesh — the way to make
node-centred output usable by `vector_calc` (UXarray does not yet support
face→node).

### `subset`

`shape`: `bbox` (`lon_bounds`, `lat_bounds`; keeps faces whose whole
footprint fits — stricter than centre-in-box) | `polygon`
(`polygon_lon_lat`; centres inside) | `cross_section` (`latitude` or
`longitude`) | `circle` (`center_lon`, `center_lat`, `radius` degrees) |
`nearest` (`center_lon`, `center_lat`, `k`). An empty selection is refused
with the mesh's extent so the −180/0..360 mix-up is visible. Returns
`result_handle`; plot or export it.

### `plot`

`kind`: `mesh` (wireframe) | `field` (`variable_name` choropleth) |
`profile` (zonal-mean line) | `temporal_mean` (mean of `variable_name` over
every time step in `data_paths`, many files; `scale_factor`, `units_label`;
reports `time_min`/`time_max`, `value_stats`, `temporal_coverage`). Returns an image block (inline under 256 kB,
otherwise a `resource_link` to the stored PNG) and a JSON text block with
`render_mode`, `n_faces_total`, `n_faces_rendered`, `image_path` and the
usual envelope. Meshes above 200 000 faces are rasterized to the requested
`width`×`height` instead of drawn polygon by polygon; `force_raster=True`
forces it. `lon_bounds`/`lat_bounds` crop mesh, field and temporal_mean plots
(`n_faces_in_region` says what survived); `coastlines=True` draws Natural
Earth features behind a mesh (local only); `result_handle` plots a stored
subset. `title`, `cmap`, `vmin`, `vmax`, `time_index`, `level_index`,
`lat_spec`, `conservative` as expected.

### `export`

Write a stored result (`result_handle`) or a file's variable to
`format` `netcdf` or `csv` at `output_path`. `export_fidelity` names
attributes, fill values or coordinates the format could not carry.

### `session`

`action`: `create` → `session_id` | `register` (`grid_path`, optional
`data_path`) → `dataset_handle` | `get` | `result` (`result_handle`) |
`reset`. Register once, then pass `session_id` + `dataset_handle` to other
tools instead of repeating paths.

### `endpoint`

`action`: `status` (manager state of every configured endpoint plus a
worker probe of the named/default one: node, Python and uxarray versions,
round-trip seconds) | `validate` (adds a header read of `path` on the
worker; `passed`) | `probe_path` | `check_yac`. A scheduler-backed endpoint
can take a minute to answer cold; `probe_timeout_seconds` (90) bounds it.

### `get_operation`

`operation_id`*, `wait_seconds` (0). Collects a remote result whose call
returned `status: "running"`, or reads the stored operation record.

### `guide`

`topic`*: `first_look` | `vorticity` | `cyclone_structure` | `eddy_activity`
| `model_evaluation` | `climatology_anomaly` | `hpc_diagnose`, plus the
paths/variables that topic needs. Returns a numbered plan naming the exact
tool calls to make and how to read their results — instructions, not data.
