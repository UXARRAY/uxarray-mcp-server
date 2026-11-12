# HPC: running tools where the data lives

Your data is on a cluster. The server sends a function to that cluster through
Globus Compute and a result comes back; nothing is copied.

## 1. How remote execution works

Every remote call ships one function, `run_op` in
`src/uxarray_mcp/remote/shim.py`, through Globus Compute with
`AllCodeStrategies` (source is serialised, not a reference). On the worker,
`run_op` does `from uxarray_mcp.core import ops` and calls
`ops.call(name, **kwargs)`. `core/` is the only place science lives, so the
worker environment needs `uxarray[geo,viz]` (the extras are required),
`netCDF4`, `h5netcdf`, `globus-compute-endpoint`, and `uxarray-mcp` installed
with `--no-deps` so `uxarray_mcp.core` is importable without the server's
`mcp` / `toolregistry` / `pydantic` tree landing beside the endpoint
(section 5).

Submitter and worker should run the same Python minor version (3.12). Globus
Compute tolerates patch skew but not minor skew; a mismatch passes toy
payloads and fails real ones as `WorkerLost`. The worker probe reports the
worker's Python so you can compare.

A tool whose path does not exist locally is sent to the endpoint whose
`path_prefixes` claims it (section 4); `use_remote=True` plus `endpoint=`
forces it. Results carry `_provenance.venue: "hpc:<name>"` and a
`_provenance.remote` block with hostname, job id, worker versions and timing.

Every remote call mints an `operation_id` before submitting. If the caller's
timeout (default 1800 s) expires first, the tool returns
`{"status": "running", "operation_id": ...}` and the task keeps running; call
`get_operation(operation_id=..., wait_seconds=...)` to collect it. Failures
come back as one typed `error_code`, not a worker traceback:
`ENDPOINT_OFFLINE` (manager not registered), `NO_WORKER` (registered, but the
scheduler allocation expired; retry in a minute), `WORKER_LOST` (worker died
mid-task: memory, or MPI, section 7), `FILE_NOT_FOUND_ON_WORKER`,
`WORKER_MISSING_PACKAGE` (worker cannot import `uxarray_mcp` or `uxarray`),
`REMOTE_FAILED` (anything else, with the traceback's last line) and
`TIMEOUT_EXPIRED` (a probe got no answer). Section 8 maps each to a fix.
Version drift between your `uxarray` / `uxarray-mcp` and the worker's is
added to `warnings` on the result, once per process per endpoint.

## 2. Prerequisites

- **A Globus identity** from <https://app.globus.org>, signed in with the
  institution that holds your HPC login. A personal Google identity
  authenticates fine and then sees none of your endpoints, which looks exactly
  like a dead endpoint; link identities at
  <https://app.globus.org/account/identities>. Only Globus Auth and Compute
  are used. The first Globus command opens a browser; over ssh it prints a URL.
- **A site account** with shell access and data you can read. An endpoint is
  per-user, not per-machine: it runs as your account and reads what you can
  read. A colleague's working endpoint tells you nothing about yours.
- **Scheduler knowledge**: the Slurm account or PBS project to charge, the
  partition or queue, and the site's conda or module convention.
- **The HPC extra** on your laptop:
  `uv tool install --python 3.12 --extra hpc uxarray-mcp`.

**Security.** An endpoint is shell-equivalent access as your HPC user for
anyone who can submit to it, including a stolen refresh token from your
laptop, and its operator sees the functions and paths you submit. Run
`chmod 700 ~/.globus_compute ~/.globus`, submit nothing you would not put in
a ticket, and read [SECURITY.md](https://github.com/UXARRAY/uxarray-mcp-server/blob/main/SECURITY.md)
before sharing an endpoint.

## 3. Set up a personal endpoint with `scripts/endpoint.sh`

`scripts/endpoint.sh` is site-agnostic: everything that differs between
machines is an environment variable with a login-node default. Clone the repo
on the HPC machine (the scripts live there) and, from a plain shell:

```bash
export CONDA_ENV=uxarray            # or VENV=~/venvs/uxarray
export MODULES="conda"              # whatever your site needs, in order

./scripts/endpoint.sh install       # create the env, install the worker packages
./scripts/endpoint.sh check         # report what is ready; changes nothing
./scripts/endpoint.sh configure     # write ~/.globus_compute/uxarray/config.yaml
./scripts/endpoint.sh start         # starts inside tmux, prints the UUID on first run
./scripts/endpoint.sh uuid          # print the UUID again later
```

`install` runs `pip install "uxarray[geo,viz]" netCDF4 h5netcdf
globus-compute-endpoint` then `pip install --no-deps uxarray-mcp`.
`configure` writes a `LocalProvider` config whose `worker_init` starts with
`unset PYTHONPATH` (so the login node's site-packages cannot shadow the
worker's), then loads `MODULES` and activates the env. `start` creates its own
tmux session, `uxarray-endpoint`; run it from outside tmux. The first start
runs an OAuth flow and prints the UUID. `start` against a profile that is
already Running would stop it while reporting success, so the script refuses
and tells you to use `restart`.

Once the login-node round trip works, move the workers onto the scheduler:

```bash
SCHEDULER=slurm ACCOUNT=myproject QUEUE=debug ./scripts/endpoint.sh configure   # or SCHEDULER=pbs
./scripts/endpoint.sh restart
```

`./scripts/endpoint.sh` with no argument lists every override (`WALLTIME`,
`MAX_BLOCKS`, `AMQP_PORT=443` where the site firewalls 5671,
`WORKER_INIT_EXTRA` for a YAC activate file or `LD_LIBRARY_PATH`).
`worker_init` is written at `configure` time, so changing any of these means
`configure` then `restart`. Under a scheduler the worker ends with its batch
job and the endpoint stays registered with nothing to run on (`NO_WORKER`).

**Shared endpoints.** A single-user endpoint runs only what the identity that
started it submits. If others will submit, request a service account from
your site, add a Globus Auth `authentication_policy` (one UUID as a flat
top-level key, never a nested block) and consider a multi-user endpoint with a
function allowlist; the Globus Compute endpoint docs cover that.

## 4. Register it on your laptop

```bash
uxarray-mcp endpoints discover                 # UUIDs your identity can see, with ready-made add lines
uxarray-mcp endpoints add chrysalis <uuid> --path-prefix /lcrc/ --set-default
uxarray-mcp endpoints list
uxarray-mcp doctor --endpoint chrysalis        # submits a real probe
uxarray-mcp doctor --endpoint chrysalis --sample-path /lcrc/group/e3sm/$USER/grid.nc
```

The name is a local alias and need not match the profile name on the cluster.
`--path-prefix` is routing: paths starting with it belong to this endpoint,
so tools route there without `use_remote`. Give every endpoint one; clusters
share mount names (Improv and Chrysalis both expose `/home/`), so an endpoint
with no prefix never wins a match and its work goes to the default instead.
Common prefixes: `/lcrc/` (Chrysalis), `/glade/` (NCAR), `/gpfs/fs1/` and
`/home/` (Improv), `/pscratch/`, `/global/` (NERSC).

`doctor` is `endpoint(action="validate")` from the shell: manager state, a
worker probe (node, Python, uxarray and uxarray-mcp versions, round trip) and,
with `--sample-path`, a header read of that file on the worker. "Registered"
is only the manager phoning home; the probe is the real test, and cold it can
take a minute on a scheduler-backed endpoint. The config is
`~/.config/uxarray-mcp/config.yaml` (`$UXARRAY_MCP_CONFIG` overrides it; a
`./config.yaml` in the working directory wins over both). `endpoints add`
writes it; a minimal file, with the optional `provider` key:

```yaml
hpc:
  execution_mode: auto
  default_endpoint: chrysalis
  endpoints:
    chrysalis:
      endpoint_id: 3cca8be6-55ec-4386-b7fd-f6c1e161d52b
      path_prefixes: [/lcrc/]
      provider: slurm          # optional: slurm | pbs | local
      timeout_seconds: 1800    # optional; the default
```

The UUID is not a secret but do not post it publicly; the file is in `.gitignore`.

## 5. Keeping the worker current

The worker's environment is updated separately from your laptop and is
routinely behind. When versions differ, results carry a warning such as
`uxarray-mcp version drift on chrysalis: local 2026.10.1, worker 2026.9.0`,
once per process. Act on it: a fix released on your side is absent on the
cluster until the worker moves.

```bash
# in the worker env on the cluster
pip install --no-deps --upgrade uxarray-mcp && pip install --upgrade "uxarray[geo,viz]"
./scripts/endpoint.sh restart          # or the site script's restart
```

The restart is not optional: running workers hold the old modules in memory,
so an install alone changes nothing until the processes are replaced; and
`restart` alone changes no versions. Before updating, check where the worker
imports from: an editable install or a `PYTHONPATH` entry beats site-packages,
and upgrading the latter then moves nothing. `chrysalis_update.sh` and
`ucar_update.sh` ask the worker's interpreter rather than guessing.

**Why `--no-deps`.** The worker only needs `uxarray_mcp.core`, which imports
uxarray, numpy and matplotlib. A full `pip install uxarray-mcp` also pulls
`mcp`, `toolregistry` and `toolregistry-server[mcp]`, whose pydantic pins
conflict with the pydantic that `globus-compute-endpoint` needs, and the
endpoint stops importing. The package cannot be left out either: the shim
imports it. `--no-deps` satisfies both, so `pip check` will always list the
toolregistry packages as missing on a worker; that is by design. Update
`uxarray-mcp` before `uxarray`, or pip reports a conflict against the stale
`uxarray<...` pin an old `uxarray-mcp` carries.

## 6. Site notes

### Chrysalis (ANL LCRC, Slurm)

Login `ssh <user>@chrysalis.lcrc.anl.gov`; 128-core, 256 GB nodes; data under
`/lcrc/group/`. Login nodes kill heavy processes, so use the Slurm mode for
anything real. Scripts: `chrysalis_endpoint.sh`, `chrysalis_update.sh`.

| Item | Default | Override |
|---|---|---|
| Profile name | `uxarray-chrysalis` | `ENDPOINT_NAME` |
| Worker conda env (Python 3.12) | `~/.conda/envs/uxarray-yac` | fixed |
| Endpoint helper venv | `~/venvs/globus-compute-py313` | `VENV_GC` |
| conda module | `miniforge3` | `CHRYSALIS_CONDA_MODULE` |
| YAC prefix | `~/local/yac-3.20.2` | `YAC_VERSION` |
| uxarray checkout on worker `PYTHONPATH` | `/lcrc/group/e3sm/$USER/uxarray-yac-src` | `UXARRAY_YAC_SRC` |
| `check-yac` script dir (`/tmp` is node-local) | `~/.cache/uxarray-mcp` | `YAC_SMOKE_DIR` |

```bash
bash scripts/chrysalis_endpoint.sh configure slurm-debug   # partition compute, 1 node/block, 2 blocks, 1h, SrunLauncher
bash scripts/chrysalis_endpoint.sh start                    # tmux session uxarray-endpoint
bash scripts/chrysalis_endpoint.sh status | logs | restart
bash scripts/chrysalis_endpoint.sh check-yac                # srun --ntasks 1 import + remap smoke
```

`configure single-host` (the default) is a `LocalProvider` template for a
quick probe. The script assumes the conda env, helper venv and YAC build exist
and writes the YAC `LD_LIBRARY_PATH` plus BLAS/LAPACK shims under
`~/local/yac-runtime-shims/lib`. `worker_init` bakes the YAC prefix in, so a
new `YAC_VERSION` or `UXARRAY_YAC_SRC` needs `configure <mode>` then
`restart`; `status` warns when the template disagrees with the script.
Register as `uxarray-mcp endpoints add chrysalis <uuid> --path-prefix /lcrc/`.

- **Two clones.** `/home/$USER/uxarray-mcp-server` and
  `/lcrc/group/e3sm/$USER/uxarray-mcp-server` both exist; the conda env's
  editable install points at one and that is the only one the worker imports.
  Pulling the other looks like success and changes nothing.
  `chrysalis_update.sh` resolves the imported checkout with
  `importlib.util.find_spec`, pulls it and `uxarray-yac-src`, refuses dirty
  checkouts, prints the versions the worker will import, and with `--restart`
  bounces the endpoint. Install a checkout with `pip install --no-deps -e .`.
- **`$HOME` shadowing.** A stale `~/uxarray` checkout on the worker's path
  shadows the installed package; `start` imports uxarray first and refuses if
  that fails. `uxarray-yac-src` tracks a feature branch, so `git pull` there
  never brings in a newer release.
- **YAC env.** The worker's `PYTHONPATH` is set, not unset, here: it names the
  YAC site-packages and `UXARRAY_YAC_SRC`. `libnetcdf.so.22`, `liblapack.so.3`,
  `libblas.so.3` or `pydantic_core` not found: re-run `configure`, then `check-yac`.

### Improv (ANL LCRC, PBS Pro)

Login `ssh <user>@improv.lcrc.anl.gov`; 128-core, 256 GB nodes; data under
`/gpfs/fs1/`. Script: `scripts/improv_endpoint.sh` (profile `improv-uxarray`,
override `ENDPOINT_NAME`; worker venv `~/venvs/globus-compute`; `PYTHON`
defaults to `/usr/bin/python3.12`). No update script; `upgrade-venv` rebuilds
the venv.

```bash
scripts/improv_endpoint.sh upgrade-venv                              # rebuild venv on 3.12 (old one moved to ~/venvs/globus-compute-3.11-backup)
source ~/venvs/globus-compute/bin/activate && globus-compute-endpoint configure improv-uxarray
scripts/improv_endpoint.sh configure single-host [name]              # LocalProvider, first validation
scripts/improv_endpoint.sh configure pbs-debug <project> [name]      # queue debug, 1 node, 1 block, 00:30:00, MpiExecLauncher, ib0
scripts/improv_endpoint.sh start | restart | status
```

`upgrade-venv` refuses any interpreter that is not 3.12 and installs
`globus-compute-endpoint>=4.9.0`, `uxarray[geo,viz]`, netCDF4, h5netcdf and
`uxarray-mcp --no-deps`. `configure pbs-debug` links `qsub`, `qstat` and
`qdel` from `/opt/pbs/bin` into the venv's `bin`. Name remote files by the
canonical `/gpfs/fs1/home/<user>/...` path, not `/home/<user>/...`, which
resolves differently on worker nodes. Register both mounts:
`uxarray-mcp endpoints add improv <uuid> --path-prefix /gpfs/fs1/ --path-prefix /home/`.
The `debug` job's 30-minute walltime is why `NO_WORKER` appears after idling.

### Casper (NCAR, PBS Pro)

Login `ssh <user>@casper.ucar.edu`; GLADE under `/glade/`. Script:
`scripts/ucar_endpoint.sh`; update: `scripts/ucar_update.sh`.
`globus-compute-endpoint` runs from the same conda env as the worker; workers
run on the login node (`LocalProvider`). Modules: `ncarenv/24.12 gcc/12.4.0
openmpi/5.0.6 conda`.

| Item | Default | Override |
|---|---|---|
| Profile name | `ucar-uxarray-yac` | `ENDPOINT_NAME` |
| Worker conda env (Python 3.12) | `/glade/work/$USER/conda-envs/uxarray_312` | `CONDA_ENV` (`NCAR_USERNAME` if `$USER` differs) |
| YAC | off | `WITH_YAC=1`, prefix `~/opt/yac-$YAC_VERSION` (3.20.2) |

```bash
module load conda && conda create -p /glade/work/$USER/conda-envs/uxarray_312 python=3.12 -c conda-forge -y
conda activate /glade/work/$USER/conda-envs/uxarray_312
pip install "uxarray[geo,viz]" netCDF4 h5netcdf globus-compute-endpoint && pip install --no-deps uxarray-mcp

ENDPOINT_NAME=ucar-uxarray ./scripts/ucar_endpoint.sh configure   # refuses a *yac* name unless WITH_YAC=1
ENDPOINT_NAME=ucar-uxarray ./scripts/ucar_endpoint.sh start
./scripts/ucar_endpoint.sh restart | status | check-mpi
./scripts/ucar_update.sh --dry-run        # where uxarray / uxarray_mcp resolve, what would change
./scripts/ucar_update.sh --restart        # update (uxarray-mcp --no-deps first), then bounce
```

- `worker_init` (which unsets `PYTHONPATH` and `PMI_FD PMI_RANK PMI_SIZE`) is
  baked at `configure` time, so a change to `CONDA_ENV`, `WITH_YAC` or
  `YAC_VERSION` needs `configure` then `restart`. Rebuilding the env at the
  same path needs only `restart`.
- `start` on a running endpoint takes it down while reporting success; the
  script refuses, use `restart`. `restart` replaces worker processes and
  changes no versions. Stop the endpoint before removing its env, or the next
  task is `WORKER_LOST` instead of a clear error. Starting
  `globus-compute-endpoint` by hand without the modules gives `endpoint not ready`.
- If pip keeps "succeeding" at an old uxarray, the interpreter is filtering
  releases. Compare `python -m pip index versions uxarray` with the same
  command plus `--ignore-requires-python`: a version that appears only in the
  second is blocked by your Python (rebuild on 3.12); one in neither is not on
  PyPI. Observed 2026-11-05: a 3.11 env stuck at 2026.10.0 because 2026.10.1
  requires 3.12.
- Register as `uxarray-mcp endpoints add ucar <uuid> --path-prefix /glade/`.

## 7. YAC / conservative remapping (optional)

YAC buys `remap(method="conservative")` and the other `backend="yac"`
methods and nothing else; nearest-neighbour, IDW and bilinear use uxarray's
own engine, and without YAC the YAC methods report the missing library.
`endpoint(action="check_yac", endpoint=...)` returns
`conservative_remap_available`.

```bash
uv run python scripts/hpc_build_yac.py --endpoint ucar --prefix '~/opt/yac-3.20.2' --yac-version v3.20.2
WITH_YAC=1 ./scripts/ucar_endpoint.sh configure && WITH_YAC=1 ./scripts/ucar_endpoint.sh restart
```

`hpc_build_yac.py` builds YAXT, YAC and the Python bindings on the worker
(`--mpi-root`/`--gcc-lib` for spack sites, `--module-loads` for Lmod sites,
`--venv-python` for the interpreter) and verifies the files landed without
importing `yac`. `endpoint(action="check_yac", endpoint=...)` then runs a real
conservative remap (HEALPix 2 → 1 of a unit field; the result must be 1
everywhere) on the compute worker, not the login node, and reports
`max_abs_error`. `chrysalis_endpoint.sh check-yac` does the same under `srun`.

**Why a conservative remap can kill the worker.** Importing YAC calls
`MPI_Init`, which reads the environment to decide whether it is one rank of
many. A worker started inside a batch job inherits `PMI_FD` from that job,
pointing at a descriptor whose owner has exited; MPI writes to it, gets `Bad
file descriptor` and aborts. That reaches you as `WORKER_LOST` with nothing
mentioning MPI, indistinguishable from an out-of-memory kill. Dropping the
variables one at a time on Chrysalis showed `PMI_FD` alone is the trigger. The
shim unsets `PMI_FD`, `PMI_RANK` and `PMI_SIZE` before anything imports YAC,
and the site scripts do the same in `worker_init` for older clients;
`ucar_endpoint.sh check-mpi` tells a PMI failure from a broken build.

**Never fix this with a launcher.** `mpiexec -n 1` also makes the import
work, but at more than one rank YAC splits the work across ranks and nothing
gathers it back; each rank returns its own partition as the whole field,
full-length, no NaNs, no error. Against a known-correct serial answer of
73344.0, four ranks returned 56635, 58331, 53862 and 60373 on consecutive runs.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ENDPOINT_OFFLINE` / status `offline` | Daemon not running on the cluster | `<script> start` (or `restart`); `globus-compute-endpoint list` there |
| `NO_WORKER` (`ENDPOINT_NOT_ONLINE`, `did not signal readiness`) | Scheduler allocation ended; manager still registered | Retry in a minute. Persisting: `<script> restart`. The raw message blaming `user_endpoint_config` is a red herring on a single-user endpoint |
| `TIMEOUT_EXPIRED` on probe | No node granted yet, or worker env broken | Wait; `--timeout-seconds 180`; check `squeue`/`qstat` and `chrysalis_endpoint.sh logs` |
| `WORKER_LOST` on a conservative remap | Stale `PMI_FD` (section 7) | Update the worker `uxarray-mcp`; add `unset PMI_FD PMI_RANK PMI_SIZE` to `worker_init` |
| `WORKER_LOST` on anything else | Node memory, or submitter/worker Python minor mismatch | Subset first; rebuild the worker on 3.12 (`improv_endpoint.sh upgrade-venv`) |
| `WORKER_MISSING_PACKAGE` | Worker env lacks `uxarray` or `uxarray-mcp` | `pip install "uxarray[geo,viz]"` and `pip install --no-deps uxarray-mcp` in the worker env, then restart |
| `FILE_NOT_FOUND_ON_WORKER` | Alias path, or file not where the worker looks | `readlink -f` on the cluster; use `/gpfs/fs1/home/...` on Improv; `endpoint(action="probe_path")` |
| `REMOTE_FAILED: ... Failed to parse uxgrid information` | The `.nc` is forcing/initial-condition data, not a mesh | Point `grid_path` at the mesh file |
| `status: running` with an `operation_id` | Call outlived the timeout; task still running | `get_operation(operation_id=..., wait_seconds=60)` |
| `NOT_CONFIGURED` | No endpoint in config and none passed | `uxarray-mcp endpoints add <name> <uuid> --path-prefix /...` |
| Version drift warning, or old code after an update | Running workers hold old modules; or you updated the clone the worker does not import | Section 5; restart; `chrysalis_update.sh` / `ucar_update.sh --dry-run` show the imported path |
| Work routed to the wrong cluster | Endpoint registered without `--path-prefix` | Add prefixes; check `uxarray-mcp endpoints list` |
| Login loop / no endpoints visible | Wrong Globus identity | Sign in with the institutional identity or link it |
| `pydantic` errors at endpoint start | Full `uxarray-mcp` dependency tree in the worker env, or `PYTHONPATH` leaking in | Reinstall `--no-deps`; keep `unset PYTHONPATH` in `worker_init` |
| `conservative_remap_available: false` with YAC built | Prefix not in `worker_init`, or build broken | `configure` with the YAC vars, `restart`, then `endpoint(action="check_yac")` |
