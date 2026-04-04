# Improv Playbook

This page captures the exact failure modes we hit while bringing up Argonne
Improv, plus the reusable fixes that now exist in the repository.

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

## Known Non-Blockers

The local SDK may warn about Python version mismatch, for example local Python
3.13 vs remote Python 3.11. That warning did not block successful remote
inspection in our tests.
