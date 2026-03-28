# Scientific Agent

The scientific agent is an autonomous four-stage pipeline that performs a complete analysis workflow on a mesh dataset.

## How It Works

The agent follows an **Analyze > Plan > Execute > Verify** loop:

1. **Analyze** — Inspects the mesh to determine format, topology, and size. Decides whether to run locally or on HPC based on file path and face count.

2. **Plan** — Determines which operations to run. If data and a variable are provided, it plans variable inspection, area calculation, zonal mean, and validation. If only a grid is provided, it plans mesh inspection and area calculation only.

3. **Execute** — Runs each planned operation, routing to local or HPC as decided in the analysis step. If validation fails, downstream steps like zonal mean are skipped to avoid producing unreliable results.

4. **Verify** — Reviews all results and produces a summary with any warnings or issues detected.

## Usage

```
Run a full scientific analysis on healpix:4
```

```
Analyze /lus/grand/projects/climate/mesh.nc with data.nc
```

## Validation Gating

The agent runs dataset validation before computing zonal means. If the validation step detects problems (NaN contamination, Inf values, fill value issues), the zonal mean step is skipped. This prevents the agent from producing results that look correct but are scientifically meaningless.

## Auto-Routing

The agent automatically decides where to run each operation:

- **Local** — files on your machine with meshes under 1 million faces
- **HPC** — files on known HPC filesystems (`/home/`, `/lus/`, `/grand/`, `/scratch/`, `/projects/`, `/gpfs/`) or meshes with more than 1 million faces

This decision is made once during the Analyze stage and applied to all subsequent operations.

## Output

The agent returns a full reasoning trace showing what it decided at each stage, along with all results:

- `reasoning_trace` — what the agent decided and why at each step
- `mesh_summary` — topology and format information
- `area_results` — face area statistics
- `variable_results` — variable metadata and statistics (if data provided)
- `zonal_mean_results` — latitude-band averages (if applicable and validation passed)
- `validation_summary` — dataset integrity check results
- `verification` — final summary and any warnings
- `_provenance` — full traceability metadata
