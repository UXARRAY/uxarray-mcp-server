# Chrysalis Playbook

Chrysalis is an ANL/LCRC cluster with a conda-managed Python 3.12 environment
that runs uxarray. This page covers the exact steps to bring up the Globus
Compute endpoint and validate remote tool execution.

Official system information:
[Chrysalis system page](https://lcrc.anl.gov/systems/chrysalis).

If you are new to Globus Compute, read [Globus Compute Primer](globus-compute.md)
first.

## Environment

The working runtime on Chrysalis uses:

- **Python 3.12.13** (`~/.conda/envs/uxarray-yac`)
- **uxarray** — installed in the conda env
- **globus-compute-endpoint** — installed in `~/venvs/globus-compute`

This is cleaner than Improv because 3.12 is close enough to the local SDK's
3.13 that Dill serialization works without `AllCodeStrategies` workarounds
(though we use them anyway for safety).

## First-Time Setup

### 1. Log in to Chrysalis

```bash
ssh <username>@chrysalis.lcrc.anl.gov
```

### 2. Configure the endpoint

```bash
bash scripts/chrysalis_endpoint.sh configure
```

This writes:
- `~/.globus_compute/chrysalis-uxarray/user_config_template.yaml.j2`
- `~/.globus_compute/chrysalis-uxarray/user_environment.yaml`

### 3. Start the endpoint in tmux

```bash
bash scripts/chrysalis_endpoint.sh start
```

This launches a tmux session named `uxarray-endpoint`, activates the conda
env, and starts `globus-compute-endpoint`.

To reattach later: `tmux attach -t uxarray-endpoint`

### 4. Register the endpoint UUID

After first start, the endpoint UUID is printed to stdout and stored in
`~/.globus_compute/chrysalis-uxarray/endpoint.json`. Add it to your local
config:

```bash
uxarray-mcp endpoints add chrysalis <your-uuid>
```

### 5. Validate

From your local machine:

```bash
uv run python -c "
from uxarray_mcp.tools.execution_control import validate_hpc_setup
import json
r = validate_hpc_setup(endpoint='chrysalis', run_remote_probe=True)
print(json.dumps(r, indent=2))
"
```

## Restart After Login

```bash
ssh chrysalis.lcrc.anl.gov
bash scripts/chrysalis_endpoint.sh restart
```

Or to check status:

```bash
bash scripts/chrysalis_endpoint.sh status
```

## Testing Vector Calculus Tools Remotely

Once the endpoint is running, test from your local machine:

```bash
uv run python -c "
from uxarray_mcp.tools.vector_calc import calculate_gradient
r = calculate_gradient(
    '/path/to/grid.nc',
    '/path/to/data.nc',
    'your_variable',
    use_remote=True,
    endpoint='chrysalis',
)
print('venue:', r['_provenance']['execution_venue'])
print('components:', r['components'])
"
```

## Important: Use Slurm for Real Work

Chrysalis login nodes **kill processes** that use significant CPU or memory.
The default `single-host` config runs workers on the login node and will
fail for any real UXarray analysis (mesh loading, plotting, computation).

For actual use, configure with the Slurm backend:

```bash
bash scripts/chrysalis_endpoint.sh configure slurm-debug
bash scripts/chrysalis_endpoint.sh restart
```

This submits workers as proper Slurm jobs on compute nodes. Use
`single-host` only for quick connectivity probes (e.g. `validate_hpc_setup`
with `run_remote_probe=False`).

### E3SM Next-Gen Mesh Sizes

These meshes are available on Chrysalis at:
`/lcrc/group/e3sm/ac.xylar/polaris_1.0/chrysalis/test_20260520/unified-mesh-topo-cull2/e3sm/init/`

| Mesh | Faces | Nodes | Size | Resolution |
|---|---|---|---|---|
| `u.oi240.lr240` | 7,293 | 15,422 | 8.5 MB | Low (240 km) |
| `u.oi30.lr10` | 462,919 | 940,119 | 561 MB | Mid (30 km) |
| `u.oi6to18.lr6to10` | 4,015,940 | 8,086,361 | 4.8 GB | High (6–18 km) |

## Known Issues

- `conda` is not on the worker PATH — the `worker_init` in the config template
  activates the env via the full conda init path instead.
- If `globus-compute-endpoint` is not found after `conda activate`, verify
  that `~/venvs/globus-compute/bin` is on your PATH.
- Login node kills: always use `configure slurm-debug` for UXarray work.
