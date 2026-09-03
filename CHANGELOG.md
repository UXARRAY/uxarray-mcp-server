# Changelog

All notable changes are recorded here. Dates are ISO 8601 (UTC). The project
uses Semantic Versioning for public releases.

## Unreleased

### Fixed
- The radius-scaling precondition on `curl` and `divergence` read whether
  scaling was *requested*, not whether it was *applied*. UXarray honours
  `scale_by_radius=True` as far as it can on a grid that declares no
  `sphere_radius`: it warns that the result is left on the unit sphere and
  returns it anyway. The request alone therefore satisfied the gate, so a
  vorticity per radian came back labelled s^-1 — carrying
  `SPHERE_RADIUS_UNAVAILABLE` and `physically_interpretable: false` beside the
  number, which is the warning-that-changes-nothing state #86 exists to end.
  The check now reads the applied flag, and its repair names the missing
  attribute instead of telling a caller to set a flag they already set.
- `gradient` was left out of the precondition gate entirely, though it takes
  the same derivative on the same sphere and the domain layer already recorded
  the same `SPHERE_RADIUS_UNAVAILABLE`. It is now gated on radius scaling like
  the other two. The component checks do not apply to it: a gradient is taken
  of one field, so distinctness, velocity units, and eastward/northward
  identity have nothing to read.
- The test suite can no longer report green against stand-ins. `conftest`
  substitutes `MagicMock` for uxarray so the pure-logic tests run on a bare
  checkout, but it did so on any `ImportError` — including one raised from
  *inside* a uxarray that is installed and broken, such as a moved optional
  import or a binary built against the wrong NumPy. A MagicMock returns a
  MagicMock for every attribute and call, so that run passes nearly everything
  it asserts and is indistinguishable from a real one. `importlib.util.
  find_spec` now separates "not installed" from "installed but broken", and
  `tests/test_suite_integrity.py` fails outright on a mocked run and on an
  installed uxarray below the floor declared in `pyproject.toml`.
- `scripts/chrysalis_endpoint.sh` prints the real uxarray import failure and
  refuses to start instead of sending stderr to `/dev/null` and echoing
  "check import". That message was the same whether uxarray was missing, built
  against the wrong NumPy, or shadowed by a stale `~/uxarray` checkout, and the
  endpoint started anyway — so the failure surfaced on the first submitted task
  rather than at the point it could be read and fixed.
- `compare_fields`, `calculate_bias`, `calculate_rmse` and
  `calculate_pattern_correlation` area-weight their metrics. They previously
  called `.mean()` over the face dimension, which answers "average over
  cells", not "average over the sphere" — the two differ whenever cell areas
  do. On a 10° lat-lon mesh (648 faces, largest cell 11.5× the smallest) with
  a +2 K tropical / −2 K polar difference, the old code reported a bias of
  −0.667 K where the area-weighted answer is +0.004 K: wrong magnitude and
  wrong sign. Results now carry an `area_weighting` block naming the face
  dimension and the max/min area ratio. When weighting is impossible — no
  grid supplied, a non-face-centered field, or unavailable face areas — the
  result says so through `scientific_status` with the
  `AREA_WEIGHTING_UNAVAILABLE` code rather than presenting a cell-count mean
  as a spatial one.

### Changed
- The `run_analysis` `outputSchema` now requires the scientific contract
  fields per result branch instead of promising almost nothing. A result with
  `result_type: "complete"` must carry `scientific_status`, `preconditions`
  and `postconditions`; a result with `result_type: "input_required"` must
  carry `refusal`, `input_requests` and `request_state`. Both shapes share one
  schema, so a flat `required` list could only hold their intersection --
  `result_type` alone -- which left a validating client unable to rely on
  anything else being there. The front door has always emitted these; the
  schema now says so, which is what makes a number and the judgment of whether
  it means anything travel together. The refusal fields are also declared as
  properties for the first time: the schema described them in prose and never
  named them.
- Require `uxarray>=2026.8.1` (was `>=2026.8.0`), in `pyproject.toml` and the
  conda recipe. 2026.8.0 matched structured-grid nodes in the lon/lat plane
  rather than in Cartesian space, so the `nlon+1` nodes at each pole and the
  two sides of the antimeridian were never identified with each other
  (UXarray #1690). A global grid therefore carried phantom nodes and was not
  a closed surface: on a 10° mesh, 703 nodes instead of 614 and `V - E + F`
  of 1 instead of 2; on 1°, 65341 instead of 64442. `inspect_mesh` reports
  `n_node` and `n_edge` straight from the grid, so it was returning those
  inflated counts — 190 rather than 146 on this project's own structured
  fixture, 23% high. Face areas are unaffected: the area ratio and the
  `4*pi` total are identical across the two releases, because the defect is
  in node identity rather than in the metric. Also picked up in 2026.8.1:
  Dask-backed data is no longer silently realized as NumPy inside the core
  routines (#1588), and `UxDataset.isel(..., ignore_grid=True)` no longer
  crashes (#1684).

### Added
- Conformance tests that drive the real front door and validate whatever comes
  back against the `outputSchema` the server publishes for it, for a completed
  analysis, a refusal, four single-dataset operations and a comparison. The one
  test that existed validated a hand-built dict, which proves the schema is
  well formed and cannot prove we honour it, because the fixture and the schema
  were written to match. Two negative cases assert the schema rejects a
  complete result with no `scientific_status` and a refusal with no repair
  path, so a branch condition that matched nothing would fail rather than pass
  everything. `jsonschema` is now a declared dev dependency for the same
  reason: it arrives transitively today, and a resolver change would have
  turned these checks into a green no-op.
- `inspect_mesh` has a regression test asserting Euler's formula on a global
  mesh. The whole suite passed unchanged against both 2026.8.0 and 2026.8.1
  — 710 passed, 4 skipped either way — because nothing asserted a node count
  on a grid that wraps the globe, so an open sphere and a closed one looked
  the same from here. `V - E + F == 2` is the cheap invariant that separates
  them.
- Comparisons declare a `units_comparable` precondition. `bias`, `rmse` and
  the difference field are all `a - b`, which is a physical quantity only
  when both sides are on the same scale; comparing a field in K against one
  in degC previously returned 273.15 with nothing to distinguish the unit
  offset from model error. Through `run_analysis` a declared, unresolvable
  disagreement now refuses with a repair, and the `acknowledge` token still
  returns the number for a caller who means it. Undeclared units are a gap in
  the metadata rather than a contradiction, so they warn (`UNITS_UNDECLARED`)
  instead of refusing — comparing two unlabeled anomaly fields is ordinary.
  `normalize_units` resolves a fixed synonym table (`K`/`kelvin`, `m/s`/
  `m s-1`) but does no unit algebra, so equivalent-but-unaliased spellings
  such as `mm day-1` against `kg m-2 s-1` refuse and say so in the repair.

## 0.3.0 — 2026-08-29

Everything below landed after 0.1.2; the 0.2.x releases were cut without
stamping a section here, so this heading closes that gap as well as naming
the current release.

### Changed
- `UXarrayApp.serve_mcp` constructs the MCP adapter itself so the
  `tools/list` cache hints reach the server. The inherited path
  (`App.serve` → `MCPAdapter.create_and_run`) builds the adapter internally
  and silently drops `list_tools_ttl_ms`/`list_tools_cache_scope`, so the CLI
  — the path users actually run — advertised the SDK default of `ttlMs=0`,
  i.e. immediately stale, re-listing the whole catalog every turn. The hints
  do reach the wire: `mcp` 2.1.1 has
  `MODERN_PROTOCOL_VERSIONS == ("2026-07-28",)` and `ListToolsResult`
  inherits `CacheableResult`, so any client on the modern transport sees
  them. Only the legacy `initialize` handshake caps earlier, at 2025-11-25,
  and there the SDK strips them harmlessly.
- Removed `attach_resource_link` and the `_resource_links` key it wrote. It
  had no production caller, and its docstring claimed the adapter reads that
  key, which was never true.
- Require `uxarray>=2026.8.0` (was `>=2026.7.0`), in `pyproject.toml` and the
  conda recipe. 2026.7.0 and earlier compute face areas with an incorrect
  Jacobian (UXarray #1646), so the floor now excludes versions that can return
  wrong areas rather than leaving it to chance. Measured on this project's
  HEALPix z2 and 162-face structured fixtures, face areas are bit-identical
  across the two releases — the Jacobian defect does not reach these grid
  types — but the floor is set on what a release can compute, not on what our
  fixtures happen to exercise.
- `recommended_next_steps` no longer interpolates the caller's own file paths
  into every suggestion. A four-step list used to repeat the same absolute
  path four times; on an MPAS QU480 mesh those echoed paths alone were 28% of
  an `inspect_mesh` result and 36% of an `inspect_variable` result, more bytes
  than every computed number in either reply. Steps now reference a
  caller-supplied value by parameter name (`plot_mesh(grid_path)`), spell out
  only values the server discovered (`plot_variable(grid_path, data_path,
  "temperature")`), and bracket what is still missing (`<data_path>`). Results
  shrank 18-34% and the computed answer went from 25-49% of a payload to
  39-61% (#83).

### Fixed
- `divergence` accepts and forwards `scale_by_radius`. UXarray's
  `UxDataArray.divergence` takes the flag exactly as `gradient` and `curl` do,
  but every layer here called it bare — `domain/vector_calc.py`,
  `remote/compute_functions.py`, the agent, and the `run_analysis` front door,
  which accepted the parameter and dropped it. A caller asking for
  unit-sphere divergence silently got radius-scaled output, and the result
  never disclosed which it was: no `scale_by_radius` key, no
  `physical_scaling_requested`/`applied` in `scientific_status`. Divergence
  now reports both, and — like `curl` — declares the `radius_scaling`
  precondition, so unscaled output is refused rather than returned as if
  physical. Same class of defect as #87.
- `time_index` no longer selects the vertical level. Every dimension that was
  not a face dimension was reduced with `time_index`, so on a field shaped
  `(time, lev, n_face)` a request for time step 3 silently returned level 3 as
  well — a plausible-looking number from the wrong slice, with nothing in the
  output saying so. The two selectors are now distinct: `time_index` reaches
  only time-like axes, `level_index` only vertical ones, and anything else
  (an ensemble member) takes index 0 because neither selector says anything
  about it. Classification lives in one place, `uxarray_mcp.domain.dims`, so
  the plotting, vector-calculus and zonal paths cannot drift on what counts
  as a time axis; the Globus Compute worker keeps hand-inlined copies because
  module-level helpers do not survive its serialization, and tests pin those
  copies to the local behavior.
- `level_index` is reachable from the tools that need it. It existed in the
  renderer but no tool accepted it, so every plot and profile of a
  multi-level field was pinned to level 0 with no way to ask for another. It
  is now accepted by `plot_dataset` (variable and zonal-mean),
  `run_analysis(calculate_zonal_mean | azimuthal_mean)`, and their remote
  equivalents. A vertical axis is also recognized by substring rather than an
  exact-name list, which had been missing the common real spellings —
  `n_level`, `nlev`, `num_levels` — including this project's own multi-level
  fixture.
- Results say which slice they show. `reduced_dims` names each collapsed
  dimension, the index used, and how many were available; `plot_variable`
  computed it and then dropped it on the way out, so a PNG of level 0 of a
  four-level field looked like the whole field. Length-1 axes are collapsed
  without being reported, since nothing is lost. `gradient`, `curl`,
  `divergence` and the remote `plot_zonal_mean` now report it too: all four
  must collapse every non-face axis before UXarray will compute at all, so
  their answers always describe one time and one level, and a derivative of
  one level of a forty-level field is not the field's derivative. The remote
  `plot_zonal_mean` worker had built the record and then omitted it from its
  payload, so the same call disclosed its slice locally and returned `{}`
  from HPC.
- A one-sided `vmin`/`vmax` takes its open end from the slice being drawn.
  The colour limit was computed from the full array before reduction, so a
  vmin-only plot of one time step of a six-step field was scaled by the
  maximum of all six.
- Plot tools now return MCP content blocks the adapter recognizes, so an
  image reaches the client as an image. `toolregistry-server` converts a tool
  result into MCP content only when it is a list of plain dicts carrying a
  known `type`; every plot returned `mcp.types` models, which fail that
  check, so the whole list was JSON-serialized into one `TextContent` holding
  Python `repr()` strings. There was no error and no warning — the figure
  simply stopped being a figure. Verified end to end through the shipped CLI
  over stdio: a `plot_dataset` call now yields `[ImageContent, TextContent]`
  with `image/png` and a 101 KB payload. The wire shape now lives in one
  module, `uxarray_mcp.content_blocks`, because two adapter asymmetries are
  easy to get wrong at a call site: an image carries its MIME type inside
  `source` while every other block carries it on the block, and a
  `resource_link` keeps only `uri`/`name`/`mimeType` — a title, description
  or byte count set on the block is dropped, so those now ride in the
  accompanying metadata instead.
- `zonal_anomaly` reports a malformed `lat_spec` as a `ValueError` naming the
  shapes it accepts. UXarray 2026.8.0 raises `TypeError` for this where earlier
  releases raised `ValueError` (UXarray #1652), which let the raw upstream
  error escape the analysis front door as an untyped traceback instead of a
  repairable message.
- Preserve the original remote worker exception when synchronous MCP tools run
  inside an event loop instead of masking it with a nested `asyncio.run` error.
- Route facility-only paths to the endpoint with the longest configured path
  prefix before using the default endpoint.
- `list_datasets` now accepts an explicit endpoint and uses the common remote
  execution path instead of silently selecting the configured default.
- Dataset validation can run on the selected endpoint. Composite and persisted
  workflows no longer attempt facility-only paths locally, and unavailable or
  failed validation blocks downstream statistics and variable plots.
- Remote variable metadata converts NumPy scalar attributes to JSON-safe Python
  values.

### Added
- `remap_to_rectilinear` refuses when source coverage is zero, using the same
  `input_required` payload as the vector preconditions. Every value in a
  zero-coverage remap is an extrapolation, so a warning beside the numbers was
  not enough. Partial coverage and a non-conservative method remain warnings.
- Analysis results carry a `postconditions` block that is explicit about not
  having checked. `calculate_area` verifies the closed-mesh identity
  `sum(face_areas) == 4*pi*R^2` and abstains with `not_evaluated` on open or
  regional meshes rather than reporting a verdict it cannot support.
- `run_analysis` accepts `verdict_policy` (`full`, `reference_only`, `off`,
  also readable from `UXARRAY_MCP_VERDICT_POLICY`) so a caller can ask for the
  reference and tolerance without the server's own verdict. An unrecognized
  policy is rejected before the computation runs.
- Two tools under a new `contract/` namespace: `describe_response_contract`
  declares the fields a named response shape requires, and `validate_response`
  checks a candidate payload against it. This makes "right answer, wrong
  envelope" separately detectable instead of scoring as a wrong answer.
- Physical test fixtures: a global mesh carrying a real Earth `sphere_radius`,
  a four-level field whose levels are far enough apart that a mis-selection is
  unmistakable, and a half-masked field where any mean other than 1.0 means
  NaNs were folded in. Every previous fixture sat on a unit sphere, where
  radius scaling is invisible.
- `evals/multi_turn/` measures what one-call benchmarks cannot: whether a run
  chains the calls a task requires, reuses minted handles instead of inventing
  or dropping them, and recovers from an injected mid-sequence fault. Two
  injected faults, a precondition refusal and an interrupted workflow, give the
  refusal machinery something to be validated against. Two scripted adapters
  bracket the score range so the harness runs offline.
- `curl` and `divergence` declare their preconditions as data and refuse
  instead of returning an unphysical number. The refusal is shaped after the
  MCP `2026-07-28` multi-round-trip request flow: `result_type:
  "input_required"`, an `elicitation/create` request, an opaque
  `request_state`, and the specific repair for each failed check. Passing
  `acknowledge` with the named token runs the operation anyway and labels the
  result `unverified` with `physically_interpretable: false`.
- Remote scientific results now distinguish submitter and worker Python
  versions through `remote_python_version`; the runtime envelope is extensible
  to hostname, Xarray, NumPy, and scheduler identifiers.
- Curl scientific status reports whether physical scaling was requested and
  actually applied. Missing radius metadata or unsupported worker APIs cannot
  appear as a complete physical result.
- A reproducible layered-readiness matrix exercises manager, worker, path,
  portable calculation, native workflow, venue, and worker provenance across
  named endpoints.

### Fixed
- Pin the MCP Python SDK to `<2` until toolregistry-server supports the renamed
  `MCPError` exception in SDK 2.x. Fresh installs previously resolved MCP 2.0,
  installed successfully, then failed when starting the stdio server.
- CI and release verification now perform a real clean-wheel MCP handshake:
  initialize the server, list tools, and call `get_capabilities` over stdio.
- Package metadata now enforces the documented UXarray 2026.7.0 minimum used by
  the vector-calculus fixes and scientific contracts.

### Breaking
- `gradient` and `curl` now default `scale_by_radius=True`, matching UXarray's
  public API. Pass `scale_by_radius=False` explicitly to preserve the previous
  MCP unit-sphere behavior. This default alignment requires a minor release.

### Added
- Vector-calculus results now include a machine-actionable
  `scientific_status` with `status`, `physically_interpretable`, stable warning
  codes, and warning text.
- `get_capabilities` now returns variable units, standard names, dimensions,
  and a `scientific_contracts.vector_calculus` block that separates structural
  applicability from semantic suitability.
- Persistent JSON and NetCDF artifacts are written atomically under a process
  lock so concurrent tool calls cannot expose partial result files.
- `gradient`, `curl`, and `divergence` (via `run_analysis` and the
  `calculate_gradient`/`calculate_curl`/`calculate_divergence` tools) now
  accept `time_index`/`level_index` to select a single time/level slice
  when the input variable(s) carry those extra dimensions. Previously these
  operations raised `Curl computation currently only supports
  1-dimensional data` on any real multi-level/multi-time model output
  (e.g. E3SM `U`/`V` shaped `(time, lev, n_face)`), forcing the caller to
  pre-slice the file out-of-band before calling the tool. Both parameters
  default to 0 and are ignored for variables that are already
  face-centered only, so existing calls are unaffected.

### Changed
- `calculate_gradient` and `calculate_curl` (local and remote) now capture
  UXarray's own `UserWarning`s raised during the actual computation --
  e.g. `scale_by_radius=True` silently falling back to unit-sphere output
  when the grid has no `sphere_radius` attribute -- and merge them into
  the tool's `component_warnings`/`_provenance.warnings`. Previously these
  warnings only reached a terminal's stderr and were invisible to an agent
  reading the tool's structured JSON result.

### Fixed
- `analyze_dataset` and `run_scientific_agent` now actually skip zonal
  statistics after failed validation; `analyze_dataset` also skips variable
  plotting and records the validation summary in provenance.
- `analyze_dataset` derives aggregate execution venue from completed stage
  provenance instead of labeling a fallback-local run as HPC solely because
  `use_remote=True` was requested.
- The monthly release workflow now uses supported Python 3.12 instead of Python
  3.13, which conflicts with the package's `requires-python` constraint.
- `calculate_area` (local and remote) silently defaulted `area_units` to
  `"m^2"` whenever a grid's `face_areas` carried no `units` attribute at
  all, fabricating a label the source file never provided. It now reports
  `None` in that case, so an absent unit is never confused with a genuine
  (even if stale) `"m^2"` label. Found while independently verifying a
  paper claim about which production meshes carry stale area-unit
  metadata: this server's own tool -- not just the meshes -- was inventing
  metadata, the exact class of silent failure this project exists to
  prevent.
- `run_analysis` and `plot_dataset` silently ignored `use_remote=True` for
  13 operations that have no remote implementation (`validate_dataset`,
  `subset_bbox`, `subset_polygon`, `cross_section`, `compare_fields`,
  `bias`, `rmse`, `pattern_correlation`, `temporal_mean`, `anomaly`,
  `ensemble_mean`, `ensemble_spread`, `export`, and
  `plot_dataset(plot_type="mesh_geo")`), running locally without saying so.
  On a facility-only path (one that doesn't exist on the caller's machine)
  this surfaced as a confusing local `FileNotFoundError` with no indication
  `use_remote` was ever honored. These now raise `ValueError` immediately
  instead. See `docs/tools.md#remote-execution` for the full list of which
  operations do and don't support remote execution today.

### Changed
- Bumped the `uxarray` floor to the new July release (`2026.7.0`), which
  fixes `curl(grad(f))` accuracy (residual now ~1e-13 with
  `scale_by_radius=True`, previously O(1) due to an upstream gradient/curl
  normalization bug) and adds Python 3.14 support, YAC v3.18 remapping, and
  one-file `open_dataset`.
- Rebuilt YAC on the Chrysalis (ANL/LCRC) endpoint from v3.17.0 to v3.18.0
  and updated `scripts/chrysalis_endpoint.sh` to point at the new
  self-contained `~/local/yac-3.18` prefix.

### Fixed
- `domain/mesh.load_dataset` and ~20 duplicated inline branches in
  `remote/compute_functions.py` crashed with `ValueError: cannot rename
  'node_lon'...` whenever a HEALPix or GIS (shapefile/GeoJSON) grid was
  combined with a *separate* data file (e.g.
  `run_analysis(operation="gradient", grid_path="healpix:4",
  data_path=...)`). The code treated the grid's minimal `to_xarray()`
  representation as a full UGRID file, which the generic reader rejects.
  Fixed by attaching the data directly to the already-loaded `Grid` object
  instead. Added regression tests in `tests/test_domain_mesh.py` covering
  both the local and remote code paths.

### Added
- `scripts/analytic_validation.py` — a checked-in, reproducible script that
  validates `gradient`/`curl`/`divergence` against four analytic
  vector-calculus identities (including the stringent
  `curl(grad(phi)) == 0`) through the same `run_analysis` tool path an
  agent uses, against a self-contained synthetic grid (no external mesh
  file required).

## 0.1.2 — 2026-07-05

### Added
- Guided science workflows as `prompt/` tools, each composing existing
  operations around a scientific question: `cyclone_structure` (storm radial
  structure), `eddy_activity` (departures from the zonal mean),
  `model_evaluation` (bias/RMSE/pattern correlation vs a reference), and
  `climatology_anomaly` (time-mean state and anomalies). These join the existing
  `vorticity_analysis` workflow.
- `run_analysis` operation `zonal_anomaly` — per-face deviation from the zonal
  mean of each latitude band (`UxDataArray.zonal_anomaly`).
- `run_analysis` operation `remap_to_rectilinear` — remap an unstructured
  variable onto a regular lon/lat grid (`UxDataArray.remap.to_rectilinear`).
- `gradient` and `curl` operations now accept a `scale_by_radius` flag. It
  defaults to `False` to preserve unit-sphere results; set it to `True` to
  divide by `uxgrid.sphere_radius` for physical units.

### Changed
- Bumped the `uxarray` floor to `>=2026.6.0` for the new zonal-anomaly,
  rectilinear-remap, and radius-scaled gradient/curl APIs.
- **Server engine**: replaced FastMCP with
  [toolregistry](https://github.com/Oaklight/ToolRegistry) +
  [toolregistry-server](https://github.com/Oaklight/toolregistry-server).
  `fastmcp` is no longer a dependency.
- **Two-profile tool surface**: `core` (~31 tools, conservative default) and
  `deferred-full` (all tools loaded, 32 deferred behind BM25 discovery).
- **Namespace grouping**: control tools under `session/` and `hpc/`, IO under
  `io/`, prompts under `prompt/`.
- **Policy tags**: every tool carries `ToolTag` metadata (`READ_ONLY`,
  `FILE_SYSTEM`, `NETWORK`, `SLOW`) and custom tags (`experimental`,
  `stateful`) from day one.

### Added
- `src/uxarray_mcp/registry.py` — `build_registry(profile=...)` with namespace
  plan, policy tags, BM25 search hints, and prompt-as-tool wiring.
- Prompt-as-tool: `first_look`, `vorticity_analysis`, `hpc_diagnose` (formerly
  `@mcp.prompt()` decorators) are now regular tools under `prompt/` namespace.
- CLI: `uxarray-mcp serve` now accepts `--profile`, `--transport`, `--host`,
  `--port`.
- Multi-transport MCP: stdio (default), SSE, streamable HTTP.
- Optional OpenAPI/REST surface via `pip install uxarray-mcp[openapi]`.

### Removed
- `fastmcp` dependency.
- `@mcp.prompt()` decorators (replaced by `prompt/` namespace tools).

## 0.1.1 — 2026-06-11

### Changed
- Pinned Python to `>=3.12,<3.13` to match the supported runtime and avoid
  Globus Compute pickle version-mismatch failures.
- Aligned the published package metadata with the current PyPI release for the
  conda-forge recipe.

## 0.1.0 — 2026-06-04

Initial public release.

### Added
- FastMCP stdio server for UXarray mesh analysis.
- Small MCP front-door tool surface:
  - `get_capabilities`
  - `analyze_dataset`
  - `run_analysis`
  - `plot_dataset`
  - `diagnose_endpoint`
  - `probe_path_access`
  - workflow/session helpers
- UXarray-backed operations for mesh inspection, variable inspection, area
  statistics, dataset validation, zonal means, vector calculus, spatial
  subsetting, remapping/regridding, comparison metrics, temporal/ensemble
  reductions, and export.
- Inline PNG plotting for mesh, geographic mesh, variables, and zonal means.
- Optional Globus Compute execution with named endpoint profiles,
  pre-flight health checks, worker probes, and local fallback when safe.
- Scientific provenance attached to tool results.
- Stateful sessions, persisted result handles, and resumable workflows.
- CLI entry point: `uxarray-mcp` with `serve`, `setup`, `endpoints`, `doctor`,
  and `install-claude` subcommands.
- Cluster setup and validation docs for Improv, Chrysalis, and UCAR/Casper.
- PyPI release automation, package smoke tests, and conda-forge seed recipe.

### Security And Privacy
- Endpoint UUIDs are private local configuration values and are not returned in
  public MCP tool provenance or status payloads.
- Repository-local `config.yaml` is ignored; the CLI writes private user config
  under `~/.config/uxarray-mcp/config.yaml` by default.
