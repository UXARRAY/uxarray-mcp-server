# Changelog

## 0.2.0 (2026-04)

### Visualization Tools
- `plot_mesh` — mesh wireframe rendered as inline PNG; supports custom width/height
- `plot_variable` — face-centered variable rendered as filled polygon map; supports `cmap`, `vmin`, `vmax`, `title`
- `plot_zonal_mean` — latitude vs. value line chart; supports `line_color`, `title`, `lat_spec`, `conservative`
- Empty file guard: clear `ValueError` raised if input file is zero bytes or rendered output is empty

## 0.1.0 (2026-03)

Initial release.

### Tools
- `inspect_mesh` — mesh topology analysis with format detection
- `inspect_variable` — variable metadata and statistics
- `calculate_area` — face area computation
- `calculate_zonal_mean` — latitude-band averaging (conservative and non-conservative)
- `validate_dataset` — data quality checks (NaN, Inf, fill values)
- `get_capabilities` — tool discovery filtered by grid topology and data
- `get_execution_mode` / `set_execution_mode` — runtime mode control

### HPC
- Globus Compute integration via Academy
- Pre-flight endpoint health checks
- Automatic fallback to local on endpoint failure
- HPC variants of core tools (`inspect_mesh_hpc`, `calculate_area_hpc`, `inspect_variable_hpc`, `calculate_zonal_mean_hpc`)

### Scientific Agent
- Autonomous four-stage pipeline (Analyze > Plan > Execute > Verify)
- Auto-routing between local and HPC based on file path and mesh size
- Validation-gated workflows (skip zonal mean if validation fails)

### Infrastructure
- Provenance tracking on all tool outputs
- Dynamic HPC tool registration
- HEALPix virtual mesh support
- CI with split core and HPC test lanes
