# Changelog

All notable changes are recorded here. Dates are ISO 8601 (UTC). The project
uses Semantic Versioning for public releases.

## Unreleased

### Fixed
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
