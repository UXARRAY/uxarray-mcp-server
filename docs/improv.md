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

- The **MCP server must be cloned on Improv** — `improv_endpoint.sh` lives in it
  — but it must never be importable by the worker. Remote functions are sent as
  source code via `AllCodeStrategies`, so the worker venv needs only `uxarray`
  and its dependencies.
- Dill serialises cleanly between matching Python minor versions, so the worker
  venv should be on the same minor version as the machine you drive it from.
  uxarray-mcp targets 3.12, and Improv has Python 3.12 at `/usr/bin/python3.12`
  — use it, and a mismatch warning goes away.
- Use canonical `/gpfs/fs1/home/<user>/...` paths, not `/home/<user>/...` aliases,
  when probing remote files.
- `scripts/endpoint.sh` is the site-agnostic version of this script — start
  there if you are standing up your first endpoint on some other machine.
- Copying files is Globus Transfer, a separate service with its own login — see
  [Moving Files](data-transfer.md).

## Worker Environment

| Item | Value |
|---|---|
| Venv | `~/venvs/globus-compute` |
| Python | 3.12 — `upgrade-venv` refuses to build with anything else |
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

Eliminates the Dill version mismatch warning you get when the worker venv is on
a different minor version than the machine driving it:

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

The template it writes asks PBS for the `debug` queue, one node per block, at
most one block, and a walltime of `00:30:00`. `configure pbs-debug` also links
`qsub`, `qstat` and `qdel` from `/opt/pbs/bin` into the venv's `bin` — that
happens at configure time, not from anything in the emitted template.

## Script Options

The script also takes `status`, which activates the venv and prints
`globus-compute-endpoint list`. Two environment variables move the defaults:
`ENDPOINT_NAME` (the Globus Compute endpoint profile name, default
`improv-uxarray`) and `PYTHON` (the interpreter `upgrade-venv` builds with,
default `/usr/bin/python3.12`).

## Starting the Endpoint

```bash
# From a plain shell on a login node:
scripts/improv_endpoint.sh start
```

`start` creates its own tmux session named `uxarray-endpoint`; run it from
outside tmux so the endpoint lives in that session rather than whichever shell
you happened to be in.

To restart: `scripts/improv_endpoint.sh restart`
To check: `scripts/improv_endpoint.sh status`

Add the UUID to your private local config on your laptop/workstation, not to the
repository:

```bash
uxarray-mcp endpoints add improv <uuid> \
    --path-prefix /gpfs/fs1/ --path-prefix /home/
```

Both mounts have to be named: an endpoint registered without a prefix claims no
paths of its own and never wins a match. Do not add `--set-default` here —
[Remote HPC](remote-hpc.md) hands the fallback default to `ucar`, and two
endpoints cannot both be it.

## Validation

```bash
uxarray-mcp doctor --endpoint improv --timeout-seconds 180
```

Or with a real mesh file:

```bash
uxarray-mcp doctor \
    --endpoint improv \
    --sample-path /gpfs/fs1/home/<user>/uxarray/test/meshfiles/mpas/QU/480/grid.nc
```

## Reference Mesh Files on Improv

These are UXarray's own test meshfiles, and they exist only if you have cloned
uxarray with its test data into your own `$HOME`. Nothing in this repository or
in `improv_endpoint.sh` puts them there.

```
/gpfs/fs1/home/<user>/uxarray/test/meshfiles/mpas/QU/480/grid.nc
/gpfs/fs1/home/<user>/uxarray/test/meshfiles/mpas/QU/480/data.nc
/gpfs/fs1/home/<user>/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc
/gpfs/fs1/home/<user>/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_data_subset.nc
```

Use canonical `/gpfs/fs1/home/...` paths — the `/home/...` alias resolves
differently on worker nodes.

## Troubleshooting

**`WorkerLost`** — Python version mismatch causing Dill failure. Run `upgrade-venv`
to rebuild with Python 3.12.

**`ENDPOINT_NOT_ONLINE`** — the PBS `debug` job expired (30-minute walltime).
Restart with `scripts/improv_endpoint.sh restart`.

**`qsub: command not found`** — scheduler binaries missing from worker PATH.
`configure pbs-debug` links `qsub`, `qstat` and `qdel` from `/opt/pbs/bin` into
`~/venvs/globus-compute/bin`; if one is missing, re-run `configure pbs-debug`.

**`validate_hpc_setup` passes but real jobs fail** — worker environment lacks
`uxarray` or its dependencies. Check `pip list` in the venv.
