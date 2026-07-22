# Changelog

All notable changes are recorded here. Dates are ISO 8601 (UTC). The project
uses Semantic Versioning for public releases.

## Unreleased

### Added
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
