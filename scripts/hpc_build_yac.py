#!/usr/bin/env python3
"""Build YAC + YAXT + Python bindings on a Globus Compute endpoint.

Mirrors the uxarray CI recipe (see uxarray/.github/workflows/yac-optional.yml):
  1. Clone YAXT, autoreconf if needed, configure with --without-regard-for-quality
  2. Clone YAC, configure with --disable-mci/utils/examples/tools/netcdf
     and --disable-mpi-checks, build python bindings against worker venv
  3. Verify by importing yac.core directly (bypasses the broken upstream
     yac/__init__.py which does `from ._yac import *` even though the
     extension installs as core.cpython-<abi>.so)

Defaults are tuned for the Improv endpoint at Argonne (ALCF/LCRC):
  * MPI: spack-built openmpi-5.0.1-g3zfkn6 (gcc-13.2.0)
  * GCC runtime libs: spack-built gcc-13.2.0-iyqxotb (needed in LD path
    because openmpi's .so links against it but the spack RPATH isn't
    on the worker's default ld search path)
  * --disable-mpi-checks because the worker has no mpiexec without a job
  * Python: /home/jain/venvs/globus-compute/bin/python (3.11)

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
    build_root: str = "/home/jain/build/yac",
    prefix: str = "/home/jain/yac",
    venv_python: str = "/home/jain/venvs/globus-compute/bin/python",
    mpi_root: str = "/gpfs/fs1/soft/improv/software/spack-built/linux-rhel8-zen3/gcc-13.2.0/openmpi-5.0.1-g3zfkn6",
    gcc_lib: str = "/gpfs/fs1/soft/improv/software/spack-built/linux-rhel8-x86_64/gcc-8.5.0/gcc-13.2.0-iyqxotb/lib64",
    yac_version: str = "v3.14.0_p1",
    yaxt_version: str = "v0.11.5.1",
    make_jobs: int = 8,
) -> Dict[str, Any]:
    """Build YAXT + YAC python bindings on the worker, mirroring uxarray CI."""
    import os
    import shlex
    import subprocess
    import time

    venv_bin = os.path.dirname(venv_python)
    script = f"""
set -euxo pipefail
export PATH={shlex.quote(venv_bin)}:{shlex.quote(mpi_root + "/bin")}:$PATH
export LD_LIBRARY_PATH={shlex.quote(mpi_root + "/lib")}:{shlex.quote(gcc_lib)}:${{LD_LIBRARY_PATH:-}}
export PREFIX={shlex.quote(prefix)}
export MPICC={shlex.quote(mpi_root + "/bin/mpicc")}
export MPIF90={shlex.quote(mpi_root + "/bin/mpif90")}
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

# --- runtime + verify ---
PY_VER=$(python -c 'import sys;print(f"{{sys.version_info.major}}.{{sys.version_info.minor}}")')
export LD_LIBRARY_PATH="$PREFIX/lib:$LD_LIBRARY_PATH"
export PYTHONPATH="$PREFIX/lib/python${{PY_VER}}/site-packages:$PREFIX/lib/python${{PY_VER}}/dist-packages:${{PYTHONPATH:-}}"
echo "PYTHONPATH=$PYTHONPATH"
python - <<'PY'
import sys
from pathlib import Path
hits = []
for entry in sys.path:
    p = Path(entry) / "yac"
    hits.extend(p.glob("core*.so"))
print("yac.core extension:", hits[:3])
import yac
print("yac module file:", getattr(yac, "__file__", None))
try:
    from uxarray.remap.yac import _import_yac
    yc = _import_yac()
    print("uxarray helper module:", yc.__name__, "file:", yc.__file__)
    print("has BasicGrid:", hasattr(yc, "BasicGrid"))
except Exception as e:
    print("uxarray helper error:", type(e).__name__, e)
PY
"""

    t0 = time.perf_counter()
    proc = subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        timeout=1800,
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
    p.add_argument("--build-root", default="/home/jain/build/yac")
    p.add_argument("--prefix", default="/home/jain/yac")
    p.add_argument(
        "--venv-python", default="/home/jain/venvs/globus-compute/bin/python"
    )
    p.add_argument(
        "--mpi-root",
        default="/gpfs/fs1/soft/improv/software/spack-built/linux-rhel8-zen3/gcc-13.2.0/openmpi-5.0.1-g3zfkn6",
    )
    p.add_argument(
        "--gcc-lib",
        default="/gpfs/fs1/soft/improv/software/spack-built/linux-rhel8-x86_64/gcc-8.5.0/gcc-13.2.0-iyqxotb/lib64",
    )
    p.add_argument("--yac-version", default="v3.14.0_p1")
    p.add_argument("--yaxt-version", default="v0.11.5.1")
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
        )
        result = future.result(timeout=args.timeout_seconds)
    finally:
        executor.shutdown(wait=False)

    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("exit_code") == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
