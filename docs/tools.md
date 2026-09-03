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
their result and provenance, and all three accept `scale_by_radius`
(default `True`, matching UXarray). When `True`, results are divided by
`uxgrid.sphere_radius` for physical units; the grid must define
`sphere_radius`. Pass `False` explicitly to keep unit-sphere results.

`gradient`, `curl` and `divergence` declare **refusable preconditions** (#86)
rather than warning and computing anyway. Each operation states, as data, what
must hold for its answer to be physical. For the two-component operators the
components must be distinct fields, both must carry velocity-like `units`, and
their direction identity must be resolvable from `standard_name` or
`long_name`. All three additionally require radius scaling, without which the
answer is a per-radian quantity rather than a vorticity in s^-1 or a gradient
per metre. Every result carries a `preconditions` block with `status`
(`satisfied`, `overridden`, `failed`, or `not_evaluated`), the individual
`checks`, and `failed_checks`.

The radius-scaling check reads whether scaling was **applied**, not whether it
was requested. UXarray honours `scale_by_radius=True` as far as it can on a
grid that declares no `sphere_radius`: it warns that the result is left on the
unit sphere and returns it. Asking only about the request therefore let the
gate pass on any such grid, so the repair names the missing attribute rather
than telling a caller to set a flag they already set.

When a check fails, the call **does not run** and no number is returned.
The result instead carries `outcome: "input_required"`, shaped after the
MCP `2026-07-28` multi-round-trip request (MRTR) flow: a `refusal` block with
the failed checks and the specific repair for each, an `input_requests` entry
holding an `elicitation/create` form, and an opaque `request_state` derived
from the operation and the failed check ids. `outcome` is the server's own
field and is deliberately not called `result_type`: the SDK stamps a
protocol-level `resultType` on every result object, always `"complete"`
because the call did return, so a refusal would otherwise carry two
same-named fields with contradicting values. A caller who wants the number
anyway passes `acknowledge` with the token named in the refusal; the result
then comes back with `preconditions.status: "overridden"`,
`scientific_status.status: "unverified"`, `physically_interpretable: false`,
and a `PRECONDITION_FAILED_<ID>` code per failed check. A wrong or guessed
token is a failed override, not a silent pass.

`compare_fields`, `bias`, `rmse` and `pattern_correlation` declare
`units_comparable` on the same machinery. All four are built from `a - b`,
which measures something only when both fields are on the same scale, so a
declared disagreement (K against degC) refuses rather than reporting the
273.15 offset as model error. Unit strings are folded through a fixed synonym
table — `K`/`kelvin`, `m/s`/`m s-1`, `degC`/`degrees_Celsius` — and nothing
more: the server does not parse unit algebra, so `mm day-1` against
`kg m-2 s-1` refuses even though the two are convertible. The repair says so.
A field that declares no `units` at all is a gap in the metadata rather than a
contradiction, so it warns with `UNITS_UNDECLARED` and the call proceeds.

Those four operations also report an `area_weighting` block. Their metrics are
weighted by `face_areas`, because a plain mean over faces answers "the average
over cells" and not "the average over the sphere" — on a variable-resolution
mesh the two differ in magnitude and can differ in sign. The block names the
face dimension and the max/min area ratio, so a caller can see whether
weighting mattered; HEALPix is equal-area and reports a ratio of 1.0. When
weighting is impossible — no `grid_path`, a field that is not face-centered,
or `face_areas` unavailable — the result says so with
`AREA_WEIGHTING_UNAVAILABLE` instead of presenting a cell-count mean as a
spatial one.

`validate_dataset` is deliberately exempt from refusal: reporting that a
dataset is invalid *is* its answer, so refusing to report it would be
circular. It reports `scientific_status.status: "invalid"` instead.

`get_capabilities` distinguishes **structural applicability** from **semantic
suitability** for vector operations. Two face-centered arrays make curl and
divergence computable, but physical interpretation remains `unverified` unless
metadata supplies vector-like units or standard names.

`zonal_anomaly` and `remap_to_rectilinear` are backed by
`UxDataArray.zonal_anomaly` and `UxDataArray.remap.to_rectilinear`, available in
the pinned UXarray (`>=2026.6.0`).

All three remap operations — `remap_to_rectilinear`, `remap_variable`, and
`regrid_dataset` — return a **`source_coverage`** block reporting
`points_in_source` out of `n_target_points`, the resulting
`coverage_fraction`, the source mesh bounding box, whether the test was
`point_in_cell` or a `bounding_box` screen, and whether the remap method
conserves the field integral. Target points outside the source mesh still
receive extrapolated values, so zero or partial coverage raises the stable
codes `REMAP_COVERAGE_ZERO` or `REMAP_COVERAGE_PARTIAL`, and a
non-conservative method raises `REMAP_METHOD_NOT_CONSERVATIVE`; all three
appear in `scientific_status.warning_codes` and `_provenance.warnings`.

For `remap_variable` and `regrid_dataset` the target points are the target
mesh's own coordinates — face centres or nodes, whichever `remap_to` writes
to — and they are paired rather than multiplied out, since an unstructured
mesh supplies one longitude and one latitude per point. A target grid that
does not expose those coordinates leaves coverage unknown, in which case
`source_coverage` is absent rather than reported as full.

Zero coverage is the one coverage case that **refuses** rather than warns.
When no target point falls inside the source mesh, every returned value is an
extrapolation, so the operation returns the same
`outcome: "input_required"` payload described above with the source bounding
box in the detail text. The repair names the argument that caller controls:
`target_lon`/`target_lat` for `remap_to_rectilinear`, and `target_grid_path`
for the two grid-to-grid operations. Partial coverage and a non-conservative
method stay warnings, because a partially covered result still contains real
values.

`calculate_zonal_mean` and `azimuthal_mean` reduce a field onto bins the caller
chooses — latitude bands, or rings of great-circle distance from a centre — and
nothing forces those bins to intersect the mesh. Both return a
**`profile_coverage`** block giving `n_bins`, `n_bins_filled`,
`source_has_missing` and `cause`. A profile with no filled bin at all
**refuses**: every entry is NaN, so nothing in the returned array was measured,
which is the same state `remap_coverage_nonzero` refuses over. The repair names
the argument that caller controls — `lat_spec` for the zonal mean,
`center_lon`/`center_lat` and `outer_radius` for the radial one. A partly
filled profile warns with `PROFILE_COVERAGE_PARTIAL` and completes, because a
regional mesh averaged over global bands legitimately fills only the bands it
spans.

The count comes from the returned profile, not from re-deriving which face
lands in which bin: that would duplicate UXarray's own binning and could
disagree with it. An empty bin is NaN, but so is a bin whose faces all held
missing data, so the source field is checked as well. `cause` is
`bins_miss_mesh` only when the field is known to be complete, and `ambiguous`
when it carries missing values or was not available to check — in which case
the repair says so rather than asserting one explanation.

`ensemble_mean` and `ensemble_spread` combine several files cell-by-cell, and
nothing in the shapes says the files measure the same thing on the same mesh.
Both report a **`member_evidence`** block naming the per-member `units`, the
verdicts `units_consistent` and `grids_consistent`, and whether the mesh was
compared on coordinates or on dimensions alone. Averaging a member in K with
one in degC is the same arithmetic as differencing two fields on different
scales, so a declared disagreement fails `ensemble_units_consistent` and
refuses; undeclared units warn with `ENSEMBLE_UNITS_UNDECLARED` for the same
reason `UNITS_UNDECLARED` warns above.

The mesh check is weaker on purpose. Members are opened as plain datasets — the
operation is handed no `grid_path` — so identity rests on whatever coordinates
the member files carry, hashed together with the dimensions. When they carry
none there is nothing left to compare beyond dimension lengths, which two
unrelated meshes with the same face count would satisfy, so the result warns
`ENSEMBLE_GRID_UNVERIFIED` rather than reporting the meshes as agreeing.
Coordinates that are present and disagree fail `ensemble_grids_consistent` and
refuse, because combining values cell-by-cell across different meshes averages
unrelated locations.

## Postconditions and `verdict_policy`

Analysis results carry a **`postconditions`** block alongside
`preconditions`. The two are deliberately distinct: a failed precondition
means "we checked and it fails", while `not_evaluated` means "we did not
check". Reporting no verification at all was previously indistinguishable
from reporting a passed one, which let a caller imply more confidence than
the computation supported.

Today `calculate_area` is the operation with a closed-form reference: the
face areas of a closed mesh must sum to `4*pi*R^2`, or `4*pi` on a unit
sphere. The check abstains — status `not_evaluated` — whenever it cannot be
trusted: an open or regional mesh, a missing total, or an unreadable grid.

`run_analysis` accepts `verdict_policy` to control how much of the check
comes back:

| Value | Behavior |
|---|---|
| `full` (default) | reference, tolerance, residual, and a `passed` verdict |
| `reference_only` | reference and tolerance only; `caller_must_supply` lists `residual` and `passed` |
| `off` | nothing is evaluated |

The default also reads from the `UXARRAY_MCP_VERDICT_POLICY` environment
variable, and an unrecognized value is rejected before the computation runs
rather than after it has already cost something.

## Response contracts (`contract/`)

Two tools under the `contract/` namespace let a caller ask what shape a
result is expected to take, instead of inferring it from an example:

- `describe_response_contract(name)` returns the required fields, their
  types, and any format constraint for a named contract
  (`calculate_area`, `inspect_mesh`, `calculate_zonal_mean`,
  `validate_dataset`, `verification`).
- `validate_response(name, response)` checks a candidate payload against
  that contract and returns the specific violations.

The contract is deliberately **not** attached to every tool result. Repeating
a schema on every response is how payload budgets get spent on text no caller
reads.

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

**Not every `run_analysis` operation supports `use_remote` yet.** Passing
`use_remote=True` for one of the operations below raises `ValueError`
immediately rather than silently running locally — this is deliberate: a
facility-only path (one that doesn't exist on your machine) combined with a
silent local fallback would otherwise produce a confusing local
`FileNotFoundError` with no indication that `use_remote` was ever honored.

| Supports `use_remote` | Does not (yet) |
|---|---|
| `inspect_mesh`, `inspect_variable`, `calculate_area`, `calculate_zonal_mean`, `zonal_anomaly`, `gradient`, `curl`, `divergence`, `azimuthal_mean`, `remap_variable`, `regrid_dataset`, `remap_to_rectilinear` | `validate_dataset`, `subset_bbox`, `subset_polygon`, `cross_section`, `compare_fields`, `bias`, `rmse`, `pattern_correlation`, `temporal_mean`, `anomaly`, `ensemble_mean`, `ensemble_spread`, `export` |

For an operation in the right-hand column, stage the file locally first (or
run it on a machine that can already read the facility path directly).
`plot_dataset(plot_type=...)` has the same split: `mesh`, `variable`, and
`zonal_mean` support `use_remote`; `mesh_geo` does not yet.

### `diagnose_endpoint`

Run endpoint diagnostics with concrete failure guidance.

Actions:

| Action | Purpose |
|---|---|
| `status` | Endpoint manager plus optional worker probe |
| `validate` | SDK auth, endpoint reachability, worker probe, optional sample path |
| `probe_path` | Check whether one exact path is readable locally or remotely |
| `check_yac` | Confirm native YAC imports and completes a real remap on the worker |

`check_yac` matters on a freshly built endpoint: YAC is compiled separately
from the Python environment, so it can be missing or mislinked on a worker that
is otherwise healthy. The check runs inside a worker-side subprocess, because a
bad YAC/MPI link can abort the importing process outright — that would
otherwise surface as an opaque `WorkerLost` rather than a diagnosable result.

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
