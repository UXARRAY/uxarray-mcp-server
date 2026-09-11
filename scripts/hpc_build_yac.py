#!/usr/bin/env python3
"""Build YAC + YAXT + Python bindings on a Globus Compute endpoint.

Mirrors the uxarray CI recipe (see uxarray/.github/workflows/yac-optional.yml):
  1. Clone YAXT, autoreconf if needed, configure with --without-regard-for-quality
  2. Clone YAC, configure with --disable-mci/utils/examples/tools/netcdf
     and --disable-mpi-checks, build python bindings against worker venv
  3. Verify that the libraries, headers and extension modules landed. This
     stops short of importing yac: the extension calls MPI_Init, and a Globus
     Compute worker is not an MPI rank, so the import aborts regardless of
     build quality. Confirm the build under a launcher instead, with
     remote_yac_remap_smoke.

Toolchains reach this two ways. Sites with a readable spack prefix pass
--mpi-root/--gcc-lib; Lmod sites that publish MPI only through modules pass
--module-loads and let the compiler wrappers name themselves.

Defaults are tuned for the Improv endpoint at Argonne (ALCF/LCRC):
  * MPI: spack-built openmpi-5.0.1-g3zfkn6 (gcc-13.2.0)
  * GCC runtime libs: spack-built gcc-13.2.0-iyqxotb (needed in LD path
    because openmpi's .so links against it but the spack RPATH isn't
    on the worker's default ld search path)
  * --disable-mpi-checks because the worker has no mpiexec without a job
  * Python: the endpoint's Globus Compute venv interpreter, passed with
    --venv-python (for example ~/venvs/globus-compute/bin/python)

For other endpoints, override via --mpi-root, --gcc-lib, --venv-python, etc.
The shape of the build is the same — the locations differ.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from globus_compute_sdk import Executor
from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

from uxarray_mcp.remote.config import load_config


def remote_build_yac(
    *,
    build_root: str = "~/build/yac",
    prefix: str = "~/yac",
    venv_python: str = "~/venvs/globus-compute/bin/python",
    mpi_root: str = "/gpfs/fs1/soft/improv/software/spack-built/linux-rhel8-zen3/gcc-13.2.0/openmpi-5.0.1-g3zfkn6",
    gcc_lib: str = "/gpfs/fs1/soft/improv/software/spack-built/linux-rhel8-x86_64/gcc-8.5.0/gcc-13.2.0-iyqxotb/lib64",
    yac_version: str = "v3.20.2",
    yaxt_version: str = "v0.11.5.1",
    make_jobs: int = 8,
    module_loads: str = "",
    timeout_seconds: int = 1800,
) -> Dict[str, Any]:
    """Build YAXT + YAC python bindings on the worker, mirroring uxarray CI."""
    import os
    import shlex
    import subprocess
    import time

    # ``~`` must expand against the *worker's* home, not the submitter's.
    build_root = os.path.expanduser(build_root)
    prefix = os.path.expanduser(prefix)
    venv_python = os.path.expanduser(venv_python)
    venv_bin = os.path.dirname(venv_python)

    if module_loads:
        # Lmod sites (Casper) publish MPI only through modules; there is no
        # readable spack prefix to point --mpi-root at, and any path guessed
        # from one moves at the next site upgrade. Load the modules and let
        # the compiler wrappers name themselves.
        loads = "\n".join(f"module load {shlex.quote(m)}" for m in module_loads.split())
        toolchain = f"""
for _init in /usr/share/lmod/lmod/init/bash /etc/profile.d/lmod.sh \\
             /glade/u/apps/opt/lmod/init/bash; do
  [ -f "$_init" ] && . "$_init" && break
done
module purge
{loads}
export PATH={shlex.quote(venv_bin)}:$PATH
export MPICC=$(command -v mpicc)
export MPIF90=$(command -v mpif90)
"""
    else:
        toolchain = f"""
export PATH={shlex.quote(venv_bin)}:{shlex.quote(mpi_root + "/bin")}:$PATH
export LD_LIBRARY_PATH={shlex.quote(mpi_root + "/lib")}:{shlex.quote(gcc_lib)}:${{LD_LIBRARY_PATH:-}}
export MPICC={shlex.quote(mpi_root + "/bin/mpicc")}
export MPIF90={shlex.quote(mpi_root + "/bin/mpif90")}
"""

    script = f"""
set -euxo pipefail
{toolchain}
export PREFIX={shlex.quote(prefix)}
export FCFLAGS="-fallow-argument-mismatch -O2"
which python && python --version
which $MPICC && $MPICC --version | head -1
which $MPIF90 && $MPIF90 --version | head -1

mkdir -p {shlex.quote(build_root)} && cd {shlex.quote(build_root)}

# --- YAXT (force fresh clone) ---
rm -rf yaxt-fresh
git clone --depth 1 --branch {shlex.quote(yaxt_version)} https://gitlab.dkrz.de/dkrz-sw/yaxt.git yaxt-fresh
cd yaxt-fresh
if [ ! -x configure ]; then
  if [ -x autogen.sh ]; then ./autogen.sh; else autoreconf -i; fi
fi
mkdir -p build && cd build
../configure --prefix="$PREFIX" --without-regard-for-quality \\
    CC="$MPICC" FC="$MPIF90" FCFLAGS="$FCFLAGS"
make -j{int(make_jobs)}
make install
cd {shlex.quote(build_root)}

# --- YAC (force fresh clone) ---
rm -rf yac-fresh
git clone --depth 1 --branch {shlex.quote(yac_version)} https://gitlab.dkrz.de/dkrz-sw/yac.git yac-fresh
cd yac-fresh
if [ ! -x configure ]; then
  if [ -x autogen.sh ]; then ./autogen.sh; else autoreconf -i; fi
fi
mkdir -p build && cd build
../configure --prefix="$PREFIX" --with-yaxt-root="$PREFIX" \\
    --disable-mci --disable-utils --disable-examples --disable-tools --disable-netcdf \\
    --disable-mpi-checks \\
    --enable-python-bindings PYTHON={shlex.quote(venv_python)} \\
    CC="$MPICC" FC="$MPIF90" FCFLAGS="$FCFLAGS"
make -j{int(make_jobs)}
make install

# --- verify the install, as far as this host can ---
# Deliberately does NOT `import yac`. The extension calls MPI_Init, and a
# Globus Compute worker is not started under a launcher, so the import aborts
# with `PMI_Get_appnum returned -1` however good the build is -- reporting a
# clean build as a failure. Same reason remote_runtime_probe skips its own
# native import check. Confirm the artifacts here; confirm the import under
# srun with remote_yac_remap_smoke.
PY_VER=$(python -c 'import sys;print(f"{{sys.version_info.major}}.{{sys.version_info.minor}}")')
echo "PY_VER=$PY_VER"
ls -1 "$PREFIX/lib" | head -20
find "$PREFIX" \\( -name 'core*.so' -o -name '_yac*.so' \\) -print
find "$PREFIX" -name 'yac-core.pc' -print
echo "BUILD_AND_INSTALL_OK prefix=$PREFIX"
"""

    t0 = time.perf_counter()
    proc = subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    elapsed = time.perf_counter() - t0

    return {
        "exit_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-200:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-200:]),
        "host": os.uname().nodename,
        "cwd": os.getcwd(),
        "prefix": prefix,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", default="improv")
    p.add_argument("--build-root", default="~/build/yac")
    p.add_argument("--prefix", default="~/yac")
    p.add_argument("--venv-python", default="~/venvs/globus-compute/bin/python")
    p.add_argument(
        "--mpi-root",
        default="/gpfs/fs1/soft/improv/software/spack-built/linux-rhel8-zen3/gcc-13.2.0/openmpi-5.0.1-g3zfkn6",
    )
    p.add_argument(
        "--gcc-lib",
        default="/gpfs/fs1/soft/improv/software/spack-built/linux-rhel8-x86_64/gcc-8.5.0/gcc-13.2.0-iyqxotb/lib64",
    )
    p.add_argument("--yac-version", default="v3.20.2")
    p.add_argument("--yaxt-version", default="v0.11.5.1")
    p.add_argument(
        "--module-loads",
        default="",
        help=(
            "Space-separated Lmod modules to load instead of using "
            "--mpi-root/--gcc-lib, e.g. 'ncarenv/24.12 gcc/12.4.0 openmpi/5.0.6'"
        ),
    )
    p.add_argument("--make-jobs", type=int, default=8)
    p.add_argument("--timeout-seconds", type=int, default=1800)
    args = p.parse_args()

    cfg = load_config().for_endpoint(endpoint=args.endpoint)
    if not cfg.endpoint_id:
        print(f"No endpoint_id resolved for {args.endpoint!r}", file=sys.stderr)
        return 2

    print(
        f"Submitting remote_build_yac to endpoint {args.endpoint} "
        f"({cfg.endpoint_id}) ...",
        file=sys.stderr,
    )

    executor = Executor(
        endpoint_id=cfg.endpoint_id,
        serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
    )
    try:
        future = executor.submit(
            remote_build_yac,
            build_root=args.build_root,
            prefix=args.prefix,
            venv_python=args.venv_python,
            mpi_root=args.mpi_root,
            gcc_lib=args.gcc_lib,
            yac_version=args.yac_version,
            yaxt_version=args.yaxt_version,
            make_jobs=args.make_jobs,
            module_loads=args.module_loads,
            # Give the worker-side kill a margin under the client-side wait,
            # so a hung build returns a captured tail instead of a bare
            # TimeoutError with no output.
            timeout_seconds=max(60, args.timeout_seconds - 120),
        )
        result = future.result(timeout=args.timeout_seconds)
    finally:
        executor.shutdown(wait=False)

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("exit_code") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
