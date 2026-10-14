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

- The **MCP server must be cloned on Chrysalis** — the endpoint scripts live in
  it — but it must never be importable by the worker. Remote functions are sent
  as source code via `AllCodeStrategies` and only need `uxarray` + deps in the
  worker environment; adding `uxarray_mcp` to the worker's `PYTHONPATH` drags in
  a pydantic that conflicts with the one `globus-compute-endpoint` wants.
- Login nodes **kill compute processes** — always use the Slurm backend.
- YAC remapping needs the Python 3.12 `uxarray-yac` environment plus YAC, MKL,
  MPICH, NetCDF, and local shim library paths. Use
  `scripts/chrysalis_endpoint.sh` instead of hand-writing those paths.
- **YAC is optional.** Without it everything works except `method="conservative"`
  and the other `backend="yac"` remap methods, which report the missing library
  rather than failing obscurely.
- If a remote probe times out after the endpoint is `registered`, inspect the
  endpoint logs on Chrysalis with `scripts/chrysalis_endpoint.sh logs`.
- `scripts/endpoint.sh` is the site-agnostic version of this script — start
  there if you are standing up your first endpoint on some other machine.
- Copying files is Globus Transfer, a separate service with its own login — see
  [Moving Files](data-transfer.md).

## Worker Environment

| Item | Value |
|---|---|
| UXarray/YAC env | `~/.conda/envs/uxarray-yac` (Python 3.12) |
| Endpoint helper venv | `~/venvs/globus-compute-py313` |
| Slurm partition | `compute` (1h walltime, 1 node per block, 2 blocks) |
| Compute nodes | 251 GB RAM, 128 CPUs |
| Endpoint name | `uxarray-chrysalis` |

## Keeping the Worker Current

The worker does **not** get `uxarray` or `uxarray-mcp` from the conda
environment's own site-packages. Both resolve to git checkouts:

| Package | Comes from | How |
|---|---|---|
| `uxarray` | `/lcrc/group/e3sm/$USER/uxarray-yac-src` | on the worker `PYTHONPATH` |
| `uxarray-mcp` | `/home/$USER/uxarray-mcp-server` | **editable install** in the conda env |

> **There are two `uxarray-mcp` clones on this machine.** One under
> `/home/$USER` and one under `/lcrc/group/e3sm/$USER`. The conda environment
> carries an *editable* install pointing at the `/home` one, so that is the
> only one the worker ever imports. Pulling the other changes nothing while
> appearing to succeed — the login node reports the new version and every
> task keeps running the old one. `chrysalis_update.sh` resolves the imported
> path with `importlib.util.find_spec` rather than guessing, and warns when a
> second clone exists.

> **`uxarray-yac-src` tracks a feature branch**, not `main` — it carries YAC
> work that is not in a release yet. `git pull` follows that branch, so it
> will not bring in a newer `uxarray` release. Moving that checkout to a
> release is a deliberate decision about whether the unreleased YAC support
> is still needed, not routine maintenance.

So `conda update` does nothing for either, and a release merged on your
laptop is simply absent from the cluster until the right checkout is pulled.
When they drift, every remote call carries a warning:

```
UXarray version drift: local=2026.9.1, remote(worker)=2026.9.0.
uxarray-mcp version drift: local=2026.9.1, remote(worker)=2026.9.0.
```

That warning is the symptom to act on — a fix that is merged, released and
green locally can be missing on the worker, and the operation keeps failing
with nothing to explain why.

On a Chrysalis login node:

```bash
cd /lcrc/group/e3sm/$USER/uxarray-mcp-server
git pull --ff-only
./scripts/chrysalis_update.sh --restart
```

`chrysalis_update.sh` pulls both checkouts, prints the versions the worker
will import, and restarts the endpoint. The restart matters: **running
workers hold the old modules in memory**, so a pull on its own changes
nothing until the processes are replaced. It refuses to pull a checkout with
uncommitted changes rather than clobbering someone's work in progress.

Confirm from your laptop afterwards — the drift warnings should be gone:

```bash
uxarray-mcp doctor --endpoint chrysalis | \
  python -c "import json,sys; print(json.load(sys.stdin)['remote_probe']['_worker_runtime'])"
```

## First-Time Setup

The script assumes four things exist that it does not create for you: the conda
environment `$HOME/.conda/envs/uxarray-yac`, the endpoint helper venv
`$HOME/venvs/globus-compute-py313`, a YAC install at `$HOME/local/yac-$YAC_VERSION`
(default `3.20.2`), and a uxarray-with-YAC checkout, which now defaults to
`/lcrc/group/e3sm/$USER/uxarray-yac-src` and is overridable with
`UXARRAY_YAC_SRC`. Only the last is genuinely optional — a `UXARRAY_YAC_SRC`
path that does not exist is simply ignored by Python.

The checked-in helper script writes the endpoint profile, YAC runtime library
paths, and small BLAS/LAPACK shims needed by the current YAC build:

```bash
git clone https://github.com/UXARRAY/uxarray-mcp-server.git
cd uxarray-mcp-server
bash scripts/chrysalis_endpoint.sh configure slurm-debug
bash scripts/chrysalis_endpoint.sh check-yac
```

The `check-yac` command imports `yac.core`, imports UXarray's YAC helper, and
remaps HEALPix zoom 2 to zoom 3. It runs the smoke script under `srun --ntasks 1`
straight from the login shell, naming no partition or account, so it depends on
site defaults or on an allocation you already hold. It should report
`yac_core_ok: true` and `remap_ok: true` before the endpoint is used by MCP.

## Script Options

Beyond `configure`, `start`, `restart`, `check-yac` and `logs`, the script takes
`status`, which activates the environment and prints `globus-compute-endpoint
list`. `configure` takes a second mode, `single-host`, which is what you get if
you name no mode at all: a `LocalProvider` template that runs workers on the
login node — fine for a quick probe, killed by the site for anything real.

Everything site-specific is an environment variable with a working default:

| Variable | Default | What it moves |
|---|---|---|
| `ENDPOINT_NAME` | `uxarray-chrysalis` | Globus Compute endpoint profile name |
| `CHRYSALIS_CONDA_MODULE` | `miniforge3` | Module that puts `conda` on `PATH` |
| `VENV_GC` | `$HOME/venvs/globus-compute-py313` | Endpoint helper venv |
| `YAC_VERSION` | `3.20.2` | Selects `$HOME/local/yac-$YAC_VERSION` |
| `UXARRAY_YAC_SRC` | `/lcrc/group/e3sm/$USER/uxarray-yac-src` | uxarray checkout put on the worker's `PYTHONPATH` ahead of the installed package |
| `YAC_SMOKE_DIR` | `$HOME/.cache/uxarray-mcp` | Where `check-yac` writes its smoke script; must be on a filesystem the compute node can read, which rules out `/tmp` here |

`worker_init` bakes the YAC prefix in at configure time, so changing
`YAC_VERSION` or `UXARRAY_YAC_SRC` means `configure <mode>` again, then
`restart`.

## Starting the Endpoint

Run this every time you log in, from a plain shell:

```bash
bash scripts/chrysalis_endpoint.sh start
```

`start` creates its own tmux session named `uxarray-endpoint`. If you are
already inside a tmux session with some other name it refuses to run, rather
than leave the endpoint owned by whatever shell happened to be attached —
detach with `Ctrl-b d` first.

The endpoint prints its UUID. Add it to your private local config on your
laptop/workstation, never to the repository:

```bash
# On your laptop:
uxarray-mcp endpoints add chrysalis <uuid> --path-prefix /lcrc/
```

The remote profile name (`uxarray-chrysalis`) and the local alias (`chrysalis`)
are separate namespaces — the local one is just what you type to refer to this
endpoint, and it need not match.

Always register the `--path-prefix`. Without it this endpoint claims no paths
of its own, so it only ever gets work as the fallback default — and any path
another endpoint claims (Improv also mounts `/home/`) silently routes there
instead, even when the file is really on Chrysalis.

## Validation

From your laptop after the endpoint is running:

```bash
uxarray-mcp doctor --endpoint chrysalis --timeout-seconds 120
uv run --extra hpc python scripts/yac_smoke_test.py \
  --endpoint chrysalis --timeout-seconds 300
```

Or manually through the Python API:

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

## E3SM Ocean Meshes

Use the curated input-data tree, which is stable:

```
/lcrc/group/e3sm/data/inputdata/ocn/mpas-o/<mesh-name>/
```

Verified loadable with `ux.open_grid` on a Chrysalis worker:

| Path (under the base above) | Faces | Size |
|---|---|---|
| `IcoswISC240E3r8/ocean.IcoswISC240E3r8.nomask.scrip.20240806.nc` | 7,302 | 0.9 MB |
| `IcoswISC240E3r8/mpaso.IcoswISC240E3r8.20240806.nc` | 7,302 | 26 MB |
| `IcosXISC30E3r7/mpaso.IcosXISC30E3r7.20240314.nc` | 463,013 | 3.9 GB |

Do not point at a personal scratch tree such as
`/lcrc/group/e3sm/ac.<user>/polaris_1.0/...` for *mesh data*. Those hold per-run
`test_<YYYYMMDD>` directories that are rotated and deleted, so a path that
worked last month will simply be gone. The endpoint script's own
`/lcrc/group/e3sm/$USER/uxarray-yac-src` default is not an exception to this —
it is a source checkout you make and keep, not model output somebody else
rotates, and `UXARRAY_YAC_SRC` moves it if you keep yours elsewhere. Not every
`.nc` file in these directories is a mesh — forcing and initial-condition files raise
`RuntimeError: Failed to parse uxgrid information`. Probe first:

```python
diagnose_endpoint(action="probe_path", file_path="<path>", endpoint="chrysalis")
```

## Troubleshooting

**`ENDPOINT_NOT_ONLINE`** — no worker was available to take the task. After
an idle period this is usually just a cold allocation: the Slurm job ended
(1h walltime) and the scheduler has not granted a new one yet. The first
call after idling can take a minute to land, and a retry often succeeds on a
fresh job id without touching anything.

Note that `endpoint_status` reports `registered` and Globus reports `online`
throughout, because registration is all that API call can see — neither says
a worker exists. A submit is the only real test. If retrying keeps failing,
the job is genuinely gone: restart with
`bash scripts/chrysalis_endpoint.sh restart`.

The raw Globus message blames `user_endpoint_config`; on a single-user
endpoint that is a red herring, which is why the server rewrites it.

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
