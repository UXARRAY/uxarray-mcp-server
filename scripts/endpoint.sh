#!/usr/bin/env bash
# Stand up a Globus Compute endpoint for uxarray-mcp on any HPC machine.
#
# This is the site-agnostic script: it knows nothing about YAC, about any
# facility's filesystem layout, or about anybody's username. Everything that
# differs between machines is an environment variable with a default that works
# on a plain login node. The per-site scripts in this directory (ucar_,
# chrysalis_, improv_) are this same shape with a site's verified module list
# and library paths already filled in.
#
# The MCP server repo does NOT need to be cloned on the HPC machine for remote
# analysis -- functions are serialised via AllCodeStrategies and run against
# whatever is installed in the worker environment. You only need this one file.
# Never add uxarray_mcp itself to the worker's PYTHONPATH; it drags in a
# pydantic that conflicts with the one globus-compute-endpoint wants.
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration -- override any of these in the environment
# ---------------------------------------------------------------------------
ENDPOINT_NAME="${ENDPOINT_NAME:-uxarray}"

# Worker environment. Set VENV for a virtualenv, CONDA_ENV for a conda env
# (a name or an absolute path). CONDA_ENV wins if both are set, because a
# conda env is what most facilities' own documentation tells you to build.
CONDA_ENV="${CONDA_ENV:-}"
VENV="${VENV:-}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

# Modules to load before touching the environment, space separated and in
# order, e.g. MODULES="ncarenv/24.12 conda". Empty means the site needs none.
MODULES="${MODULES:-}"
MODULE_PURGE="${MODULE_PURGE:-0}"

# Where the work runs. "local" puts workers on the login node, which is the
# right first step everywhere: it proves the endpoint round-trips before a
# scheduler can be blamed for anything. Move to slurm or pbs once it does.
SCHEDULER="${SCHEDULER:-local}"      # local | slurm | pbs
ACCOUNT="${ACCOUNT:-}"               # Slurm account / PBS project -- required off local
QUEUE="${QUEUE:-}"                   # PBS queue or Slurm partition
WALLTIME="${WALLTIME:-01:00:00}"
NODES_PER_BLOCK="${NODES_PER_BLOCK:-1}"
MAX_BLOCKS="${MAX_BLOCKS:-1}"
MAX_WORKERS_PER_NODE="${MAX_WORKERS_PER_NODE:-1}"

# Extra worker_init lines, appended verbatim after the environment is active.
# This is the hook a site script uses for things this script must not know
# about -- a YAC activate file, an LD_LIBRARY_PATH, a scratch export.
WORKER_INIT_EXTRA="${WORKER_INIT_EXTRA:-}"

# Some facilities firewall AMQP's default 5671. Set AMQP_PORT=443 there.
AMQP_PORT="${AMQP_PORT:-}"

TMUX_SESSION="${TMUX_SESSION:-uxarray-endpoint}"

usage() {
  cat <<'EOF'
Usage (run on an HPC login node):
  endpoint.sh install      Create the worker environment and install into it
  endpoint.sh check        Report what is ready and what is missing; change nothing
  endpoint.sh configure    Write the endpoint config (once per install)
  endpoint.sh start        Start the endpoint inside tmux
  endpoint.sh restart      Stop a running endpoint, then start it again
  endpoint.sh status       Show the endpoint list
  endpoint.sh uuid         Print this endpoint's UUID for `uxarray-mcp endpoints add`

Environment overrides:
  ENDPOINT_NAME         Endpoint profile name (default: uxarray)
  CONDA_ENV             Conda env name or path for the worker
  VENV                  Virtualenv path for the worker (used if CONDA_ENV unset)
  PYTHON_VERSION        Python for `install` (default: 3.12 -- see the note below)
  MODULES               Modules to load, space separated, in order
  MODULE_PURGE          1 to `module purge` first (default: 0)
  SCHEDULER             local | slurm | pbs (default: local)
  ACCOUNT               Slurm account or PBS project; required unless local
  QUEUE                 PBS queue or Slurm partition
  WALLTIME              Job walltime (default: 01:00:00)
  NODES_PER_BLOCK       Nodes per scheduler job (default: 1)
  MAX_BLOCKS            Concurrent scheduler jobs (default: 1)
  MAX_WORKERS_PER_NODE  Workers per node (default: 1)
  WORKER_INIT_EXTRA     Extra worker_init lines, appended verbatim
  AMQP_PORT             Set to 443 where the site firewalls 5671
  TMUX_SESSION          tmux session name (default: uxarray-endpoint)

Python version: Globus Compute tolerates patch skew (3.12.4 vs 3.12.10) but
not minor skew (3.12 vs 3.13). uxarray-mcp pins 3.12, so build the worker on
3.12 and the submitter side already matches.

Examples:
  # Simplest thing that works: login-node workers, conda, no scheduler
  CONDA_ENV=uxarray ./endpoint.sh install
  CONDA_ENV=uxarray ./endpoint.sh configure && CONDA_ENV=uxarray ./endpoint.sh start

  # Slurm, once the local one round-trips
  CONDA_ENV=uxarray SCHEDULER=slurm ACCOUNT=myproj QUEUE=debug \
    ./endpoint.sh configure
EOF
}

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

_env_kind() {
  if [[ -n "$CONDA_ENV" ]]; then echo conda
  elif [[ -n "$VENV" ]]; then echo venv
  else echo none
  fi
}

_require_env_choice() {
  if [[ "$(_env_kind)" == none ]]; then
    echo "ERROR: set CONDA_ENV (name or path) or VENV (path) first." >&2
    echo "  e.g. CONDA_ENV=uxarray $(basename "$0") $1" >&2
    return 1
  fi
}

_load_modules() {
  [[ -z "$MODULES" ]] && return 0
  if ! command -v module &>/dev/null; then
    # `module` is a shell function, so it can be missing in a non-login shell
    # even on a machine that has Lmod. Say which, or the user edits MODULES
    # looking for a typo that is not there.
    echo "WARNING: MODULES is set but no 'module' command in this shell." >&2
    echo "  Run from a login shell (bash -l), or unset MODULES." >&2
    return 0
  fi
  [[ "$MODULE_PURGE" == "1" ]] && module purge
  local m
  for m in $MODULES; do module load "$m"; done
  return 0
}

_activate_env() {
  case "$(_env_kind)" in
    conda)
      if ! command -v conda &>/dev/null; then
        echo "ERROR: no conda on PATH. Add the site's conda module to MODULES." >&2
        return 1
      fi
      # shellcheck disable=SC1091
      source "$(conda info --base)/etc/profile.d/conda.sh"
      conda activate "$CONDA_ENV"
      ;;
    venv)
      # shellcheck disable=SC1091
      source "$VENV/bin/activate"
      ;;
    *) _require_env_choice activate ;;
  esac
}

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

_install() {
  _require_env_choice install
  _load_modules
  case "$(_env_kind)" in
    conda)
      if conda env list | awk '{print $1}' | grep -qx "$CONDA_ENV"; then
        echo "==> Conda env '$CONDA_ENV' exists; installing into it"
      else
        echo "==> Creating conda env '$CONDA_ENV' (python $PYTHON_VERSION)"
        conda create -n "$CONDA_ENV" "python=$PYTHON_VERSION" -c conda-forge -y
      fi
      ;;
    venv)
      if [[ ! -d "$VENV" ]]; then
        echo "==> Creating venv $VENV"
        "python$PYTHON_VERSION" -m venv "$VENV"
      fi
      ;;
  esac
  _activate_env
  echo "==> Installing worker packages"
  python -m pip install --upgrade pip
  python -m pip install globus-compute-endpoint uxarray xarray netCDF4 h5netcdf matplotlib
  echo
  echo "Installed into: $(python -c 'import sys; print(sys.prefix)')"
  python -c 'import sys; print("python", ".".join(map(str, sys.version_info[:3])))'
  echo "Next: $(basename "$0") configure"
}

# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------

_worker_init() {
  # Emitted as a YAML block scalar, so the caller indents every line. Order
  # matters: PYTHONPATH is cleared before anything activates, or the login
  # node's site-packages shadow the worker's and the import errors that
  # follow name packages nobody asked for.
  echo "unset PYTHONPATH"
  if [[ -n "$MODULES" ]]; then
    [[ "$MODULE_PURGE" == "1" ]] && echo "module purge"
    local m
    for m in $MODULES; do echo "module load $m"; done
  fi
  case "$(_env_kind)" in
    conda)
      # Left unexpanded on purpose: conda's base differs between the login
      # node and a compute node at some sites.
      echo "source \"\$(conda info --base)/etc/profile.d/conda.sh\""
      echo "conda activate $CONDA_ENV"
      ;;
    venv) echo "source $VENV/bin/activate" ;;
  esac
  [[ -n "$WORKER_INIT_EXTRA" ]] && printf '%s\n' "$WORKER_INIT_EXTRA"
  return 0
}

_provider_block() {
  case "$SCHEDULER" in
    local)
      cat <<EOF
    type: LocalProvider
    init_blocks: 1
    min_blocks: 0
    max_blocks: $MAX_BLOCKS
EOF
      ;;
    slurm)
      cat <<EOF
    type: SlurmProvider
    partition: $QUEUE
    account: $ACCOUNT
    nodes_per_block: $NODES_PER_BLOCK
    init_blocks: 1
    min_blocks: 0
    max_blocks: $MAX_BLOCKS
    walltime: "$WALLTIME"
EOF
      ;;
    pbs)
      cat <<EOF
    type: PBSProProvider
    queue: $QUEUE
    account: $ACCOUNT
    nodes_per_block: $NODES_PER_BLOCK
    init_blocks: 1
    min_blocks: 0
    max_blocks: $MAX_BLOCKS
    walltime: "$WALLTIME"
EOF
      ;;
    *)
      echo "ERROR: SCHEDULER must be local, slurm or pbs (got '$SCHEDULER')." >&2
      return 1
      ;;
  esac
}

_configure() {
  _require_env_choice configure
  if [[ "$SCHEDULER" != local ]]; then
    if [[ -z "$ACCOUNT" ]]; then
      # Without an account the scheduler rejects every job, and Globus Compute
      # reports the endpoint as healthy while no worker ever appears.
      echo "ERROR: SCHEDULER=$SCHEDULER needs ACCOUNT set to your project." >&2
      return 1
    fi
    if [[ -z "$QUEUE" ]]; then
      echo "ERROR: SCHEDULER=$SCHEDULER needs QUEUE set to the partition or queue." >&2
      return 1
    fi
  fi
  _load_modules
  _activate_env

  local ep_dir="$HOME/.globus_compute/$ENDPOINT_NAME"
  if [[ ! -d "$ep_dir" ]]; then
    echo "==> Creating endpoint profile: $ENDPOINT_NAME"
    globus-compute-endpoint configure "$ENDPOINT_NAME"
  fi

  {
    echo "display_name: $ENDPOINT_NAME"
    [[ -n "$AMQP_PORT" ]] && echo "amqp_port: $AMQP_PORT"
    echo "engine:"
    echo "  type: GlobusComputeEngine"
    echo "  max_workers_per_node: $MAX_WORKERS_PER_NODE"
    echo "  provider:"
    _provider_block
    echo "    worker_init: |"
    _worker_init | sed 's/^/      /'
    # The endpoint stops itself after a long idle rather than holding a
    # scheduler allocation forever; the soft count releases blocks first.
    echo "idle_heartbeats_soft: 10"
    echo "idle_heartbeats_hard: 5760"
  } > "$ep_dir/config.yaml"

  echo "Wrote $ep_dir/config.yaml:"
  echo
  sed 's/^/  /' "$ep_dir/config.yaml"
  echo
  echo "Next: $(basename "$0") start"
}

# ---------------------------------------------------------------------------
# check -- report only, change nothing
# ---------------------------------------------------------------------------

_check_line() { printf '  [%s] %s\n' "$1" "$2"; }

_check() {
  local missing=0
  if [[ "$(_env_kind)" == none ]]; then
    _check_line TODO "worker env -- set CONDA_ENV or VENV"
    missing=1
  else
    _check_line "ok " "worker env -- $(_env_kind): ${CONDA_ENV:-$VENV}"
  fi

  _load_modules || true
  if [[ "$(_env_kind)" != none ]] && _activate_env 2>/dev/null; then
    _check_line "ok " "env activates"
    if command -v globus-compute-endpoint &>/dev/null; then
      _check_line "ok " "globus-compute-endpoint -- $(command -v globus-compute-endpoint)"
    else
      _check_line TODO "globus-compute-endpoint not installed -- run: $(basename "$0") install"
      missing=1
    fi
    local pyver
    pyver="$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo '?')"
    if [[ "$pyver" == "3.12" ]]; then
      _check_line "ok " "worker python $pyver"
    else
      # Minor skew breaks Dill; AllCodeStrategies hides it for simple payloads
      # and then does not, which is the worst way to find out.
      _check_line TODO "worker python $pyver -- uxarray-mcp pins 3.12; rebuild the env"
      missing=1
    fi
    if python -c 'import uxarray' 2>/dev/null; then
      _check_line "ok " "uxarray importable"
    else
      _check_line TODO "uxarray not importable in the worker env"
      missing=1
    fi
  else
    _check_line TODO "env does not activate -- check MODULES and CONDA_ENV/VENV"
    missing=1
  fi

  if [[ -f "$HOME/.globus_compute/$ENDPOINT_NAME/config.yaml" ]]; then
    _check_line "ok " "config -- ~/.globus_compute/$ENDPOINT_NAME/config.yaml"
  else
    _check_line TODO "no config -- run: $(basename "$0") configure"
    missing=1
  fi

  if command -v tmux &>/dev/null; then
    _check_line "ok " "tmux available"
  else
    _check_line TODO "no tmux -- the endpoint would die with your ssh session"
    missing=1
  fi

  if [[ "$SCHEDULER" != local && -z "$ACCOUNT" ]]; then
    _check_line TODO "SCHEDULER=$SCHEDULER but ACCOUNT is empty"
    missing=1
  fi
  return "$missing"
}

# ---------------------------------------------------------------------------
# start / restart / status
# ---------------------------------------------------------------------------

_do_start() {
  _load_modules
  _activate_env
  # `globus-compute-endpoint start` against a profile that is already Running
  # takes the live endpoint down rather than no-opping, and reports success
  # while doing it. Refuse, and name the verb that works.
  if globus-compute-endpoint list 2>/dev/null | grep -q "Running.*$ENDPOINT_NAME"; then
    echo "ERROR: '$ENDPOINT_NAME' is already Running -- starting again would stop it." >&2
    echo "  Use: $(basename "$0") restart" >&2
    return 1
  fi
  echo "==> Starting endpoint: $ENDPOINT_NAME"
  globus-compute-endpoint start "$ENDPOINT_NAME"
}

_start() {
  _require_env_choice start
  if [[ -z "${TMUX:-}" ]]; then
    echo "Launching tmux session '$TMUX_SESSION'..."
    # -A: attach if it exists, create otherwise. The trailing shell keeps the
    # window open when the endpoint exits, so the error is still on screen.
    exec tmux new-session -A -s "$TMUX_SESSION" \
      "bash -l \"$0\" _do_start; exec bash -l"
  fi
  local current
  current="$(tmux display-message -p '#S' 2>/dev/null || echo '')"
  if [[ "$current" != "$TMUX_SESSION" ]]; then
    # Running from some other session leaves the endpoint owned by whatever
    # shell happened to be attached, and invites a second copy from elsewhere.
    echo "ERROR: inside tmux session '$current', not '$TMUX_SESSION'." >&2
    echo "  Detach with Ctrl-b d, then re-run from a plain shell." >&2
    return 1
  fi
  _do_start
}

_restart() {
  _require_env_choice restart
  _load_modules
  _activate_env
  echo "==> Stopping endpoint: $ENDPOINT_NAME"
  globus-compute-endpoint stop "$ENDPOINT_NAME" 2>/dev/null || true
  rm -f "$HOME/.globus_compute/$ENDPOINT_NAME/daemon.pid"
  echo "==> Restarting..."
  globus-compute-endpoint start "$ENDPOINT_NAME"
}

_status() {
  _load_modules
  _activate_env
  globus-compute-endpoint list
}

_uuid() {
  local f="$HOME/.globus_compute/$ENDPOINT_NAME/endpoint.json"
  if [[ ! -f "$f" ]]; then
    echo "ERROR: no $f -- the endpoint has not been started yet." >&2
    return 1
  fi
  python -c "import json,sys; print(json.load(open(sys.argv[1]))['endpoint_id'])" "$f"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
  install)   _install ;;
  check)     _check ;;
  configure) _configure ;;
  start)     _start ;;
  _do_start) _do_start ;;  # internal: invoked by tmux
  restart)   _restart ;;
  status)    _status ;;
  uuid)      _uuid ;;
  *) usage; exit 1 ;;
esac
