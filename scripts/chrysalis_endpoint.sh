#!/usr/bin/env bash
# Run on Chrysalis (ANL/LCRC) to configure or start the Globus Compute endpoint.
set -euo pipefail

# ---------------------------------------------------------------------------
# USER CONFIG — change these to match your account before running
# ---------------------------------------------------------------------------
USERNAME="jain"   # your Chrysalis username
# ---------------------------------------------------------------------------

ENDPOINT_NAME="${ENDPOINT_NAME:-uxarray-chrysalis}"
CONDA_ENV="$HOME/.conda/envs/uxarray-yac"
VENV_GC="${VENV_GC:-$HOME/venvs/globus-compute-py313}"
TMUX_SESSION="uxarray-endpoint"

YAC_SHIM_LIB="$HOME/local/yac-runtime-shims/lib"
YAC_SRC_PY="$HOME/src/yac/build/python"
YAC_SRC_CORE="$HOME/src/yac/build/src/core"
YAC_SRC_UTILS="$HOME/src/yac/build/src/utils"
YAC_LOCAL_PREFIX="$HOME/local/yac-3.17"
UXARRAY_YAC_SRC="/lcrc/group/e3sm/jain/uxarray-yac-src"
MKL_LIB="/gpfs/fs1/soft/chrysalis/spack-latest/opt/spack/linux-rhel8-x86_64/oneapi-2022.1.0/intel-oneapi-mkl-2022.1.0-iwhfz52/mkl/2022.1.0/lib/intel64"
MPICH_LIB="/gpfs/fs1/soft/chrysalis/spack-latest/opt/spack/linux-rhel8-x86_64/gcc-11.3.0/mpich-4.3.2-dp2ycaq/lib"
HWLOC_LIB="/gpfs/fs1/soft/chrysalis/spack-latest/opt/spack/linux-rhel8-x86_64/gcc-11.3.0/hwloc-2.12.2-5vqrpw7/lib"
YAKSA_LIB="/gpfs/fs1/soft/chrysalis/spack-latest/opt/spack/linux-rhel8-x86_64/gcc-11.3.0/yaksa-0.4-mejnfxw/lib"
LIBFABRIC_LIB="/gpfs/fs1/soft/chrysalis/spack-latest/opt/spack/linux-rhel8-x86_64/gcc-9.3.0/libfabric-1.16.1-vwdeh3y/lib"
GCC_LIB="/gpfs/fs1/soft/chrysalis/spack-latest/opt/spack/linux-rhel8-x86_64/gcc-8.5.0/gcc-11.3.0-jkpmtgq/lib64"
YAC_PYTHONPATH="$YAC_SRC_PY:$YAC_LOCAL_PREFIX/lib/python3.12/site-packages:$UXARRAY_YAC_SRC"
YAC_LD_LIBRARY_PATH="$YAC_SHIM_LIB:$MKL_LIB:$CONDA_ENV/lib:$YAC_SRC_CORE:$YAC_SRC_UTILS:$YAC_LOCAL_PREFIX/lib:$MPICH_LIB:$HWLOC_LIB:$YAKSA_LIB:$LIBFABRIC_LIB:$GCC_LIB"
YAC_WORKER_PATH="$CONDA_ENV/bin:$VENV_GC/bin:/usr/bin:/bin"

usage() {
  cat <<'EOF'
Usage (run on a Chrysalis login node):
  chrysalis_endpoint.sh configure [mode]   Write endpoint config files (once per install)
  chrysalis_endpoint.sh start              Activate env + start endpoint in tmux
  chrysalis_endpoint.sh restart            Stop running endpoint, then start fresh
  chrysalis_endpoint.sh status             Show endpoint list
  chrysalis_endpoint.sh check-yac          Run a Slurm YAC import/remap smoke test
  chrysalis_endpoint.sh logs               Show endpoint and worker log hints

Configure modes:
  single-host   (default) LocalProvider — fine for quick probes, killed for real compute
  slurm-debug   SlurmProvider debug queue — submits real compute jobs (use this for plotting/analysis)

NOTE: Chrysalis login nodes kill processes that use significant CPU/memory.
      Use slurm-debug mode for any real UXarray analysis.

Environment overrides:
  ENDPOINT_NAME   Globus Compute endpoint profile name (default: uxarray-chrysalis)
EOF
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_activate_env() {
  # Activate the conda uxarray env, then layer globus-compute-endpoint on top
  # shellcheck disable=SC1091
  source "$(conda info --base 2>/dev/null || echo "$HOME/.conda")/etc/profile.d/conda.sh" 2>/dev/null || true
  conda activate "$CONDA_ENV"
  # Add the globus-compute venv bin so globus-compute-endpoint is on PATH
  export PATH="$VENV_GC/bin:$PATH"
}

_configure_yac_runtime() {
  mkdir -p "$YAC_SHIM_LIB"
  ln -sfn "$MKL_LIB/libmkl_rt.so" "$YAC_SHIM_LIB/liblapack.so.3"
  ln -sfn "$MKL_LIB/libmkl_rt.so" "$YAC_SHIM_LIB/libblas.so.3"
}

_export_yac_runtime() {
  _configure_yac_runtime
  export PATH="$YAC_WORKER_PATH"
  export PYTHONPATH="$YAC_PYTHONPATH"
  export LD_LIBRARY_PATH="$YAC_LD_LIBRARY_PATH"
}

_check_endpoint_dir() {
  local ep_dir="$HOME/.globus_compute/$ENDPOINT_NAME"
  if [[ ! -d "$ep_dir" ]]; then
    echo "Endpoint profile not found: $ep_dir"
    echo "Run: globus-compute-endpoint configure $ENDPOINT_NAME"
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# configure: write Globus Compute template + environment files
# ---------------------------------------------------------------------------

_configure() {
  local mode="${1:-single-host}"
  local ep_dir="$HOME/.globus_compute/$ENDPOINT_NAME"

  if [[ ! -d "$ep_dir" ]]; then
    echo "Creating endpoint profile: $ENDPOINT_NAME"
    _activate_env
    globus-compute-endpoint configure "$ENDPOINT_NAME"
  fi

  _configure_yac_runtime

  cat > "$ep_dir/user_environment.yaml" <<EOF
PATH: "$YAC_WORKER_PATH"
PYTHONPATH: "$YAC_PYTHONPATH"
LD_LIBRARY_PATH: "$YAC_LD_LIBRARY_PATH"
EOF

  case "$mode" in
    single-host)
      cat > "$ep_dir/user_config_template.yaml.j2" <<EOF
endpoint_setup: ""

engine:
  type: GlobusComputeEngine
  max_workers_per_node: 1
  provider:
    type: LocalProvider
    min_blocks: 0
    max_blocks: 1
    init_blocks: 1
    worker_init: |
      export PATH="$YAC_WORKER_PATH"
      export PYTHONPATH="$YAC_PYTHONPATH"
      export LD_LIBRARY_PATH="$YAC_LD_LIBRARY_PATH:\${LD_LIBRARY_PATH:-}"

idle_heartbeats_soft: 10
idle_heartbeats_hard: 5760
EOF
      echo "WARNING: LocalProvider runs on the login node."
      echo "         Login nodes kill processes that use significant CPU/memory."
      echo "         Use 'configure slurm-debug' for real UXarray analysis."
      ;;

    slurm-debug)
      cat > "$ep_dir/user_config_template.yaml.j2" <<EOF
endpoint_setup: ""

engine:
  type: GlobusComputeEngine
  max_workers_per_node: 4

  provider:
    type: SlurmProvider
    partition: compute
    nodes_per_block: 1
    init_blocks: 0
    min_blocks: 0
    max_blocks: 2
    walltime: "01:00:00"
    worker_init: |
      export PATH="$YAC_WORKER_PATH"
      export PYTHONPATH="$YAC_PYTHONPATH"
      export LD_LIBRARY_PATH="$YAC_LD_LIBRARY_PATH:\${LD_LIBRARY_PATH:-}"

    launcher:
      type: SrunLauncher

idle_heartbeats_soft: 10
idle_heartbeats_hard: 5760
EOF
      echo "Configured Slurm-backed endpoint (partition: compute, 1 node, 1h walltime)."
      echo "Workers will be submitted as Slurm jobs — real compute, no login-node kill."
      ;;

    *)
      usage; exit 1
      ;;
  esac

  echo "Wrote:"
  echo "  $ep_dir/user_config_template.yaml.j2"
  echo "  $ep_dir/user_environment.yaml"
  echo
  echo "Next: chrysalis_endpoint.sh start"
}

# ---------------------------------------------------------------------------
# _do_start: real work, called inside tmux
# ---------------------------------------------------------------------------

_do_start() {
  _check_endpoint_dir
  echo "==> Activating conda env: $CONDA_ENV"
  _activate_env
  _export_yac_runtime
  echo "==> Python: $(python --version)"
  echo "==> uxarray: $(python -c 'import uxarray; print(uxarray.__version__)' 2>/dev/null || echo 'check import')"
  echo "==> Starting endpoint: $ENDPOINT_NAME"
  globus-compute-endpoint start "$ENDPOINT_NAME"
}

# ---------------------------------------------------------------------------
# start: wrap _do_start inside tmux
# ---------------------------------------------------------------------------

_start() {
  if [[ -z "${TMUX:-}" ]]; then
    echo "Launching tmux session '$TMUX_SESSION'..."
    exec tmux new-session -A -s "$TMUX_SESSION" \
      "bash -l \"$0\" _do_start; exec bash -l"
  else
    _do_start
  fi
}

# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------

_restart() {
  _check_endpoint_dir
  _activate_env
  echo "==> Stopping endpoint: $ENDPOINT_NAME"
  globus-compute-endpoint stop "$ENDPOINT_NAME" 2>/dev/null || true
  rm -f "$HOME/.globus_compute/$ENDPOINT_NAME/daemon.pid"
  echo "==> Restarting..."
  globus-compute-endpoint start "$ENDPOINT_NAME"
}

# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

_status() {
  _activate_env
  globus-compute-endpoint list
}

_check_yac() {
  _export_yac_runtime
  local smoke
  smoke="$(mktemp "${TMPDIR:-/tmp}/uxmcp-yac-smoke.XXXXXX.py")"
  cat > "$smoke" <<'PY'
import json
import sys
import time
import traceback

out = {"python": sys.version, "executable": sys.executable}
try:
    import yac.core as yc

    out["yac_core_ok"] = True
    out["yac_file"] = getattr(yc, "__file__", None)
except Exception as exc:
    out["yac_core_ok"] = False
    out["yac_core_error"] = f"{type(exc).__name__}: {exc}"
    out["yac_traceback"] = traceback.format_exc()

try:
    import numpy as np
    import uxarray as ux
    import xarray as xr
    from uxarray.remap.yac import _import_yac

    yc = _import_yac()
    out["uxarray_helper_ok"] = True
    out["uxarray_helper_file"] = getattr(yc, "__file__", None)
    src = ux.Grid.from_healpix(zoom=2)
    dst = ux.Grid.from_healpix(zoom=3)
    rng = np.random.default_rng(0)
    uxda = ux.UxDataArray(
        xr.DataArray(rng.standard_normal(int(src.n_face)), dims=("n_face",), name="field"),
        uxgrid=src,
    )
    t0 = time.perf_counter()
    remapped = uxda.remap.nearest_neighbor(destination_grid=dst, remap_to="face centers")
    out["remap_ok"] = True
    out["remap_seconds"] = round(time.perf_counter() - t0, 3)
    out["remap_shape"] = list(remapped.shape)
except Exception as exc:
    out["remap_ok"] = False
    out["remap_error"] = f"{type(exc).__name__}: {exc}"
    out["remap_traceback"] = traceback.format_exc()

print(json.dumps(out, indent=2))
raise SystemExit(0 if out.get("yac_core_ok") and out.get("remap_ok") else 1)
PY
  echo "==> Running YAC smoke through Slurm"
  srun --ntasks 1 bash -lc "PATH='$PATH' PYTHONPATH='$PYTHONPATH' LD_LIBRARY_PATH='$LD_LIBRARY_PATH' python '$smoke'"
}

_logs() {
  local ep_dir="$HOME/.globus_compute/$ENDPOINT_NAME"
  echo "==> Endpoint profile: $ep_dir"
  if [[ ! -d "$ep_dir" ]]; then
    echo "Endpoint profile not found."
    exit 1
  fi
  echo
  echo "==> Current endpoint config"
  sed -n '1,220p' "$ep_dir/user_config_template.yaml.j2" 2>/dev/null || true
  echo
  echo "==> Current endpoint environment"
  sed -n '1,120p' "$ep_dir/user_environment.yaml" 2>/dev/null || true
  echo
  echo "==> Running endpoint-related processes"
  ps -fu "$USER" | grep -E 'globus|parsl|process_worker|interchange|uxarray-chrysalis' | grep -v grep || true
  echo
  echo "==> Latest submit scripts"
  find "$HOME/.globus_compute" -path '*3cca8be6-55ec-4386-b7fd-f6c1e161d52b*/submit_scripts/*' \
    -type f -print 2>/dev/null | sort | tail -10
  echo
  echo "==> Latest endpoint logs"
  find "$HOME/.globus_compute" -path '*3cca8be6-55ec-4386-b7fd-f6c1e161d52b*' \
    \( -name '*.log' -o -name '*.err' -o -name '*.out' \) -type f -print 2>/dev/null | sort | tail -20
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
  configure) shift; _configure "$@" ;;
  start)     _start ;;
  _do_start) _do_start ;;   # internal: invoked by tmux
  restart)   _restart ;;
  status)    _status ;;
  check-yac) _check_yac ;;
  logs)      _logs ;;
  *) usage; exit 1 ;;
esac
