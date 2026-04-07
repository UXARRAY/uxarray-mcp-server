#!/usr/bin/env bash
# Creates 10 feature issues on UXARRAY/uxarray-mcp-server.
# Usage:
#   gh auth login          # if not already authenticated
#   chmod +x create-issues.sh
#   ./create-issues.sh
set -euo pipefail
REPO="UXARRAY/uxarray-mcp-server"

echo "Creating 10 feature issues on $REPO..."
echo ""

# ── 1. Visualization Tools ──────────────────────────────────────────────────
gh issue create --repo "$REPO" \
  --title "Visualization tools: plot_mesh, plot_variable, plot_zonal_mean" \
  --label "enhancement" \
  --body "## Summary

Add MCP tools that return rendered images (PNG/SVG URLs or base64) so AI agents can show users maps, mesh wireframes, and zonal-mean profiles inline.

## Motivation

The server computes results but never renders them. Agents that can't show a plot are half-blind — scientists need to *see* the data to trust it. UXarray already has plotting support via HoloViz/Matplotlib, so the rendering layer exists.

## Proposed Tools

| Tool | Description |
|------|-------------|
| \`plot_mesh(grid_path, style)\` | Render mesh wireframe or filled polygons |
| \`plot_variable(grid_path, data_path, variable, projection)\` | Choropleth map of a face/node/edge variable |
| \`plot_zonal_mean(grid_path, data_path, variable)\` | Latitude vs. value line plot |

## Design Considerations

- Return images as base64 data URIs or temp-file paths that the MCP client can render.
- Support common projections (PlateCarree, Robinson, Orthographic).
- Keep rendering in the domain layer so HPC can optionally generate server-side plots.
- Add \`_provenance\` to plot results (same as all other tools).
- Consider a \`plot_style\` parameter (light/dark theme, colormap).

## Priority

High — biggest gap in the current toolset."

echo "  ✓ Issue 1: Visualization Tools"

# ── 2. Remapping / Regridding ────────────────────────────────────────────────
gh issue create --repo "$REPO" \
  --title "Remapping / regridding tool" \
  --label "enhancement" \
  --body "## Summary

Add an MCP tool for remapping data between unstructured grids (e.g. MPAS → lat-lon, ICON → UGRID).

## Motivation

Comparing datasets on different meshes is one of the most common scientific tasks. Currently users must leave the agent workflow to run CDO/ESMF regridding externally. UXarray supports remapping natively — wrapping it completes a major workflow.

## Proposed Tool

\`\`\`
remap(
    source_grid: str,
    source_data: str,
    target_grid: str,
    variable: str,
    method: str = \"nearest_neighbor\"  # or \"bilinear\", \"conservative\"
) -> dict
\`\`\`

## Returns
- Remapped variable statistics (min, max, mean on target grid)
- Target grid summary
- Provenance with source/target info

## Design Considerations

- Support nearest-neighbor, bilinear, and conservative methods.
- Add HPC variant (\`remap_hpc\`) for large meshes.
- Consider writing output to a file (ties into the Export issue).
- Gate on dataset validation — don't remap data with NaN/fill issues."

echo "  ✓ Issue 2: Remapping / Regridding"

# ── 3. Subsetting / Spatial Queries ──────────────────────────────────────────
gh issue create --repo "$REPO" \
  --title "Subsetting / spatial query tools" \
  --label "enhancement" \
  --body "## Summary

Add MCP tools for cropping a mesh and its data to a geographic region — bounding box, named region, or arbitrary GeoJSON polygon.

## Motivation

Scientists almost always zoom into a region before analyzing. The \`get_capabilities\` tool already lists UXarray subsetting APIs (\`cross_section_*\`, \`subset\`) that aren't wrapped yet. This is the second thing every user will ask for after \"show me the data.\"

## Proposed Tools

| Tool | Description |
|------|-------------|
| \`subset_bbox(grid, data, lat_min, lat_max, lon_min, lon_max)\` | Bounding-box crop |
| \`subset_polygon(grid, data, geojson)\` | Arbitrary polygon crop |
| \`cross_section(grid, data, lat_or_lon, value)\` | Extract a cross-section |

## Returns
- Subsetted mesh summary (n_face, n_node, n_edge for the subset)
- Variable statistics on the subset
- Provenance

## Design Considerations

- Named region presets (\"Arctic\", \"North Atlantic\", \"Tropics\") for convenience.
- Chain with other tools: subset → zonal mean, subset → plot.
- Add HPC variant for large meshes.
- Consider returning the subset as a temporary file path for downstream tools."

echo "  ✓ Issue 3: Subsetting / Spatial Queries"

# ── 4. Multi-Step Workflow Composition (DAGs) ────────────────────────────────
gh issue create --repo "$REPO" \
  --title "Multi-step workflow composition (DAG builder)" \
  --label "enhancement" \
  --body "## Summary

Enable AI agents to compose arbitrary multi-step scientific workflows instead of relying on the hard-coded Analyze → Plan → Execute → Verify pipeline.

## Motivation

The current \`run_scientific_agent\` runs a fixed 4-stage pipeline. Real scientific analysis is more varied: \"validate, then subset to the Arctic, then compute zonal mean, then plot.\" Agents need a way to chain tools dynamically.

## Possible Approaches

1. **MCP Resource for tool chains** — expose a resource that describes valid tool sequences, dependencies, and data flow. The AI agent reads it and decides the order.
2. **Workflow tool** — \`run_workflow(steps=[...])\` that takes a list of tool calls with data-flow edges and executes them as a DAG.
3. **Session state** — let each tool accept output from a previous tool's result ID, building implicit chains.

## Design Considerations

- Validation gating should be composable: any step can declare a precondition.
- Provenance should chain — each step's provenance references its upstream.
- Error handling: partial results, retry, and fallback at each step.
- Keep it simple enough that agents can use it without complex planning.

## Priority

High — this turns a tool shelf into a real scientific assistant."

echo "  ✓ Issue 4: Multi-Step Workflow Composition"

# ── 5. Time-Series & Ensemble Support ────────────────────────────────────────
gh issue create --repo "$REPO" \
  --title "Time-series and ensemble analysis tools" \
  --label "enhancement" \
  --body "## Summary

Add time-dimension awareness to the tool suite — temporal means, time series extraction, and ensemble statistics.

## Motivation

The current tools operate on single snapshots. Climate and weather data almost always has a time dimension. Temporal analysis (trends, anomalies, seasonal cycles) and ensemble statistics (spread, percentiles) are the most common analysis patterns.

## Proposed Tools

| Tool | Description |
|------|-------------|
| \`temporal_mean(grid, data, variable, time_range)\` | Average over time dimension |
| \`time_series_at_point(grid, data, variable, lat, lon)\` | Extract time series at nearest face |
| \`temporal_anomaly(grid, data, variable, climatology)\` | Compute departure from mean |
| \`ensemble_statistics(grid, data_paths[], variable)\` | Mean, spread, percentiles across runs |

## Design Considerations

- Auto-detect the time dimension name (\`time\`, \`Time\`, \`xtime\`, \`nTime\`).
- Support ISO time ranges and calendar-aware grouping (DJF, JJA, annual).
- Ensemble tools should handle different file layouts (one file per member vs. stacked).
- Integration with visualization: \`plot_time_series\`, \`plot_ensemble_spread\`.
- HPC variants for large ensembles."

echo "  ✓ Issue 5: Time-Series & Ensemble Support"

# ── 6. Data Catalog / Discovery Resource ─────────────────────────────────────
gh issue create --repo "$REPO" \
  --title "Data catalog / discovery MCP resource" \
  --label "enhancement" \
  --body "## Summary

Expose an MCP *resource* (not a tool) that indexes available datasets on disk or HPC filesystems, so users don't need to type exact file paths.

## Motivation

The biggest friction point is knowing what files exist and where. Scientists working on HPC clusters have thousands of NetCDF files across scratch, project, and archive directories. Letting the agent browse a catalog — \"show me all MPAS meshes in \`/scratch/climate/\`\" — dramatically lowers the barrier to entry.

## Proposed Design

- **MCP Resource URI**: \`uxarray://catalog/{base_path}\`
- Returns: list of mesh/data files with detected format, variable names, mesh size, and modification date.
- **Indexing**: recursive scan with caching (SQLite or JSON sidecar).
- **Filters**: by format, mesh size, variable name, date range.

## Design Considerations

- Use UXarray's format detection to auto-classify files.
- Cache index to avoid re-scanning large directories on every call.
- Support both local and HPC filesystem paths.
- Privacy: only index directories the user explicitly opts in.
- Consider integration with Globus Transfer for cross-site data discovery."

echo "  ✓ Issue 6: Data Catalog / Discovery Resource"

# ── 7. Comparison & Difference Tools ─────────────────────────────────────────
gh issue create --repo "$REPO" \
  --title "Comparison and difference tools (bias, RMSE, correlation)" \
  --label "enhancement" \
  --body "## Summary

Add tools for comparing meshes and computing difference statistics between datasets — bias, RMSE, pattern correlation.

## Motivation

Model evaluation is one of the most frequent scientific tasks: comparing a simulation against observations or another model. This currently requires bespoke scripts outside the agent workflow.

## Proposed Tools

| Tool | Description |
|------|-------------|
| \`compare_meshes(grid_a, grid_b)\` | Topology comparison (resolution, coverage, format) |
| \`diff_variables(grid, data_a, data_b, variable)\` | Point-wise difference statistics |
| \`compute_metrics(grid, data_a, data_b, variable)\` | Bias, RMSE, pattern correlation, skill scores |

## Returns
- Difference statistics: mean bias, RMSE, min/max difference
- Spatial correlation coefficient
- Per-latitude-band breakdown (ties into zonal mean)
- Provenance linking both input datasets

## Design Considerations

- Handle different grids: auto-remap to common grid if needed (ties into Remapping issue).
- Support masked regions (land/ocean masking).
- Validation gating: skip comparison if either dataset has quality issues.
- Visualization integration: \`plot_difference_map\`, \`plot_taylor_diagram\`."

echo "  ✓ Issue 7: Comparison & Difference Tools"

# ── 8. Export / Format Conversion ────────────────────────────────────────────
gh issue create --repo "$REPO" \
  --title "Export and format conversion tools" \
  --label "enhancement" \
  --body "## Summary

Add tools to write analysis results and converted data back to standard file formats (NetCDF/UGRID, SCRIP, lat-lon CF-compliant).

## Motivation

Right now results stay in tool-response JSON. Scientists need files they can pass to NCL, CDO, ParaView, or share with collaborators. Closing the loop from \"analyze\" to \"produce a file\" keeps the entire workflow inside the agent.

## Proposed Tools

| Tool | Description |
|------|-------------|
| \`export_to_netcdf(grid, data, output_path, format)\` | Write data to NetCDF in specified convention |
| \`convert_mesh_format(grid, target_format, output_path)\` | Convert between mesh formats |
| \`export_zonal_mean(results, output_path, format)\` | Write zonal mean profile to CSV/NetCDF |

## Design Considerations

- Support UGRID, SCRIP, and CF-compliant lat-lon output.
- Include provenance metadata as NetCDF global attributes.
- Handle HPC paths: write to remote filesystems via Globus.
- Validate output: read-back check to confirm round-trip fidelity.
- Security: restrict output paths to user-owned directories."

echo "  ✓ Issue 8: Export / Format Conversion"

# ── 9. Streaming Progress for Long Operations ───────────────────────────────
gh issue create --repo "$REPO" \
  --title "Streaming progress notifications for long-running operations" \
  --label "enhancement" \
  --body "## Summary

Use MCP's progress notification mechanism to report incremental status during long-running HPC operations and large-mesh computations.

## Motivation

Large meshes (10M+ faces) on HPC can take minutes. Currently the agent goes silent until the result returns. Streaming progress (\"25% complete… zonal mean running on 2.6M faces…\") makes HPC jobs feel responsive instead of black-box.

## Proposed Implementation

- Use FastMCP's \`Context.report_progress()\` / progress tokens from the MCP spec.
- Report stages: submission → queued → running → percentage → complete.
- For local operations: report per-step progress in the scientific agent pipeline.
- For HPC operations: poll Globus Compute task status and relay updates.

## Design Considerations

- MCP progress notifications are optional — degrade gracefully if the client doesn't support them.
- Avoid polling too frequently on HPC (respect endpoint rate limits).
- Include estimated time remaining when possible.
- Log progress to provenance for post-hoc analysis of performance."

echo "  ✓ Issue 9: Streaming Progress"

# ── 10. Multi-Dataset Agent Memory / Session State ───────────────────────────
gh issue create --repo "$REPO" \
  --title "Multi-dataset session state / agent memory" \
  --label "enhancement" \
  --body "## Summary

Add a lightweight session/context layer so the scientific agent can remember which datasets are loaded, what's been validated, and what the user has already asked — avoiding redundant work across a conversation.

## Motivation

The scientific agent is currently stateless — every \`run_scientific_agent\` call starts from scratch. If a user validates a dataset, then asks for zonal mean, then asks for a plot, the agent re-loads and re-validates every time. Session state would let it build on previous results.

## Proposed Design

- **Session object**: tracks loaded grids, validated datasets, computed results, and their provenance IDs.
- **Cache layer**: keep UXarray Grid/Dataset objects in memory across tool calls within a session.
- **Result references**: tools can accept a \`result_id\` from a previous tool's provenance instead of re-specifying file paths.
- **Session lifecycle**: auto-expire after inactivity; explicit \`clear_session\` tool.

## Design Considerations

- Memory pressure: large datasets can be GBs. Use LRU eviction or lazy loading.
- Thread safety: MCP servers may handle concurrent requests.
- Persistence: optionally serialize session to disk for resumption.
- Privacy: session data should never leak between different users/connections.
- Integration with workflow composition (DAG issue) — sessions provide the implicit data flow."

echo "  ✓ Issue 10: Multi-Dataset Agent Memory"

echo ""
echo "✅ All 10 issues created successfully!"
