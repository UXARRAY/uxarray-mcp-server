#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  improv_endpoint.sh single-host [endpoint-name]
  improv_endpoint.sh pbs-debug <project> [endpoint-name]

Modes:
  single-host  Write a LocalProvider template for first-pass validation.
  pbs-debug    Write a PBSPro debug-queue template for Improv.

The script writes:
  ~/.globus_compute/<endpoint-name>/user_config_template.yaml.j2
  ~/.globus_compute/<endpoint-name>/user_environment.yaml

It does not start the endpoint for you. Run it inside tmux, then start:
  source ~/venvs/globus-compute/bin/activate
  globus-compute-endpoint start <endpoint-name>
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

MODE="$1"
PROJECT="${2:-}"
ENDPOINT_NAME="${3:-improv-uxarray}"

if [[ "$MODE" == "single-host" ]]; then
  ENDPOINT_NAME="${2:-improv-uxarray}"
fi

ENDPOINT_DIR="$HOME/.globus_compute/$ENDPOINT_NAME"
if [[ ! -d "$ENDPOINT_DIR" ]]; then
  echo "Endpoint profile not found: $ENDPOINT_DIR"
  echo "Run: globus-compute-endpoint configure $ENDPOINT_NAME"
  exit 1
fi

mkdir -p "$HOME/venvs/globus-compute/bin"

cat > "$ENDPOINT_DIR/user_environment.yaml" <<EOF
PATH: /opt/pbs/bin:$HOME/venvs/globus-compute/bin:/usr/bin:/bin
EOF

case "$MODE" in
  single-host)
    cat > "$ENDPOINT_DIR/user_config_template.yaml.j2" <<'EOF'
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
    if [[ -z "$PROJECT" ]]; then
      usage
      exit 1
    fi
    ln -sf /opt/pbs/bin/qsub "$HOME/venvs/globus-compute/bin/qsub"
    ln -sf /opt/pbs/bin/qstat "$HOME/venvs/globus-compute/bin/qstat"
    ln -sf /opt/pbs/bin/qdel "$HOME/venvs/globus-compute/bin/qdel"
    cat > "$ENDPOINT_DIR/user_config_template.yaml.j2" <<EOF
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
    account: $PROJECT
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
    usage
    exit 1
    ;;
esac

echo "Wrote:"
echo "  $ENDPOINT_DIR/user_environment.yaml"
echo "  $ENDPOINT_DIR/user_config_template.yaml.j2"
echo
echo "Next steps:"
echo "  source ~/venvs/globus-compute/bin/activate"
echo "  globus-compute-endpoint stop $ENDPOINT_NAME || true"
echo "  rm -f $ENDPOINT_DIR/daemon.pid"
echo "  globus-compute-endpoint start $ENDPOINT_NAME"
