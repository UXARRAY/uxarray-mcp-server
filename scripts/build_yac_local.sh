#!/usr/bin/env bash
# Build YAC + YAXT with Python bindings on a laptop or workstation.
#
# The HPC twin of this script is scripts/hpc_build_yac.py, which runs the same
# recipe on a Globus Compute worker. Same versions, same configure flags; this
# one finds the toolchain locally instead of taking it as spack paths or
# module names.
#
# Versions track uxarray's own CI (.github/workflows/yac-optional.yml) rather
# than the newest upstream tag -- that pairing is the one that is tested.
#
#   ./scripts/build_yac_local.sh                     # build and install
#   ./scripts/build_yac_local.sh --prefix ~/opt/yac  # somewhere else
#   ./scripts/build_yac_local.sh --check             # preflight only
#
# Afterwards, either source the generated activate file:
#   source ~/opt/yac-<version>/activate-yac.sh
# or make it the default for one interpreter with a .pth file, as the README
# describes.
set -euo pipefail

YAC_VERSION="v3.20.2"
YAXT_VERSION="v0.11.5.1"
PREFIX=""
BUILD_ROOT=""
PYTHON="${PYTHON:-}"
JOBS=""
CHECK_ONLY=0

usage() {
  cat <<'EOF'
Usage: build_yac_local.sh [options]

  --prefix DIR        Install prefix (default: ~/opt/yac-<version>)
  --build-root DIR    Scratch build tree (default: ~/build/yac-<version>)
  --python PATH       Interpreter to build bindings against (default: python3)
  --yac-version TAG   YAC git tag (default: v3.20.2)
  --yaxt-version TAG  YAXT git tag (default: v0.11.5.1)
  --jobs N            Parallel make jobs (default: detected core count)
  --check             Run preflight checks and exit without building
  -h, --help          This message

Supported: macOS (Homebrew), Debian/Ubuntu, RHEL/Fedora/Rocky, Arch, SUSE.
Missing prerequisites are reported with the install command for your platform;
nothing is installed for you.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)        PREFIX="$2"; shift 2 ;;
    --build-root)    BUILD_ROOT="$2"; shift 2 ;;
    --python)        PYTHON="$2"; shift 2 ;;
    --yac-version)   YAC_VERSION="$2"; shift 2 ;;
    --yaxt-version)  YAXT_VERSION="$2"; shift 2 ;;
    --jobs)          JOBS="$2"; shift 2 ;;
    --check)         CHECK_ONLY=1; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

_version_no_v="${YAC_VERSION#v}"
PREFIX="${PREFIX:-$HOME/opt/yac-$_version_no_v}"
BUILD_ROOT="${BUILD_ROOT:-$HOME/build/yac-$_version_no_v}"
PYTHON="${PYTHON:-python3}"

OS="$(uname -s)"

# ---------------------------------------------------------------------------
# Platform-specific install hints. Reported, never run -- installing system
# packages is the user's call, not this script's.
# ---------------------------------------------------------------------------

_pkg_hint() {
  # $1 = one of: mpi, fortran, autotools, git
  local what="$1"
  if [[ "$OS" == "Darwin" ]]; then
    case "$what" in
      mpi)       echo "brew install open-mpi" ;;
      fortran)   echo "brew install gcc" ;;
      autotools) echo "brew install autoconf automake libtool" ;;
      git)       echo "xcode-select --install" ;;
    esac
    return
  fi
  if command -v apt-get &>/dev/null; then
    case "$what" in
      mpi)       echo "sudo apt-get install libopenmpi-dev openmpi-bin" ;;
      fortran)   echo "sudo apt-get install gfortran" ;;
      autotools) echo "sudo apt-get install autoconf automake libtool" ;;
      git)       echo "sudo apt-get install git" ;;
    esac
  elif command -v dnf &>/dev/null || command -v yum &>/dev/null; then
    local mgr; mgr="$(command -v dnf &>/dev/null && echo dnf || echo yum)"
    case "$what" in
      # RHEL-family puts the MPI wrappers behind a module rather than on PATH.
      mpi)       echo "sudo $mgr install openmpi-devel  &&  module load mpi/openmpi-x86_64" ;;
      fortran)   echo "sudo $mgr install gcc-gfortran" ;;
      autotools) echo "sudo $mgr install autoconf automake libtool" ;;
      git)       echo "sudo $mgr install git" ;;
    esac
  elif command -v pacman &>/dev/null; then
    case "$what" in
      mpi)       echo "sudo pacman -S openmpi" ;;
      fortran)   echo "sudo pacman -S gcc-fortran" ;;
      autotools) echo "sudo pacman -S autoconf automake libtool" ;;
      git)       echo "sudo pacman -S git" ;;
    esac
  elif command -v zypper &>/dev/null; then
    case "$what" in
      mpi)       echo "sudo zypper install openmpi-devel" ;;
      fortran)   echo "sudo zypper install gcc-fortran" ;;
      autotools) echo "sudo zypper install autoconf automake libtool" ;;
      git)       echo "sudo zypper install git" ;;
    esac
  else
    echo "install $what with your package manager"
  fi
}

_missing=0
_need() {
  # $1 = command, $2 = hint key
  if ! command -v "$1" &>/dev/null; then
    echo "MISSING: $1" >&2
    echo "  try: $(_pkg_hint "$2")" >&2
    _missing=1
    return 1
  fi
  return 0
}

_detect_jobs() {
  if [[ -n "$JOBS" ]]; then echo "$JOBS"; return; fi
  if [[ "$OS" == "Darwin" ]]; then sysctl -n hw.ncpu 2>/dev/null || echo 4
  else nproc 2>/dev/null || echo 4
  fi
}

# Some distros ship the wrappers only as mpicc.openmpi / mpifort. Accept any
# of the usual spellings rather than insisting on one.
_first_of() {
  local c
  for c in "$@"; do
    if command -v "$c" &>/dev/null; then command -v "$c"; return 0; fi
  done
  return 1
}

_fc_accepts() {
  # gfortran >= 10 rejects the argument-mismatch patterns YAXT relies on
  # unless told not to; older gfortran and non-GNU compilers reject the flag
  # itself. Ask the compiler instead of guessing from a version string.
  local tmpd flag rc
  flag="$1"
  tmpd="$(mktemp -d)"
  printf 'end\n' > "$tmpd/probe.f90"
  "$MPIF90" "$flag" -fsyntax-only "$tmpd/probe.f90" >/dev/null 2>&1
  rc=$?
  rm -rf "$tmpd"
  return $rc
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

echo "==> Preflight (${OS})"

_need git git || true
_need make autotools || true

if ! MPICC="$(_first_of mpicc mpicc.openmpi mpicc.mpich)"; then
  echo "MISSING: mpicc" >&2
  echo "  try: $(_pkg_hint mpi)" >&2
  _missing=1
fi
if ! MPIF90="$(_first_of mpif90 mpifort mpif90.openmpi mpifort.openmpi)"; then
  echo "MISSING: mpif90 (or mpifort)" >&2
  echo "  try: $(_pkg_hint mpi)" >&2
  _missing=1
fi

if ! command -v gfortran &>/dev/null && [[ -z "${MPIF90:-}" ]]; then
  echo "MISSING: gfortran" >&2
  echo "  try: $(_pkg_hint fortran)" >&2
  _missing=1
fi

if ! command -v "$PYTHON" &>/dev/null; then
  echo "MISSING: python interpreter '$PYTHON'" >&2
  echo "  pass one with --python /path/to/python" >&2
  _missing=1
else
  PYTHON="$(command -v "$PYTHON")"
  # The bindings are Cython-built against this interpreter, and YAC's
  # configure checks for both of these by name.
  for _mod in "cython>=3.0.0" "mpi4py"; do
    if ! "$PYTHON" -c "
import sys
from importlib.metadata import version, PackageNotFoundError
name = '$_mod'.split('>=')[0]
try:
    version(name)
except PackageNotFoundError:
    sys.exit(1)
" 2>/dev/null; then
      echo "MISSING: python module $_mod (for $PYTHON)" >&2
      echo "  try: $PYTHON -m pip install '$_mod'" >&2
      _missing=1
    fi
  done
fi

if [[ "$_missing" -ne 0 ]]; then
  echo >&2
  echo "Preflight failed. Install the above, then re-run." >&2
  exit 1
fi

JOBS="$(_detect_jobs)"
FCFLAGS_BASE="-O2"
if _fc_accepts -fallow-argument-mismatch; then
  FCFLAGS_BASE="-fallow-argument-mismatch $FCFLAGS_BASE"
fi

echo "  python : $PYTHON ($("$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])'))"
echo "  mpicc  : $MPICC"
echo "  mpif90 : $MPIF90"
echo "  fcflags: $FCFLAGS_BASE"
echo "  jobs   : $JOBS"
echo "  prefix : $PREFIX"
echo "  yac    : $YAC_VERSION / yaxt $YAXT_VERSION"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "==> Preflight OK (--check, not building)"
  exit 0
fi

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

export MPICC MPIF90
export FCFLAGS="$FCFLAGS_BASE"

_bootstrap() {
  # Release tarballs ship configure; git checkouts do not.
  if [[ ! -x configure ]]; then
    if [[ -x autogen.sh ]]; then ./autogen.sh; else autoreconf -i; fi
  fi
}

mkdir -p "$BUILD_ROOT"
cd "$BUILD_ROOT"

echo "==> YAXT $YAXT_VERSION"
rm -rf yaxt-fresh
git clone --depth 1 --branch "$YAXT_VERSION" https://gitlab.dkrz.de/dkrz-sw/yaxt.git yaxt-fresh
cd yaxt-fresh
_bootstrap
mkdir -p build && cd build
../configure --prefix="$PREFIX" --without-regard-for-quality \
    CC="$MPICC" FC="$MPIF90" FCFLAGS="$FCFLAGS"
make -j"$JOBS"
make install
cd "$BUILD_ROOT"

echo "==> YAC $YAC_VERSION"
rm -rf yac-fresh
git clone --depth 1 --branch "$YAC_VERSION" https://gitlab.dkrz.de/dkrz-sw/yac.git yac-fresh
cd yac-fresh
_bootstrap
mkdir -p build && cd build
# netcdf/MCI/utils/examples/tools are all unused by uxarray's remapping path;
# skipping them drops a pile of optional dependencies. --disable-mpi-checks
# because configure's MPI probes want to launch processes.
../configure --prefix="$PREFIX" --with-yaxt-root="$PREFIX" \
    --disable-mci --disable-utils --disable-examples --disable-tools --disable-netcdf \
    --disable-mpi-checks \
    --enable-python-bindings PYTHON="$PYTHON" \
    CC="$MPICC" FC="$MPIF90" FCFLAGS="$FCFLAGS"
make -j"$JOBS"
make install

# ---------------------------------------------------------------------------
# Activate file + verification
# ---------------------------------------------------------------------------

PY_VER="$("$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
SITE="$PREFIX/lib/python$PY_VER/site-packages"
if [[ "$OS" == "Darwin" ]]; then LIBVAR="DYLD_LIBRARY_PATH"; else LIBVAR="LD_LIBRARY_PATH"; fi

cat > "$PREFIX/activate-yac.sh" <<EOF
# Generated by build_yac_local.sh for YAC $_version_no_v -- safe to delete.
export PYTHONPATH="$SITE:\${PYTHONPATH:-}"
export $LIBVAR="$PREFIX/lib:\${$LIBVAR:-}"
EOF

echo "==> Installed"
find "$PREFIX" \( -name 'core*.so' -o -name '_yac*.so' \) -print
echo "  activate: source $PREFIX/activate-yac.sh"

echo "==> Verifying import"
# Importing yac calls MPI_Init. Open MPI initialises fine as a singleton;
# MPICH usually wants a launcher and aborts with `PMI_Get_appnum returned -1`.
# A failure here is therefore not evidence of a bad build, so retry under
# mpirun before saying anything, and never fail the script on it.
_verify() {
  PYTHONPATH="$SITE" "$@" "$PYTHON" -c \
    'import yac.core as c; print("  YAC OK:", c.__file__); print("  BasicGrid:", hasattr(c, "BasicGrid"))'
}
if _verify 2>/dev/null; then
  :
elif command -v mpirun &>/dev/null && _verify mpirun -n 1 2>/dev/null; then
  echo "  (needed a launcher: import under 'mpirun -n 1')"
else
  echo "  Could not import yac here, but the build artifacts above are installed."
  echo "  This is expected with MPICH outside a launcher. Try:"
  echo "    source $PREFIX/activate-yac.sh && mpirun -n 1 $PYTHON -c 'import yac.core'"
fi
