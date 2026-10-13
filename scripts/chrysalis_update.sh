#!/usr/bin/env bash
# Bring the Chrysalis worker up to the versions the submitter is running.
#
# Run this ON A CHRYSALIS LOGIN NODE. It cannot be run from a laptop: LCRC
# requires MFA, so there is no non-interactive path in.
#
# Why this exists: the worker imports both uxarray and uxarray-mcp from git
# checkouts under /lcrc/group/e3sm/$USER, not from the conda environment.
# `conda update` therefore does nothing for either, and the drift warning
# ("local=2026.9.1, remote(worker)=2026.9.0") keeps firing until the
# checkouts are pulled and the endpoint is restarted so workers re-import.
#
#   uxarray      <- $UXARRAY_YAC_SRC            (on the worker PYTHONPATH)
#   uxarray-mcp  <- $UXARRAY_MCP_SRC            (installed editable / on path)
#
# Usage:
#   ./scripts/chrysalis_update.sh            # pull both, show versions
#   ./scripts/chrysalis_update.sh --restart  # also restart the endpoint
set -euo pipefail

UXARRAY_YAC_SRC="${UXARRAY_YAC_SRC:-/lcrc/group/e3sm/$USER/uxarray-yac-src}"
UXARRAY_MCP_SRC="${UXARRAY_MCP_SRC:-/lcrc/group/e3sm/$USER/uxarray-mcp-server}"
CONDA_ENV="${CONDA_ENV:-$HOME/.conda/envs/uxarray-yac}"
RESTART=0

for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -d "$UXARRAY_YAC_SRC/.git" ] && [ ! -d "$UXARRAY_MCP_SRC/.git" ]; then
  echo "Neither checkout found. Are you on a Chrysalis login node?" >&2
  echo "  looked for: $UXARRAY_YAC_SRC" >&2
  echo "              $UXARRAY_MCP_SRC" >&2
  exit 1
fi

pull() {
  local dir="$1" name="$2"
  if [ ! -d "$dir/.git" ]; then
    echo "==> $name: no checkout at $dir, skipping"
    return
  fi
  echo "==> $name: $dir"
  local before
  before="$(git -C "$dir" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  # A dirty checkout is a local experiment someone is mid-way through.
  # Clobbering it silently is how an afternoon of debugging disappears.
  if ! git -C "$dir" diff --quiet || ! git -C "$dir" diff --cached --quiet; then
    echo "    REFUSING: uncommitted changes. Commit, stash or discard first:"
    git -C "$dir" status --short | sed 's/^/      /'
    return
  fi
  git -C "$dir" pull --ff-only
  local after
  after="$(git -C "$dir" rev-parse --short HEAD)"
  if [ "$before" = "$after" ]; then
    echo "    already current at $after"
  else
    echo "    $before -> $after"
  fi
}

pull "$UXARRAY_YAC_SRC" "uxarray (YAC source)"
pull "$UXARRAY_MCP_SRC" "uxarray-mcp (this server)"

echo
echo "==> Versions the worker will now import"
# Report through the same interpreter the endpoint's worker_init puts first,
# so this agrees with what the drift warning compares against.
"$CONDA_ENV/bin/python" - <<PY || echo "    (could not query $CONDA_ENV/bin/python)"
import importlib.util, os, sys
sys.path.insert(0, "$UXARRAY_YAC_SRC")
sys.path.insert(0, os.path.join("$UXARRAY_MCP_SRC", "src"))
for name in ("uxarray", "xarray", "numpy", "uxarray_mcp"):
    spec = importlib.util.find_spec(name)
    if spec is None:
        print(f"    {name:12} NOT IMPORTABLE")
        continue
    mod = __import__(name)
    print(f"    {name:12} {getattr(mod, '__version__', '?'):12} {getattr(mod, '__file__', '?')}")
PY

if [ "$RESTART" -eq 1 ]; then
  echo
  echo "==> Restarting the endpoint so workers re-import"
  # Running workers hold the old modules in memory; a pull alone changes
  # nothing until the processes are replaced.
  "$(dirname "$0")/chrysalis_endpoint.sh" restart
else
  echo
  echo "Pulled, but running workers still hold the OLD code in memory."
  echo "Restart the endpoint to pick it up:"
  echo "    ./scripts/chrysalis_endpoint.sh restart"
fi
