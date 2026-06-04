# Chrysalis Endpoint

**Chrysalis** is a 492-node AMD EPYC cluster at Argonne National Laboratory,
operated by the Laboratory Computing Resource Center (LCRC). It is an E3SM
dedicated facility used for model runs and post-processing. Nodes have 128
cores and 256 GB RAM. Storage is on the LCRC GPFS filesystem (`/lcrc/group/`),
which hosts the E3SM next-generation mesh library.

- **Location:** Argonne National Laboratory, Lemont, IL
- **Operator:** LCRC — <https://lcrc.anl.gov>
- **Access:** ANL/LCRC account — <https://accounts.lcrc.anl.gov>
- **System page:** <https://lcrc.anl.gov/systems/chrysalis>
- **Scheduler:** Slurm
- **Login:** `ssh <username>@chrysalis.lcrc.anl.gov`

## Key Points

- The **MCP server does not need to be cloned on Chrysalis** — remote functions
  are sent as source code via `AllCodeStrategies` and only need `uxarray` + deps
  in the worker environment.
- Login nodes **kill compute processes** — always use the Slurm backend.
- YAC remapping needs the Python 3.12 `uxarray-yac` environment plus YAC, MKL,
  MPICH, NetCDF, and local shim library paths. Use
  `scripts/chrysalis_endpoint.sh` instead of hand-writing those paths.
- If a remote probe times out after the endpoint is `registered`, inspect the
  endpoint logs on Chrysalis with `scripts/chrysalis_endpoint.sh logs`.

## Worker Environment

| Item | Value |
|---|---|
| UXarray/YAC env | `~/.conda/envs/uxarray-yac` (Python 3.12) |
| Endpoint helper venv | `~/venvs/globus-compute-py313` |
| Slurm partition | `debug` (4h walltime, 20 nodes) |
| Compute nodes | 251 GB RAM, 128 CPUs |
| Endpoint name | `uxarray-chrysalis` |

## First-Time Setup

The checked-in helper script writes the endpoint profile, YAC runtime library
paths, and small BLAS/LAPACK shims needed by the current YAC build:

```bash
git clone https://github.com/UXARRAY/uxarray-mcp-server.git
cd uxarray-mcp-server
bash scripts/chrysalis_endpoint.sh configure slurm-debug
bash scripts/chrysalis_endpoint.sh check-yac
```

The `check-yac` command runs a tiny Slurm job that imports `yac.core`, imports
UXarray's YAC helper, and remaps HEALPix zoom 2 to zoom 3. It should report
`yac_core_ok: true` and `remap_ok: true` before the endpoint is used by MCP.

## Starting the Endpoint

Run this every time you log in:

```bash
bash scripts/chrysalis_endpoint.sh start
```

The endpoint prints its UUID. Add it to your private local config on your
laptop/workstation, never to the repository:

```bash
# On your laptop:
uxarray-mcp endpoints add chrysalis <uuid> --set-default
```

## Validation

From your laptop after the endpoint is running:

```bash
uv run python scripts/hpc_doctor.py --endpoint chrysalis --timeout-seconds 120
uv run --extra hpc python scripts/yac_smoke_test.py \
  --endpoint chrysalis --timeout-seconds 300
```

Or manually:

```python
from uxarray_mcp.tools.execution_control import endpoint_status, validate_hpc_setup

print(endpoint_status(endpoint='chrysalis', force=True))
print(validate_hpc_setup(endpoint='chrysalis', run_remote_probe=True,
                          probe_timeout_seconds=120))
```

If the manager reports `registered` but worker probes time out, inspect the
remote side on Chrysalis:

```bash
bash scripts/chrysalis_endpoint.sh logs
squeue -u "$USER"
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

**`ENDPOINT_NOT_ONLINE`** — the Slurm debug job timed out (4h limit). Restart
with `bash scripts/chrysalis_endpoint.sh restart`.

**Worker probe timeout after `registered`** — the manager is connected, but a
Slurm worker did not return. Run `bash scripts/chrysalis_endpoint.sh logs` on
Chrysalis and inspect the latest submit script/log pair.

**`pydantic_core` not found** — the worker is running from the wrong Python
environment. Re-run `bash scripts/chrysalis_endpoint.sh configure slurm-debug`
and restart the endpoint.

**`libnetcdf.so.22`, `liblapack.so.3`, or `libblas.so.3` not found** — the YAC
runtime paths or local MKL shims are missing. Re-run
`bash scripts/chrysalis_endpoint.sh configure slurm-debug`, then
`bash scripts/chrysalis_endpoint.sh check-yac`.

**`PMI_Init failed` or `WorkerLost` during YAC import** — YAC initializes MPI.
Inside a Globus Compute worker, run the YAC smoke/remap through the dedicated
smoke path, which launches the native YAC child process with
`srun --ntasks 1` when `SLURM_JOB_ID` is present.
