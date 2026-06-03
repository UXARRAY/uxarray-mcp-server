# Chrysalis Endpoint

Chrysalis is an ANL/LCRC cluster hosting E3SM next-generation ocean meshes.

## Key Points

- The **MCP server does not need to be cloned on Chrysalis** — remote functions
  are sent as source code via `AllCodeStrategies` and only need `uxarray` + deps
  in the worker environment.
- Login nodes **kill compute processes** — always use the Slurm backend.
- `unset PYTHONPATH` before every endpoint start — the conda `uxarray-yac` env
  injects broken `pydantic_core` paths that crash workers.

## Worker Environment

| Item | Value |
|---|---|
| Venv | `~/venvs/globus-compute-py313` (Python 3.13) |
| Slurm partition | `debug` (4h walltime, 20 nodes) |
| Compute nodes | 251 GB RAM, 128 CPUs |
| Endpoint name | `uxarray-chrysalis` |

## First-Time Setup

```bash
# 1. Create Python 3.13 conda env
/gpfs/fs1/soft/chrysalis/manual/miniforge3/25.3.1/bin/conda create \
    -n gc-py313 python=3.13 -y

# 2. Build the globus-compute venv
~/.conda/envs/gc-py313/bin/python -m venv ~/venvs/globus-compute-py313
~/venvs/globus-compute-py313/bin/pip install \
    "globus-compute-endpoint==4.12.0" \
    uxarray xarray netCDF4 h5netcdf numpy matplotlib holoviews cartopy

# 3. Configure the endpoint (Slurm-backed)
unset PYTHONPATH
~/venvs/globus-compute-py313/bin/globus-compute-endpoint configure uxarray-chrysalis

cat > ~/.globus_compute/uxarray-chrysalis/user_config_template.yaml.j2 << 'EOF'
endpoint_setup: ""
engine:
  type: GlobusComputeEngine
  max_workers_per_node: 4
  provider:
    type: SlurmProvider
    partition: debug
    nodes_per_block: 1
    init_blocks: 0
    min_blocks: 0
    max_blocks: 2
    walltime: "04:00:00"
    worker_init: |
      unset PYTHONPATH
    launcher:
      type: SrunLauncher
idle_heartbeats_soft: 10
idle_heartbeats_hard: 5760
EOF

cat > ~/.globus_compute/uxarray-chrysalis/user_environment.yaml << 'EOF'
PYTHONPATH: ""
PATH: "/home/<username>/venvs/globus-compute-py313/bin:/usr/bin:/bin"
EOF
```

## Starting the Endpoint

Run this every time you log in:

```bash
unset PYTHONPATH
~/venvs/globus-compute-py313/bin/globus-compute-endpoint start uxarray-chrysalis
```

The endpoint prints its UUID. Add it to your **local** `config.yaml` (never commit the UUID):

```bash
# On your laptop:
uxarray-mcp endpoints add chrysalis <uuid>
```

## Validation

From your laptop after the endpoint is running:

```bash
uv run python scripts/hpc_doctor.py --endpoint chrysalis --timeout-seconds 120
```

Or manually:

```python
from uxarray_mcp.tools.execution_control import endpoint_status, validate_hpc_setup

print(endpoint_status(endpoint='chrysalis', force=True))
print(validate_hpc_setup(endpoint='chrysalis', run_remote_probe=True,
                          probe_timeout_seconds=120))
```

## E3SM Next-Generation Ocean Meshes

Available at `/lcrc/group/e3sm/ac.xylar/polaris_1.0/chrysalis/test_20260520/unified-mesh-topo-cull2/`:

| Mesh | Faces | Size | Notes |
|---|---|---|---|
| `mesh/.../u.oi240.lr240/base_mesh/build/base_mesh.nc` | 10,302 | 12 MB | Full globe, unculled |
| `e3sm/init/u.oi240.lr240/.../culled_ocean_no_cavities_mesh.nc` | 7,293 | 8.5 MB | Ocean only |
| `e3sm/init/u.oi30.lr10/.../culled_ocean_no_cavities_mesh.nc` | 462,919 | 561 MB | Ocean only |
| `e3sm/init/u.oi6to18.lr6to10/.../culled_ocean_no_cavities_mesh.nc` | 4,015,940 | 4.8 GB | Variable-res 6–18 km |

## Troubleshooting

**`ENDPOINT_NOT_ONLINE`** — the Slurm debug job timed out (4h limit). Restart with `unset PYTHONPATH && ~/venvs/globus-compute-py313/bin/globus-compute-endpoint start uxarray-chrysalis`.

**`WorkerLost` or `SystemError`** — PYTHONPATH is set. Always `unset PYTHONPATH` before starting the endpoint.

**`pydantic_core` not found** — conda env leaked into the worker. Check `user_environment.yaml` has `PYTHONPATH: ""` and restart.
