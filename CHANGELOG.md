# Changelog

All notable changes are recorded here. Dates are ISO 8601 (UTC). The project
uses Semantic Versioning for public releases.

## Unreleased

### Changed
- **Server engine**: replaced FastMCP with
  [toolregistry](https://github.com/Oaklight/ToolRegistry) +
  [toolregistry-server](https://github.com/Oaklight/toolregistry-server).
  `fastmcp` is no longer a dependency.
- **Two-profile tool surface**: `core` (~27 tools, conservative default) and
  `deferred-full` (all tools loaded, 30 deferred behind BM25 discovery).
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
