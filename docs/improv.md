# Improv Endpoint

**Improv** is a 736-node AMD EPYC "Zen 3" cluster at Argonne National Laboratory,
operated by the Laboratory Computing Resource Center (LCRC). It runs RHEL 8 and
uses PBS Pro for job scheduling. Nodes have 128 cores and 256 GB RAM. Storage is
on the LCRC GPFS filesystem (`/gpfs/fs1/`).

- **Location:** Argonne National Laboratory, Lemont, IL
- **Operator:** LCRC — <https://lcrc.anl.gov>
- **Access:** ANL/LCRC account — <https://accounts.lcrc.anl.gov>
- **System page:** <https://www.lcrc.anl.gov/systems/improv>
- **Scheduler:** PBS Pro
- **Login:** `ssh <username>@improv.lcrc.anl.gov`

## Key Points

- The **MCP server does not need to be cloned on Improv** — remote functions are
  sent as source code via `AllCodeStrategies`.
- The venv Python version should match the local SDK as closely as possible.
  Improv has Python 3.12 at `/usr/bin/python3.12` — use it to avoid Dill
  serialisation warnings from the 3.11 venv.
- Use canonical `/gpfs/fs1/home/<user>/...` paths, not `/home/<user>/...` aliases,
  when probing remote files.

## Worker Environment

| Item | Value |
|---|---|
| Venv | `~/venvs/globus-compute` |
| Python | 3.11 (existing) or 3.12 (`upgrade-venv` subcommand) |
| Scheduler | PBS Pro |
| Endpoint name | `improv-uxarray` |

## First-Time Setup

Run these on an Improv login node. The MCP server repository does not need to
be cloned on Improv, but these helper scripts do assume you have copied the
script or are running from a checkout available on the login node.

```bash
# 1. Create or upgrade the endpoint venv
scripts/improv_endpoint.sh upgrade-venv

# 2. Create the endpoint profile
source ~/venvs/globus-compute/bin/activate
globus-compute-endpoint configure improv-uxarray

# 3. Write a single-host config (for initial validation)
scripts/improv_endpoint.sh configure single-host improv-uxarray

# 4. Start
scripts/improv_endpoint.sh start
```

## Upgrading to Python 3.12 (recommended)

Eliminates the Dill version mismatch warning between the local 3.13 SDK and the
3.11 worker:

```bash
# On an Improv login node:
scripts/improv_endpoint.sh upgrade-venv
scripts/improv_endpoint.sh restart
```

## PBS-Backed Config (for real compute jobs)

```bash
scripts/improv_endpoint.sh configure pbs-debug <your-allocation> improv-uxarray
scripts/improv_endpoint.sh restart
```

## Starting the Endpoint

```bash
# In a tmux session on a login node:
scripts/improv_endpoint.sh start
```

To restart: `scripts/improv_endpoint.sh restart`
To check: `scripts/improv_endpoint.sh status`

Add the UUID to your private local config on your laptop/workstation, not to the
repository:

```bash
uxarray-mcp endpoints add improv <uuid> --set-default
```

## Validation

```bash
uv run python scripts/hpc_doctor.py --endpoint improv --timeout-seconds 180
```

Or with a real mesh file:

```bash
uv run python scripts/hpc_doctor.py \
    --endpoint improv \
    --sample-path /gpfs/fs1/home/<user>/uxarray/test/meshfiles/mpas/QU/480/grid.nc
```

## Reference Mesh Files on Improv

```
/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/QU/480/grid.nc
/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/QU/480/data.nc
/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc
/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_data_subset.nc
```

Use canonical `/gpfs/fs1/home/...` paths — the `/home/...` alias resolves
differently on worker nodes.

## Troubleshooting

**`WorkerLost`** — Python version mismatch causing Dill failure. Run `upgrade-venv`
to rebuild with Python 3.12.

**`qsub: command not found`** — scheduler binaries missing from worker PATH. The
PBS-backed config template links them via `ln -sf /opt/pbs/bin/qsub ~/venvs/...`.

**`validate_hpc_setup` passes but real jobs fail** — worker environment lacks
`uxarray` or its dependencies. Check `pip list` in the venv.
