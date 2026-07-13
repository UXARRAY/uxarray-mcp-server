# Provenance Tracking

Every tool result includes a `_provenance` block that records what ran, when, where, and with what software. This makes scientific workflows reproducible and auditable.

## What Gets Tracked

| Field | Description |
|-------|-------------|
| `tool` | Name of the tool that produced this result |
| `inputs` | The exact parameters passed to the tool |
| `execution_venue` | Where it ran — `"local"` or `"hpc:<endpoint>"` |
| `timestamp_utc` | When the tool was called (UTC) |
| `uxarray_version` | UXarray version on the local (submitting) machine |
| `remote_uxarray_version` | UXarray version on the HPC worker (remote runs only) |
| `python_version` | Python version on the executing machine |
| `warnings` | Any warnings generated during execution |
| `artifacts` | Summary of key outputs (mesh topology, area totals, etc.) |
| `selected_variable` | Which variable was analyzed (if applicable) |
| `validation_summary` | Dataset validation results (if applicable) |

For remote runs, `remote_uxarray_version` records the version that actually
computed the result on the worker. This is reported uniformly across every
compute and analysis operation (inspect, area, zonal mean/anomaly, gradient,
curl, divergence, azimuthal mean, remap/regrid, and capability discovery). When
it differs from the local `uxarray_version`, a **version-drift warning** is added
to `warnings` so that silent numerical differences between local and remote
execution are surfaced. `curl`/`divergence` additionally add **vector-component
warnings** here when the inputs do not look like genuine vector components.

## Example

```json
{
  "_provenance": {
    "tool": "run_scientific_agent",
    "inputs": { "file_path": "healpix:4", "data_path": null, "variable_name": null },
    "execution_venue": "local",
    "timestamp_utc": "2026-03-18T...",
    "uxarray_version": "2026.6.0",
    "python_version": "3.12.0",
    "warnings": [],
    "artifacts": [
      { "type": "mesh_topology", "n_face": 3072, "n_node": 3074, "format": "HEALPix" },
      { "type": "face_areas", "total_area": 5.1e14, "n_face": 3072, "area_units": "m^2" }
    ]
  }
}
```

## Why Provenance Matters

In scientific computing, knowing *what produced a result* is as important as the result itself. Provenance tracking allows:

- **Reproducibility** — re-run the exact same computation later
- **Auditing** — verify which software versions and parameters were used
- **Debugging** — trace unexpected results back to their source
- **Trust** — downstream consumers of the data can verify its origin
