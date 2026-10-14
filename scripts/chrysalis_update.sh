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
CONDA_ENV="${CONDA_ENV:-$HOME/.conda/envs/uxarray-yac}"
RESTART=0

# Which uxarray-mcp checkout does the worker actually import?
#
# Do not guess this. There are two clones on Chrysalis --
# /home/$USER/uxarray-mcp-server and /lcrc/group/e3sm/$USER/uxarray-mcp-server
# -- and the conda environment carries an *editable* install pointing at the
# first one. Pulling the second changed nothing the worker could see: the
# login node reported 2026.9.1 @ e0f88a5 while every task still ran
# 2026.9.0 @ a9468e7, which looks exactly like a restart that did not take.
#
# So ask the interpreter where it resolves the package, and update that.
# An explicit UXARRAY_MCP_SRC still wins, for a layout this cannot infer.
if [ -z "${UXARRAY_MCP_SRC:-}" ]; then
  _resolved="$(
    "$CONDA_ENV/bin/python" - <<'PY' 2>/dev/null || true
import importlib.util, os
spec = importlib.util.find_spec("uxarray_mcp")
origin = getattr(spec, "origin", None) or ""
if origin:
    # .../<repo>/src/uxarray_mcp/__init__.py -> <repo>
    pkg = os.path.dirname(origin)
    src = os.path.dirname(pkg)
    repo = os.path.dirname(src)
    if os.path.isdir(os.path.join(repo, ".git")):
        print(os.path.realpath(repo))
PY
  )"
  if [ -n "$_resolved" ]; then
    UXARRAY_MCP_SRC="$_resolved"
    echo "==> Worker imports uxarray-mcp from: $UXARRAY_MCP_SRC"
  else
    UXARRAY_MCP_SRC="/lcrc/group/e3sm/$USER/uxarray-mcp-server"
    echo "==> Could not resolve the imported checkout; falling back to"
    echo "    $UXARRAY_MCP_SRC (override with UXARRAY_MCP_SRC=...)"
  fi
fi

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
  local before branch
  before="$(git -C "$dir" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  # A feature branch is not a mistake -- uxarray-yac-src deliberately tracks
  # unreleased YAC work -- but pulling it will not bring in a release, and a
  # bare "already current" invites the reader to think it did. Observed:
  # uxarray-yac-src on rajeeja/scrip-dask-lazy-dedup-2 reporting success while
  # the worker stayed on 2026.9.0 against a >=2026.9.1 floor.
  case "$branch" in
    main|master) ;;
    *) echo "    on branch '$branch', not main -- a pull follows that branch,"
       echo "    so a newer release will not arrive this way." ;;
  esac
  # A dirty checkout is a local experiment someone is mid-way through.
  # Clobbering it silently is how an afternoon of debugging disappears.
  if ! git -C "$dir" diff --quiet || ! git -C "$dir" diff --cached --quiet; then
    echo "    REFUSING: uncommitted changes. Commit, stash or discard first:"
    git -C "$dir" status --short | sed 's/^/      /'
    return
  fi
  # Not fatal: a detached head or a branch with no upstream is a normal
  # state for a checkout someone is working in, and the other repository
  # still deserves its turn. `set -e` would abandon the run here.
  if ! git -C "$dir" pull --ff-only; then
    echo "    pull did not succeed; leaving this checkout at $before"
    return
  fi
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

# A second clone that is not the one being imported is a trap: pulling it
# looks like success and changes nothing. Say so rather than leaving the
# next person to work it out from a version number that will not move.
for other in "/home/$USER/uxarray-mcp-server" "/lcrc/group/e3sm/$USER/uxarray-mcp-server"; do
  if [ -d "$other/.git" ] && [ "$(realpath "$other")" != "$(realpath "$UXARRAY_MCP_SRC")" ]; then
    echo "==> NOTE: another checkout exists at $other"
    echo "    ($(git -C "$other" rev-parse --short HEAD 2>/dev/null)) -- not the one the worker imports,"
    echo "    so pulling it would not change what runs."
  fi
done

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
