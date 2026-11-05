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

## If someone else set this up

Endpoints are per-user. A colleague's working Casper endpoint does not give
you one — it runs as *their* account and reads *their* files. You need your
own, and `uxarray-mcp endpoints discover` tells you whether you have it.

Same for the conda env and the YAC build below: they live under a specific
`$USER`, so paths in this page like `/glade/work/$USER/conda-envs/uxarray_dev`
are yours, not shared. Set `NCAR_USERNAME` if your NCAR login differs from
your local `$USER`.

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
pip install globus-compute-endpoint "uxarray[geo,viz]" xarray netCDF4 h5netcdf matplotlib

# The distribution metadata the worker's provenance reads. --no-deps keeps
# the toolregistry/pydantic tree out -- see "Updating the Worker" below.
pip install --no-deps uxarray-mcp

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

## Rebuilding the Worker Env

`pyproject.toml` sets `requires-python = ">=3.12"`, so an env on an older
interpreter is unsupported regardless of whether anything has visibly broken
yet. Observed 2026-11-05 on Casper: the env was on **3.11**, and was stuck at
`uxarray` 2026.10.0 — below this server's own `uxarray[geo,viz]>=2026.10.1`
floor — because 3.11 cannot install 2026.10.1. Nothing errored; pip just
installed the newest release the interpreter qualified for and reported
success.

Check the interpreter, and separately check what pip can actually see:

```bash
/glade/work/$USER/conda-envs/uxarray_dev/bin/python -V
/glade/work/$USER/conda-envs/uxarray_dev/bin/python -m pip index versions uxarray
/glade/work/$USER/conda-envs/uxarray_dev/bin/python -m pip index versions uxarray \
    --ignore-requires-python | head -3
```

The two `index versions` calls are the diagnostic pair, and running only the
first will mislead you. `pip index versions` **hides releases your
interpreter cannot install**, so a floor you cannot reach and a release that
does not exist look identical — both just show an older `LATEST`. Compare
the two outputs: a version that appears only under
`--ignore-requires-python` is being filtered by your Python, while one that
appears under neither is not on PyPI at all and no rebuild will conjure it.
On Casper 2026-11-05, 2026.10.1 appeared only under the second — the
filtered case.

If the interpreter is not 3.12, rebuild. Stop the endpoint first — removing an env out
from under a running worker gets you `WorkerLost` on the next task rather
than a clear error.

```bash
./scripts/ucar_endpoint.sh status          # note whether it is running
globus-compute-endpoint stop ucar-uxarray-yac

module load conda
conda env remove -p /glade/work/$USER/conda-envs/uxarray_dev -y
conda create  -p /glade/work/$USER/conda-envs/uxarray_dev python=3.12 -c conda-forge -y
conda activate /glade/work/$USER/conda-envs/uxarray_dev

pip install globus-compute-endpoint "uxarray[geo,viz]" xarray netCDF4 h5netcdf matplotlib
pip install --no-deps uxarray-mcp

./scripts/ucar_update.sh --dry-run         # confirm versions and layout
./scripts/ucar_endpoint.sh start
```

`configure` is not needed if you rebuilt at the same path — `worker_init`
names the directory, not the interpreter, so `start` is enough. It *is*
needed if you changed `CONDA_ENV`.

Prefer the plain `--no-deps uxarray-mcp` above to an editable install of a
git checkout. An editable install does not refresh its recorded version on
`git pull`, so the distribution metadata drifts from the module: observed on
Casper as `uxarray_mcp 2026.10.1` importing from
`~/uxarray-mcp-server/src/` while the metadata still read `2026.9.0`. Runtime
survives this — the provenance lambda parses `__version__` out of the file
and only falls back to `importlib.metadata` — but the stale `Requires-Dist`
in that metadata is what generates pip resolver conflicts on every later
install.

## Updating the Worker

`restart` changes no versions. It stops the endpoint, removes the pid file and
starts it again — there is no `pip`, no `conda` and no `git` anywhere in
`ucar_endpoint.sh`. What it buys you is that worker processes are *replaced*,
so they re-import whatever is on disk at that moment. Running workers hold the
old modules in memory, which makes a restart necessary after an update and
never sufficient on its own.

```bash
# On a Casper login node, from a plain shell
./scripts/ucar_update.sh --dry-run   # report what would change
./scripts/ucar_update.sh --restart   # update, then bounce the endpoint
```

The script asks the worker's own interpreter where `uxarray` and `uxarray_mcp`
resolve, then pulls the git checkout or upgrades from PyPI accordingly — the
same "do not guess this" approach as `chrysalis_update.sh`, which exists
because updating the clone the worker *wasn't* importing looked like success
and moved nothing.

`uxarray-mcp` is always installed with `--no-deps`, and the reason is worth
knowing before someone "fixes" it. The worker never runs the MCP server:
remote functions are serialised by value and execute against uxarray, numpy
and matplotlib alone, and `worker_init` unsets `PYTHONPATH` to keep the server
off the import path. A full install pulls `toolregistry` and
`toolregistry-server[mcp]`, whose pydantic pins conflict with the endpoint's.
But the distribution cannot be removed either: every `remote_*` function
reports provenance through an inlined `importlib.metadata.version("uxarray-mcp")`
with no fallback, so an absent distribution raises `PackageNotFoundError` and
every tool call fails *after* doing all its work. `--no-deps` is what satisfies
both — the metadata exists, nothing else comes with it.

That stale metadata is also what produces this, if you pip-install by hand
into an env whose `uxarray-mcp` is older than the `uxarray` you are
installing:

```
uxarray-mcp 2026.9.0 requires uxarray<2026.10,>=2026.9.0,
but you have uxarray 2026.10.0 which is incompatible
```

The script avoids it by updating `uxarray-mcp` first, so the pin is current
before `uxarray` moves. `pip check` will always report the two `toolregistry`
packages as missing here; that is the design, not a fault.

Changes to `CONDA_ENV`, `WITH_YAC`, `YAC_VERSION` or `worker_init` are a
different matter — those are baked into `user_config_template.yaml.j2` at
`configure` time, so they need `configure` **then** `restart`.

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

**A conservative remap kills the worker (`WorkerLost`)** — MPI, not memory,
and the two look identical from the outside. Importing YAC calls `MPI_Init`,
which works out whether this process is one rank of many by reading the
environment. A worker started inside a batch job inherits `PMI_FD` from that
job, pointing at a descriptor whose owner has already exited. MPI writes to
it, gets `Bad file descriptor`, and aborts — which reaches you as a lost
worker with nothing mentioning MPI.

The server unsets `PMI_FD`, `PMI_RANK` and `PMI_SIZE` before every YAC-backed
remap, so a current endpoint should not hit this. If you still see it, the
endpoint is probably running an older `uxarray-mcp`; check the version in
`check_remote_yac(endpoint=...)` and redeploy. To fix it at the endpoint
instead, add to `worker_init`:

```bash
unset PMI_FD PMI_RANK PMI_SIZE
```

`conservative_ok: false` from `check_remote_yac` means something else — the
YAC build itself. `./scripts/ucar_endpoint.sh check-mpi` distinguishes the two.

**Do not fix this with an MPI launcher.** `mpiexec -n 1` also makes the import
work, and earlier versions of this page recommended it. At more than one rank
it silently corrupts results: YAC splits the work across ranks, nothing here
gathers it back, and each rank returns its own partition as if it were the
whole field. Measured against a known-correct serial answer of 73344.0, four
ranks gave 56635, 58331, 53862 and 60373 on four consecutive runs — full-length
arrays, no NaNs, no error.

Meanwhile `inverse_distance_weighted` and `bilinear` work — they use uxarray's
own engine. Neither conserves the field integral, which is usually the reason
conservative was asked for, so this is a stopgap and not a fix.
