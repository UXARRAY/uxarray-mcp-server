# Improv Playbook

This page captures the exact failure modes we hit while bringing up Argonne
Improv, plus the reusable fixes that now exist in the repository.

Official system information for Improv is available from LCRC:
[Improv system page](https://www.lcrc.anl.gov/systems/improv).

If you are new to Globus Compute, read [Globus Compute Primer](globus-compute.md)
first. This page assumes you already understand the difference between:

- the local machine
- the endpoint manager
- the child endpoint
- the remote worker environment

## What Finally Worked

1. Start with a single-host endpoint on one login node only.
2. Authenticate the local Globus client from an interactive terminal.
3. Validate the runtime with `validate_hpc_setup(..., sample_path=...)`.
4. Probe the exact remote path with `probe_path_access(..., use_remote=True)`.
5. Only after those pass, switch to the PBS-backed template.

The repository now includes a helper script for this:

```bash
scripts/improv_endpoint.sh single-host improv-uxarray
scripts/improv_endpoint.sh pbs-debug <allocation> improv-uxarray
```

## Improv-Specific Misses We Hit

### 1. `/home/...` was not the right path for the worker

The worker resolved files from the canonical GPFS filesystem, not the login
alias. A path that looked fine interactively:

```text
/home/<username>/...
```

needed to be rewritten to:

```text
/gpfs/fs1/home/<username>/...
```

Use canonical absolute paths for remote probes and real jobs.

### 2. Endpoint manager `online` was not enough

The manager was healthy while the child endpoint still failed. That is why the
repository now has:

- `validate_hpc_setup()`
- `probe_path_access()`

These are the first commands to run on a new cluster.

### 3. `qsub` was missing from the child endpoint environment

The child endpoint could not find PBS commands until `/opt/pbs/bin` was added
to the environment. The `pbs-debug` mode in `scripts/improv_endpoint.sh` now
does this for you and also creates `qsub`, `qstat`, and `qdel` symlinks inside
the endpoint venv.

### 4. `uxarray` was missing on the remote worker

Remote task execution worked before UXarray-specific tools worked. The worker
needed:

```bash
python -m pip install uxarray xarray netCDF4 h5netcdf
```

Install these in the endpoint venv used by the worker.

### 5. Stale PID files and multiple login nodes caused false starts

We hit:

- stale `daemon.pid`
- "another instance is running"
- child endpoint startup conflicts across multiple login nodes

Run the endpoint from one login node only, ideally inside `tmux`.

## Recommended Improv Sequence

On Improv:

```bash
python3 -m venv ~/venvs/globus-compute
source ~/venvs/globus-compute/bin/activate
python -m pip install -U pip
python -m pip install globus-compute-endpoint globus-compute-sdk
python -m pip install uxarray xarray netCDF4 h5netcdf
globus-compute-endpoint configure improv-uxarray
scripts/improv_endpoint.sh single-host improv-uxarray
globus-compute-endpoint start improv-uxarray
```

On your laptop:

```bash
uv run python scripts/hpc_doctor.py \
  --timeout-seconds 180 \
  --sample-path /gpfs/fs1/home/<username>/path/to/file.nc
```

When that succeeds, switch to PBS mode:

```bash
source ~/venvs/globus-compute/bin/activate
scripts/improv_endpoint.sh pbs-debug <allocation> improv-uxarray
globus-compute-endpoint start improv-uxarray
```

At that point, rerun `validate_hpc_setup` before trying a real UXarray job.

## Worked Example From `jain`

These are real paths and checks that succeeded during the Improv bring-up.

### 1. Prove the remote worker can see one exact file

The first successful remote path probe used the canonical GPFS path:

```bash
uv run python scripts/hpc_doctor.py \
  --timeout-seconds 180 \
  --sample-path /gpfs/fs1/home/jain/WPSV39/20170316_2days/met_em.d01.2017-03-16_00:00:00.nc
```

That confirmed:

- the remote worker could execute code
- the remote worker was running on `ilogin3.lcrc.anl.gov`
- `/gpfs/fs1/home/jain/...` worked where `/home/jain/...` had not

### 2. Run a real UXarray remote inspection

The MPAS sample files that worked were:

```text
/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc
/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_data_subset.nc
```

Local command:

```bash
uv run python -c "from uxarray_mcp.tools.remote_tools import inspect_mesh, inspect_variable; import pprint; grid='/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc'; data='/gpfs/fs1/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_data_subset.nc'; print('=== inspect_mesh ==='); pprint.pp(inspect_mesh(grid, use_remote=True)); print(); print('=== inspect_variable ==='); pprint.pp(inspect_variable(grid, data, use_remote=True))"
```

Remote UXarray inspection returned:

- `n_face = 195`
- `n_node = 442`
- `n_edge = 636`
- variables:
  - `face_lat`
  - `face_lon`
  - `gaussian`
  - `inverse_gaussian`

### 3. What this example demonstrates

This sequence proved the full path in the right order:

1. local Globus client auth worked
2. endpoint manager was healthy
3. remote worker execution worked
4. canonical GPFS file paths worked
5. UXarray imports were available remotely
6. remote mesh and variable inspection worked

## Known Non-Blockers

The local SDK may warn about Python version mismatch, for example local Python
3.13 vs remote Python 3.11. That warning did not block successful remote
inspection in our tests.
