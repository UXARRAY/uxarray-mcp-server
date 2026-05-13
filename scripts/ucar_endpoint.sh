#!/usr/bin/env bash
# Run on Casper (NCAR) to configure or start the ucar-uxarray-yac Globus Compute endpoint.
set -euo pipefail

# ---------------------------------------------------------------------------
# USER CONFIG — change these to match your account before running
# ---------------------------------------------------------------------------
USERNAME="rajeevj"   # your NCAR username
# ---------------------------------------------------------------------------

ENDPOINT_NAME="${ENDPOINT_NAME:-ucar-uxarray-yac}"
CONDA_ENV="/glade/work/$USERNAME/conda-envs/uxarray_dev"
YAC_ACTIVATE="$HOME/opt/yac-core-v3.14.0_p1/activate-yac.sh"
MCP_SERVER_DIR="/glade/u/home/$USERNAME/uxarray-mcp-server"
UXARRAY_DIR="/glade/u/home/$USERNAME/uxarray"
TMUX_SESSION="uxarray-endpoint"

usage() {
  cat <<'EOF'
Usage (run on a Casper login node):
  ucar_endpoint.sh configure    Write endpoint config files (once per install)
  ucar_endpoint.sh start        Load env + start endpoint in tmux
  ucar_endpoint.sh restart      Stop running endpoint, then start fresh
  ucar_endpoint.sh status       Show endpoint list

Environment overrides:
  ENDPOINT_NAME   Globus Compute endpoint profile name (default: ucar-uxarray-yac)
EOF
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_load_modules() {
  if ! command -v module &>/dev/null 2>&1; then
    for _init in \
      /usr/share/lmod/lmod/init/bash \
      /etc/profile.d/lmod.sh \
      /glade/u/apps/opt/lmod/init/bash; do
      [[ -f "$_init" ]] && source "$_init" && break
    done
  fi

  module purge
  module load ncarenv/24.12
  module load gcc/12.4.0
  module load openmpi/5.0.6
  module load conda
}

_activate_env() {
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "$CONDA_ENV"
  source "$YAC_ACTIVATE"
}

_check_yac() {
  python -c 'import yac; import yac.core; print("  YAC OK:", yac.core.__file__)' \
    || { echo "ERROR: yac.core import failed — check YAC build at $YAC_ACTIVATE"; exit 1; }
}

# ---------------------------------------------------------------------------
# configure: write Globus Compute template + environment files
# ---------------------------------------------------------------------------

_configure() {
  local ep_dir="$HOME/.globus_compute/$ENDPOINT_NAME"

  if [[ ! -d "$ep_dir" ]]; then
    echo "Creating endpoint profile: $ENDPOINT_NAME"
    globus-compute-endpoint configure "$ENDPOINT_NAME"
  fi

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
      source $YAC_ACTIVATE
      export PYTHONPATH="$MCP_SERVER_DIR/src:$UXARRAY_DIR:\${PYTHONPATH:-}"
      cd $MCP_SERVER_DIR

idle_heartbeats_soft: 10
idle_heartbeats_hard: 5760
EOF

  cat > "$ep_dir/user_environment.yaml" <<EOF
PATH: "$CONDA_ENV/bin:/usr/bin:/bin"
EOF

  echo "Wrote:"
  echo "  $ep_dir/user_config_template.yaml.j2"
  echo "  $ep_dir/user_environment.yaml"
  echo
  echo "Next: ucar_endpoint.sh start"
}

# ---------------------------------------------------------------------------
# _do_start: the real work, called inside tmux
# ---------------------------------------------------------------------------

_do_start() {
  echo "==> Loading modules..."
  _load_modules
  echo "==> Activating conda env: $CONDA_ENV"
  _activate_env
  echo "==> Checking YAC..."
  _check_yac
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
    # -A: attach if session exists, create otherwise; keep shell alive after endpoint exits
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
  _load_modules
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
  _load_modules
  _activate_env
  globus-compute-endpoint list
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

case "${1:-}" in
  configure) _configure ;;
  start)     _start ;;
  _do_start) _do_start ;;  # internal: invoked by tmux
  restart)   _restart ;;
  status)    _status ;;
  *) usage; exit 1 ;;
esac
