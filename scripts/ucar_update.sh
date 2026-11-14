#!/usr/bin/env bash
# Bring the UCAR (Casper) worker up to the versions the submitter is running.
#
# Run this ON A CASPER LOGIN NODE, from a plain shell -- not from inside the
# endpoint's tmux session, whose environment is the worker's, not yours.
#
# Why this exists: scripts/ucar_endpoint.sh restart only replaces the worker
# processes. It contains no pip, no conda and no git, so it picks up whatever
# is already on disk and never changes a version. Chrysalis has
# chrysalis_update.sh for the other half of that job; UCAR had nothing, and
# the gap was filled by hand-typed pip lines that got it wrong.
#
# Unlike Chrysalis -- where the worker imports both packages from git
# checkouts under /lcrc -- the documented UCAR layout pip-installs into a
# conda env. Neither assumption is safe to hard-code, so this script asks the
# worker's own interpreter where each package actually resolves and updates
# whichever of the two it finds. See _resolve_repo below.
#
#   uxarray      <- git checkout if that is where it resolves, else PyPI
#   uxarray-mcp  <- likewise, but always installed --no-deps (see NO-DEPS)
#
# Usage:
#   ./scripts/ucar_update.sh            # update both, show versions
#   ./scripts/ucar_update.sh --restart  # also restart the endpoint
#   ./scripts/ucar_update.sh --dry-run  # report only, change nothing
set -euo pipefail

USERNAME="${NCAR_USERNAME:-$USER}"
CONDA_ENV="${CONDA_ENV:-/glade/work/$USERNAME/conda-envs/uxarray_312}"
PY="$CONDA_ENV/bin/python"

# Pin either package by exporting a full pip requirement specifier, e.g.
#   UXARRAY_SPEC='uxarray[geo,viz]==2026.10.1' ./scripts/ucar_update.sh
#
# The [geo,viz] extras are not optional for this server. Upstream 2026.9.1
# (UXARRAY/uxarray#1548) moved cartopy, healpix, hvplot and geopandas out of
# uxarray's required set and into extras, and pyproject.toml accordingly
# floors `uxarray[geo,viz]`. A bare `uxarray` installs and imports fine, then
# fails only when a tool reaches for coastlines or a HEALPix grid -- on the
# worker, mid-render, as a missing-module traceback.
UXARRAY_SPEC="${UXARRAY_SPEC:-uxarray[geo,viz]}"
UXARRAY_MCP_SPEC="${UXARRAY_MCP_SPEC:-uxarray-mcp}"

RESTART=0
DRY_RUN=0

for arg in "$@"; do
  case "$arg" in
    --restart) RESTART=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -x "$PY" ]; then
  echo "No interpreter at $PY" >&2
  echo "  Are you on a Casper login node? Override with CONDA_ENV=..." >&2
  exit 1
fi

echo "==> Worker env: $CONDA_ENV"
echo "==> Interpreter: $($PY -V 2>&1)"
echo

# ---------------------------------------------------------------------------
# Where does the worker actually import this from?
#
# Do not guess. The same package name can resolve to a git checkout on one
# facility and to site-packages on another, and updating the wrong one looks
# like success while the version number refuses to move -- the exact trap
# chrysalis_update.sh documents for its two uxarray-mcp clones.
#
# Prints the repository root when the package resolves inside a git checkout
# (both src-layout and flat layouts), and nothing otherwise.
# ---------------------------------------------------------------------------
_resolve_repo() {
  "$PY" - "$1" <<'PY' 2>/dev/null || true
import importlib.util, os, sys

name = sys.argv[1]
try:
    spec = importlib.util.find_spec(name)
except Exception:
    spec = None
origin = getattr(spec, "origin", None) or ""
if origin:
    pkg = os.path.dirname(origin)
    # .../<repo>/src/<pkg>/__init__.py  and  .../<repo>/<pkg>/__init__.py
    for cand in (os.path.dirname(os.path.dirname(pkg)), os.path.dirname(pkg)):
        if os.path.isdir(os.path.join(cand, ".git")):
            print(os.path.realpath(cand))
            break
PY
}

# ---------------------------------------------------------------------------
# Update a git checkout. Lifted from chrysalis_update.sh so the two scripts
# fail the same way; the guards below each cost someone an afternoon once.
# ---------------------------------------------------------------------------
_pull() {
  local dir="$1" name="$2"
  echo "==> $name: git checkout at $dir"
  local before branch after
  before="$(git -C "$dir" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  # A feature branch is not a mistake, but pulling it will not bring in a
  # release, and a bare "already current" invites the reader to think it did.
  case "$branch" in
    main|master) ;;
    *) echo "    on branch '$branch', not main -- a pull follows that branch,"
       echo "    so a newer release will not arrive this way." ;;
  esac
  # A dirty checkout is an experiment someone is mid-way through. Clobbering
  # it silently is how an afternoon of debugging disappears.
  if ! git -C "$dir" diff --quiet || ! git -C "$dir" diff --cached --quiet; then
    echo "    REFUSING: uncommitted changes. Commit, stash or discard first:"
    git -C "$dir" status --short | sed 's/^/      /'
    return
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "    [dry-run] would: git -C $dir pull --ff-only"
    return
  fi
  # Not fatal: a detached head or a branch with no upstream is a normal state
  # for a checkout someone works in, and the other package still deserves its
  # turn. `set -e` would abandon the run here.
  if ! git -C "$dir" pull --ff-only; then
    echo "    pull did not succeed; leaving this checkout at $before"
    return
  fi
  after="$(git -C "$dir" rev-parse --short HEAD)"
  if [ "$before" = "$after" ]; then
    echo "    already current at $after"
  else
    echo "    $before -> $after"
  fi
}

_pip_upgrade() {
  local spec="$1" name="$2"; shift 2
  echo "==> $name: site-packages install, upgrading from PyPI"
  if [ "$DRY_RUN" -eq 1 ]; then
    # Quoted in the echo too: the extras brackets are shell glob characters,
    # so an unquoted copy-paste of this line can silently install nothing.
    echo "    [dry-run] would: $PY -m pip install --upgrade $* '$spec'"
    return
  fi
  "$PY" -m pip install --upgrade "$@" "$spec"
}

_update() {
  local pkg="$1" spec="$2" name="$3"; shift 3
  local repo
  repo="$(_resolve_repo "$pkg")"
  if [ -n "$repo" ]; then
    _pull "$repo" "$name"
  else
    _pip_upgrade "$spec" "$name" "$@"
  fi
  echo
}

# ---------------------------------------------------------------------------
# NO-DEPS: why uxarray-mcp is installed without its dependency tree.
#
# The worker never runs the MCP server. The shim function is serialised by
# value (AllCodeStrategies) and does `from uxarray_mcp.core import ops` on the
# worker, so the package must be importable there -- but core/ only needs
# uxarray, numpy and matplotlib. Installing the full tree pulls mcp,
# toolregistry and toolregistry-server[mcp], whose pydantic pins conflict with
# the endpoint's, and the endpoint stops importing.
#
# --no-deps threads both: uxarray_mcp.core imports, nothing else is pulled
# in, and the stale `uxarray<2026.10` pin that an old uxarray-mcp carries is
# not enforced against a current uxarray. That pin is what produces
#
#   uxarray-mcp 2026.9.0 requires uxarray<2026.10,>=2026.9.0,
#   but you have uxarray 2026.10.0 which is incompatible
#
# Update uxarray-mcp FIRST so its metadata is current before uxarray moves,
# or pip reports the conflict against a pin that is about to be replaced.
# ---------------------------------------------------------------------------
_update uxarray_mcp "$UXARRAY_MCP_SPEC" "uxarray-mcp (core/ only, --no-deps)" --no-deps
_update uxarray     "$UXARRAY_SPEC"     "uxarray (the worker's compute library)"

echo "==> Versions the worker will now import"
# Report through the same interpreter worker_init puts first, so this agrees
# with the drift warning the submitter compares against.
"$PY" - <<'PY' || echo "    (could not query the worker interpreter)"
import importlib.metadata as md
import importlib.util
import sys

for name in ("uxarray", "xarray", "numpy", "matplotlib", "uxarray_mcp"):
    spec = importlib.util.find_spec(name)
    if spec is None:
        print(f"    {name:12} NOT IMPORTABLE")
        continue
    try:
        mod = __import__(name)
        ver = getattr(mod, "__version__", "?")
        print(f"    {name:12} {ver:12} {getattr(mod, '__file__', '?')}")
    except Exception as exc:
        print(f"    {name:12} IMPORT FAILED  {type(exc).__name__}: {exc}")

# What the shim imports on every remote call. An editable install can leave
# the distribution metadata behind the module, so report both.
try:
    import uxarray_mcp.core  # noqa: F401
    print(f"\n    uxarray_mcp.core importable; distribution metadata: {md.version('uxarray-mcp')}")
except Exception as exc:
    print(f"\n    uxarray_mcp.core / distribution: MISSING ({type(exc).__name__})")
    print("    Remote tool calls will fail with WORKER_MISSING_PACKAGE. Reinstall with:")
    print(f"      {sys.executable} -m pip install --no-deps uxarray-mcp")
PY

# `pip check` is deliberately not run here. It will always report
# toolregistry and toolregistry-server as missing, by design -- see NO-DEPS
# above -- and a red line that is expected every single time trains people to
# ignore the one that is not.

echo
if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry run: nothing was changed."
elif [ "$RESTART" -eq 1 ]; then
  echo "==> Restarting the endpoint so workers re-import"
  # Running workers hold the old modules in memory; an install alone changes
  # nothing until the processes are replaced.
  "$(dirname "$0")/ucar_endpoint.sh" restart
else
  echo "Installed, but running workers still hold the OLD code in memory."
  echo "Restart the endpoint to pick it up:"
  echo "    ./scripts/ucar_endpoint.sh restart"
fi
