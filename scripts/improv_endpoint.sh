#!/usr/bin/env bash
# Run on Improv (ANL) to configure or start the Globus Compute endpoint.
set -euo pipefail

# ---------------------------------------------------------------------------
# USER CONFIG — change these to match your account before running
# ---------------------------------------------------------------------------
USERNAME="jain"   # your Improv username
# ---------------------------------------------------------------------------

ENDPOINT_NAME="${ENDPOINT_NAME:-improv-uxarray}"
# Python 3.12 is available system-wide on Improv (/usr/bin/python3.12).
# Use it for new venv creation to match the local SDK's 3.13 closely enough
# that Dill serialization works. Existing 3.11 venvs still function via
# AllCodeStrategies but will show a mismatch warning.
PYTHON="${PYTHON:-/usr/bin/python3.12}"
VENV="$HOME/venvs/globus-compute"
MCP_SERVER_DIR="/home/$USERNAME/uxarray-mcp-server"
TMUX_SESSION="uxarray-endpoint"

usage() {
  cat <<'EOF'
Usage (run on an Improv login node):
  improv_endpoint.sh configure <mode> [args]   Write endpoint config files
  improv_endpoint.sh start                     Activate venv + start endpoint in tmux
  improv_endpoint.sh restart                   Stop running endpoint, then start fresh
  improv_endpoint.sh status                    Show endpoint list
  improv_endpoint.sh upgrade-venv              Rebuild venv with Python 3.12 (eliminates Dill mismatch)

Configure modes:
  single-host [endpoint-name]       LocalProvider template (first-pass validation)
  pbs-debug   <project> [ep-name]   PBSPro debug-queue template

Environment overrides:
  ENDPOINT_NAME   Globus Compute endpoint profile name (default: improv-uxarray)
  PYTHON          Python executable for venv creation (default: /usr/bin/python3.12)
EOF
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_activate_env() {
  source "$VENV/bin/activate"
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
  local mode="${1:-}"
  local project="${2:-}"
  local ep_name="${2:-$ENDPOINT_NAME}"  # single-host uses arg2 as ep name

  if [[ -z "$mode" ]]; then
    usage; exit 1
  fi

  # pbs-debug uses arg2 as project, arg3 as optional ep name
  if [[ "$mode" == "pbs-debug" ]]; then
    ep_name="${3:-$ENDPOINT_NAME}"
  fi

  ENDPOINT_NAME="$ep_name"
  local ep_dir="$HOME/.globus_compute/$ENDPOINT_NAME"

  if [[ ! -d "$ep_dir" ]]; then
    echo "Endpoint profile not found: $ep_dir"
    echo "Run: globus-compute-endpoint configure $ENDPOINT_NAME"
    exit 1
  fi

  mkdir -p "$VENV/bin"

  cat > "$ep_dir/user_environment.yaml" <<EOF
PATH: "/opt/pbs/bin:$VENV/bin:/usr/bin:/bin"
EOF

  case "$mode" in
    single-host)
      cat > "$ep_dir/user_config_template.yaml.j2" <<'EOF'
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
      source ~/venvs/globus-compute/bin/activate

idle_heartbeats_soft: 10
idle_heartbeats_hard: 5760
EOF
      ;;

    pbs-debug)
      if [[ -z "$project" ]]; then
        usage; exit 1
      fi
      ln -sf /opt/pbs/bin/qsub  "$VENV/bin/qsub"
      ln -sf /opt/pbs/bin/qstat "$VENV/bin/qstat"
      ln -sf /opt/pbs/bin/qdel  "$VENV/bin/qdel"
      cat > "$ep_dir/user_config_template.yaml.j2" <<EOF
endpoint_setup: |
  export PATH=/opt/pbs/bin:\$PATH

engine:
  type: GlobusComputeEngine
  max_workers_per_node: 1

  address:
    type: address_by_interface
    ifname: ib0

  provider:
    type: PBSProProvider
    account: $project
    queue: debug
    worker_init: |
      source ~/venvs/globus-compute/bin/activate
    nodes_per_block: 1
    init_blocks: 0
    min_blocks: 0
    max_blocks: 1
    walltime: 00:30:00

    launcher:
      type: MpiExecLauncher

idle_heartbeats_soft: 10
idle_heartbeats_hard: 5760
EOF
      ;;

    *)
      usage; exit 1
      ;;
  esac

  echo "Wrote:"
  echo "  $ep_dir/user_environment.yaml"
  echo "  $ep_dir/user_config_template.yaml.j2"
  echo
  echo "Next: improv_endpoint.sh start"
}

# ---------------------------------------------------------------------------
# _do_start: the real work, called inside tmux
# ---------------------------------------------------------------------------

_do_start() {
  _check_endpoint_dir
  echo "==> Activating venv: $VENV"
  _activate_env
  echo "==> Starting endpoint: $ENDPOINT_NAME"
  cd "$MCP_SERVER_DIR"
  globus-compute-endpoint start "$ENDPOINT_NAME"
}

# ---------------------------------------------------------------------------
# start: wrap _do_start inside a tmux session
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

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# upgrade-venv: rebuild the globus-compute venv with Python 3.12
# Eliminates the Dill 3.13<->3.11 mismatch warning and WorkerLost crashes
# when sending raw closures. AllCodeStrategies still works regardless.
# ---------------------------------------------------------------------------

_upgrade_venv() {
  echo "==> Checking Python 3.12: $PYTHON"
  if ! "$PYTHON" --version 2>&1 | grep -q "3\.12"; then
    echo "ERROR: $PYTHON is not Python 3.12. Set PYTHON= to the correct path."
    exit 1
  fi

  local backup="$HOME/venvs/globus-compute-3.11-backup"
  if [[ -d "$VENV" ]]; then
    echo "==> Backing up existing venv to $backup"
    mv "$VENV" "$backup"
  fi

  echo "==> Creating new venv with $PYTHON"
  "$PYTHON" -m venv "$VENV"
  source "$VENV/bin/activate"

  echo "==> Installing globus-compute-endpoint"
  pip install --upgrade pip
  pip install "globus-compute-endpoint>=4.9.0" uxarray xarray netCDF4 h5netcdf numpy

  echo "==> Verifying"
  python --version
  python -c "import uxarray; print('uxarray OK')"
  globus-compute-endpoint --version

  echo ""
  echo "==> Venv rebuilt with Python 3.12."
  echo "    Run: improv_endpoint.sh restart"
}

case "${1:-}" in
  configure)    shift; _configure "$@" ;;
  start)        _start ;;
  _do_start)    _do_start ;;  # internal: invoked by tmux
  restart)      _restart ;;
  status)       _status ;;
  upgrade-venv) _upgrade_venv ;;
  *) usage; exit 1 ;;
esac
