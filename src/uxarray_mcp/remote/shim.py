"""The single function shipped to a Globus Compute worker.

Globus serializes this function's source (AllCodeStrategies) and runs it on
the worker, which has ``uxarray`` and ``uxarray-mcp`` installed with
``--no-deps``. Everything scientific lives in ``uxarray_mcp.core``; this
function only dispatches to it and reports what ran. It must stay
self-contained: no module-level imports from this package, no closures.
"""

from __future__ import annotations

from typing import Any


def run_op(op: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Run ``uxarray_mcp.core.ops.call(op, **kwargs)`` on the worker."""
    import os
    import platform
    import socket
    import sys
    import time

    # YAC imports call MPI_Init, which reads PMI_* from a batch job that has
    # already exited and aborts the worker. Scrub before anything imports it.
    for key in ("PMI_FD", "PMI_RANK", "PMI_SIZE"):
        os.environ.pop(key, None)

    started = time.perf_counter()
    import uxarray

    from uxarray_mcp import __version__ as server_version
    from uxarray_mcp.core import ops

    result = ops.call(op, **kwargs)
    if not isinstance(result, dict):
        result = {"value": result}
    result["_worker"] = {
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "uxarray_version": getattr(uxarray, "__version__", None),
        "server_version": server_version,
        "python_executable": sys.executable,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "pbs_job_id": os.environ.get("PBS_JOBID"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    return result


def probe() -> dict[str, Any]:
    """Cheap worker probe: versions and node identity, no science."""
    import importlib.util
    import os
    import platform
    import socket
    import sys

    def version(name: str) -> str | None:
        spec = importlib.util.find_spec(name)
        if spec is None:
            return None
        try:
            return getattr(__import__(name), "__version__", "present")
        except Exception as exc:  # pragma: no cover - diagnostic path
            return f"import failed: {type(exc).__name__}"

    return {
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "uxarray_version": version("uxarray"),
        "server_version": version("uxarray_mcp"),
        "core_importable": importlib.util.find_spec("uxarray_mcp.core") is not None,
        "yac_available": importlib.util.find_spec("yac") is not None,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "pbs_job_id": os.environ.get("PBS_JOBID"),
    }
