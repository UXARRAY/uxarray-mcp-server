#!/usr/bin/env bash
# Run on Chrysalis (ANL/LCRC) to configure or start the Globus Compute endpoint.
set -euo pipefail

# ---------------------------------------------------------------------------
# USER CONFIG — change these to match your account before running
# ---------------------------------------------------------------------------
USERNAME="jain"   # your Chrysalis username
# ---------------------------------------------------------------------------

ENDPOINT_NAME="${ENDPOINT_NAME:-chrysalis-uxarray}"
CONDA_ENV="$HOME/.conda/envs/uxarray-yac"
VENV_GC="$HOME/venvs/globus-compute"
TMUX_SESSION="uxarray-endpoint"

usage() {
  cat <<'EOF'
Usage (run on a Chrysalis login node):
  chrysalis_endpoint.sh configure [mode]   Write endpoint config files (once per install)
  chrysalis_endpoint.sh start              Activate env + start endpoint in tmux
  chrysalis_endpoint.sh restart            Stop running endpoint, then start fresh
  chrysalis_endpoint.sh status             Show endpoint list

Configure modes:
  single-host   (default) LocalProvider — fine for quick probes, killed for real compute
  slurm-debug   SlurmProvider debug queue — submits real compute jobs (use this for plotting/analysis)

NOTE: Chrysalis login nodes kill processes that use significant CPU/memory.
      Use slurm-debug mode for any real UXarray analysis.

Environment overrides:
  ENDPOINT_NAME   Globus Compute endpoint profile name (default: chrysalis-uxarray)
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

  cat > "$ep_dir/user_environment.yaml" <<EOF
PATH: "$CONDA_ENV/bin:$VENV_GC/bin:/usr/bin:/bin"
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
      source "\$(conda info --base)/etc/profile.d/conda.sh"
      conda activate $CONDA_ENV

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
      source "\$(conda info --base)/etc/profile.d/conda.sh"
      conda activate $CONDA_ENV

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

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
  configure) shift; _configure "$@" ;;
  start)     _start ;;
  _do_start) _do_start ;;   # internal: invoked by tmux
  restart)   _restart ;;
  status)    _status ;;
  *) usage; exit 1 ;;
esac
