# Changelog

All notable changes are recorded here. Dates are ISO 8601 (UTC). The
project follows [Semantic Versioning](https://semver.org/) once `1.0.0`
is released; pre-1.0 minor bumps may include breaking changes documented
under their entry.

## Unreleased

### Added
- `uxarray-mcp` CLI entry point with subcommands: `serve`, `setup`,
  `endpoints add/list/remove`, `doctor`, `install-claude`.
- Multi-endpoint config schema (`hpc.endpoints.<name>` with
  `endpoint_id`, `path_prefixes`, `timeout_seconds`) and config
  discovery order: `$UXARRAY_MCP_CONFIG` → `~/.config/uxarray-mcp/config.yaml`
  → `./config.yaml`.
- YAC remote build script (`scripts/hpc_build_yac.py`) and runtime
  fallback that loads `yac.core` via `importlib.machinery` when the
  upstream `__init__.py` is unconditional.
- `remote_subset_bbox_plot`: bounding-box subset + plot in a single
  remote call; returns inline PNG.
- Persisted workflows (`run_workflow`, `resume_workflow`,
  `get_workflow_status`) and stateful sessions
  (`create_session`, `register_dataset`, `get_session_state`).
- Advanced analysis tools: temporal mean, anomaly, ensemble mean/spread,
  bias, RMSE, pattern correlation, cross-section extraction, polygon
  subsetting, regridding, NetCDF/CSV export.
- Multi-platform CI: Python 3.11/3.12/3.13 on Ubuntu plus Python 3.13
  on macOS; `cli-smoke` job exercises the installed entry point.
- Apache 2.0 LICENSE.

### Changed
- Collapsed the `*_hpc` tool surface. The unified tools
  (`inspect_mesh`, `inspect_variable`, `calculate_area`, plotting tools,
  etc.) accept `use_remote: bool` and `endpoint: str | None`; there are
  no separate `_hpc` tool names.
- `endpoints add/remove` now honor `$UXARRAY_MCP_CONFIG` so the write
  target follows the same config the rest of the server reads.
- README: replaced the "private repo" install instructions with the
  public-clone path and added a `How it runs` section with two ASCII
  diagrams (local stdio vs HPC dispatch).

### Fixed
- HPC plotting discovery and fast-fail behavior (PR #36 follow-up).
- Session-aware plotting for handle-based dataset references.
- Remote catalog scanning surfaces accurate path metadata.
- `_run_with_optional_hpc` no longer falls back to a local file read when
  `use_remote=True` is requested for a path that does not exist on the
  client. The dispatcher now raises a clear `RuntimeError` naming the
  endpoint state (no endpoint configured, or endpoint not ready) instead
  of surfacing a misleading `FileNotFoundError` from the local fallback.
  Local paths and HEALPix specs still fall back silently. (#27)
- `plot_mesh`, `plot_variable`, and `plot_zonal_mean` HPC wrappers now
  accept `session_id` + `dataset_handle` and resolve grid/data paths
  from a registered session dataset, matching the handle pattern
  already used by `subset_bbox` / `subset_polygon`. Direct paths still
  work unchanged. (#25)

## 0.1.0 — initial scaffold

Initial repository skeleton with core inspection and area tools.
Predates the multi-endpoint, CLI, and unified-tool work and was never
tagged or released; superseded by the unreleased entries above.
