# UCAR/Casper Endpoint

**Casper** is an NCAR data analysis and visualization cluster at the National
Center for Atmospheric Research (NCAR) Mesa Lab, operated by the CISL
(Computational and Information Systems Laboratory). It provides access to the
GLADE parallel filesystem and is the primary NCAR resource for post-processing
and interactive analysis of climate model output.

- **Location:** NCAR Mesa Lab, Boulder, CO
- **Operator:** CISL/NCAR — <https://arc.ucar.edu>
- **Access:** NCAR allocation required — <https://arc.ucar.edu/knowledge_base/74317833>
- **System page:** <https://arc.ucar.edu/knowledge_base/70549913>
- **Scheduler:** PBS Pro
- **Login:** `ssh <username>@casper.ucar.edu`
- **Storage:** GLADE — `/glade/work/`, `/glade/derecho/scratch/`, `/glade/u/`

## Start here

If you are standing up your own Casper endpoint for the first time, use the
site-agnostic [`scripts/endpoint.sh`](operating-an-endpoint.md) and skip the
rest of this page:

```bash
# On a Casper login node, from a clone of this repo
export CONDA_ENV=uxarray MODULES="ncarenv/24.12 conda"
./scripts/endpoint.sh install
./scripts/endpoint.sh configure
./scripts/endpoint.sh start
```

That gives you every tool except conservative remapping. The rest of this page
describes `scripts/ucar_endpoint.sh`, which is the same thing with NCAR's
verified module list, an optional YAC build, and a fixed profile name.

## Key Points

- **You do need a clone of this repo on Casper**, because the endpoint scripts
  live in it. You do **not** need it importable: remote functions are sent as
  source via `AllCodeStrategies`, and adding `uxarray_mcp` to the worker's
  `PYTHONPATH` breaks it with a pydantic conflict.
- **YAC is optional.** Without it, everything works except
  `method="conservative"` and the `backend="yac"` remap methods, which report
  the missing library rather than failing obscurely.
- `globus-compute-endpoint` runs from the same conda env as the worker; there
  is no separate venv on Casper.
- Worker Python must be 3.12. Globus Compute tolerates patch skew but not
  minor skew, and uxarray-mcp pins 3.12.

## Worker Environment

| Item | Value | Override |
|---|---|---|
| Conda env | `/glade/work/<user>/conda-envs/uxarray_dev` | `CONDA_ENV` |
| NCAR login | `$USER` | `NCAR_USERNAME` |
| Endpoint profile | `ucar-uxarray-yac` | `ENDPOINT_NAME` |
| Modules | `ncarenv/24.12`, `gcc/12.4.0`, `openmpi/5.0.6`, `conda` | — |
| Provider | `LocalProvider` (workers on the login node) | — |
| YAC | off | `WITH_YAC=1` |
| YAC prefix | `~/opt/yac-3.20.2` when `WITH_YAC=1` | `YAC_VERSION` |

The script does **not** create the conda env or the YAC build. Both must exist
first.

## First-Time Setup

```bash
# 1. Build the worker conda env (once)
module load conda
conda create -p /glade/work/$USER/conda-envs/uxarray_dev python=3.12 -c conda-forge -y
conda activate /glade/work/$USER/conda-envs/uxarray_dev
pip install globus-compute-endpoint uxarray xarray netCDF4 h5netcdf matplotlib

# 2. Write the endpoint config
ENDPOINT_NAME=ucar-uxarray ./scripts/ucar_endpoint.sh configure

# 3. Start it
ENDPOINT_NAME=ucar-uxarray ./scripts/ucar_endpoint.sh start
```

The profile name is `ucar-uxarray-yac` by default, and `configure` refuses that
name unless `WITH_YAC=1` — a profile named for YAC that quietly came up without
it would look healthy and be missing conservative remapping. Either pick a name
without `yac` in it, as above, or build YAC first (below).

## Starting the Endpoint

```bash
# From a plain shell on a Casper login node -- NOT from inside tmux
./scripts/ucar_endpoint.sh start
```

The script loads modules, activates the conda env, and starts the endpoint
**inside a tmux session it creates itself**, named `uxarray-endpoint`. Do not
start tmux yourself: if you are already inside a session with a different name,
the script refuses and tells you to detach.

- Reattach: `tmux attach -t uxarray-endpoint`
- Restart: `./scripts/ucar_endpoint.sh restart` (use this, not `start`, on a
  running endpoint — `start` would take it down while reporting success)
- Status: `./scripts/ucar_endpoint.sh status`

The first start opens an OAuth flow. Over ssh, paste the printed URL into a
browser on your laptop and paste the code back. It then prints the endpoint
UUID.

## Registering It

Add the UUID to your private local config on your laptop, never to the
repository:

```bash
uxarray-mcp endpoints add ucar-casper <uuid> --path-prefix /glade/
```

`ucar-casper` here is a **local alias**, independent of the remote profile
name; every later `--endpoint` flag uses the alias. Always register the
`--path-prefix`. Without it this endpoint claims no paths of its own, so
`/glade/...` work falls through to whatever endpoint happens to be the
configured default — quite possibly at another facility.

## Validation

```bash
uxarray-mcp doctor --endpoint ucar-casper --timeout-seconds 120
```

Or against a real GLADE path:

```bash
uxarray-mcp doctor --endpoint ucar-casper \
    --sample-path /glade/work/<user>/your_mesh_file.nc
```

## YAC Remapping (optional)

Only needed for `method="conservative"` and the `backend="yac"` methods.

```bash
# Build it once, into the prefix ucar_endpoint.sh looks for
uv run python scripts/hpc_build_yac.py \
    --endpoint ucar-casper --prefix '~/opt/yac-3.20.2' --yac-version v3.20.2

# Then rebuild the endpoint config with YAC in worker_init and restart
WITH_YAC=1 ./scripts/ucar_endpoint.sh configure
WITH_YAC=1 ./scripts/ucar_endpoint.sh restart

# Verify on the worker, not the login node
uv run python scripts/yac_smoke_test.py --endpoint ucar-casper
```

`worker_init` bakes the YAC prefix in at configure time, so pointing at a new
build (`YAC_VERSION=3.21 ...`) needs `configure` again, then `restart`.

## Moving Files

Globus Compute and Globus Transfer are separate services with separate logins.
A working endpoint does not let you copy files. See
[data-transfer.md](data-transfer.md); NCAR GLADE is in the known-collections
table, so `uxarray-mcp transfer setup --endpoint ucar-casper` finds it without
you pasting a UUID.

## Troubleshooting

**`endpoint not ready` immediately after start** — modules not loaded before
starting. `ucar_endpoint.sh start` loads them; if you started
`globus-compute-endpoint` by hand, run
`module load ncarenv/24.12 gcc/12.4.0 openmpi/5.0.6 conda` first.

**`configure` refuses with "named for YAC but WITH_YAC is 0"** — intentional.
Pass `WITH_YAC=1`, or use a profile name without `yac` in it.

**`no YAC install at ~/opt/yac-<version>`** — `WITH_YAC=1` with nothing built.
Build it with `scripts/hpc_build_yac.py`, or drop `WITH_YAC`.

**YAC import fails on the worker** — the prefix moved. Check `~/opt/` for the
build you have and pass its version as `YAC_VERSION`; the activate file is
synthesized from the prefix, so there is nothing to edit in the script.

**`doctor` passes but YAC tools fail** — run `yac_smoke_test.py`, which checks
importability on the compute worker specifically rather than on the login node.
