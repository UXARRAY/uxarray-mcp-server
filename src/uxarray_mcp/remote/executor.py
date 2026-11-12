"""Submit core operations to a Globus Compute endpoint.

One code path for every remote call: resolve the endpoint, record an
operation, submit ``shim.run_op``, wait up to the timeout. A call that
outlives the timeout is not an error -- the future keeps running and the
caller gets an ``operation_id`` to redeem with :func:`redeem`.
"""

from __future__ import annotations

import re
import threading
import time
import warnings
from concurrent.futures import Future
from typing import Any

from uxarray_mcp import __version__ as LOCAL_SERVER_VERSION
from uxarray_mcp.remote import shim
from uxarray_mcp.remote.config import HPCConfig, load_config

# Error codes a client can branch on. Messages explain; codes classify.
ENDPOINT_OFFLINE = "ENDPOINT_OFFLINE"
NO_WORKER = "NO_WORKER"
WORKER_LOST = "WORKER_LOST"
FILE_NOT_FOUND_ON_WORKER = "FILE_NOT_FOUND_ON_WORKER"
WORKER_MISSING_PACKAGE = "WORKER_MISSING_PACKAGE"
REMOTE_FAILED = "REMOTE_FAILED"
TIMEOUT_EXPIRED = "TIMEOUT_EXPIRED"
OPERATION_UNKNOWN = "OPERATION_UNKNOWN"
NOT_CONFIGURED = "NOT_CONFIGURED"

_ENV_DIFF_WARNING = (
    r"(?s).*Environment differences detected between local SDK and endpoint.*"
)


class RemoteError(RuntimeError):
    """A remote failure with a stable ``code`` and an ``operation_id``."""

    def __init__(self, code: str, message: str, operation_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.operation_id = operation_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "error",
            "error_code": self.code,
            "message": str(self),
            "operation_id": self.operation_id,
        }


class _Pending:
    """A submitted task the caller stopped waiting for."""

    def __init__(self, future: Future, op: str, endpoint: str, started: float):
        self.future = future
        self.op = op
        self.endpoint = endpoint
        self.started = started


_executors: dict[str, Any] = {}
_pending: dict[str, _Pending] = {}
_lock = threading.Lock()
_drift_reported: set[str] = set()


def _executor_for(config: HPCConfig) -> Any:
    """One Executor per endpoint id; rebuilt if Globus marked it stopped."""
    key = config.endpoint_id or ""
    with _lock:
        existing = _executors.get(key)
        if existing is not None and not getattr(existing, "_stopped", False):
            return existing
        from globus_compute_sdk import Executor
        from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

        serializer = ComputeSerializer(strategy_code=AllCodeStrategies())
        kwargs: dict[str, Any] = {"endpoint_id": key, "serializer": serializer}
        if config.user_endpoint_config is not None:
            kwargs["user_endpoint_config"] = config.user_endpoint_config
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=_ENV_DIFF_WARNING)
            executor = Executor(**kwargs)
        # Function registration serializes through the client, not the
        # executor; without this the worker would import its own copy by
        # reference instead of running the shipped source.
        client = getattr(executor, "client", None)
        if client is not None and hasattr(client, "fx_serializer"):
            client.fx_serializer = serializer
        _executors[key] = executor
        return executor


def _classify(exc: BaseException, endpoint: str) -> RemoteError:
    """Collapse a worker traceback into one typed, one-line error."""
    text = str(exc)
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    final = lines[-1] if lines else type(exc).__name__
    if "No such file or directory" in text or "FileNotFoundError" in text:
        match = re.search(r"['\"]([^'\"]+)['\"]", final)
        missing = match.group(1) if match else "the requested path"
        return RemoteError(
            FILE_NOT_FOUND_ON_WORKER,
            f"{missing} does not exist on {endpoint}. Check the path with "
            "endpoint(action='probe_path').",
        )
    if "No module named 'uxarray_mcp" in text or "No module named 'uxarray'" in text:
        return RemoteError(
            WORKER_MISSING_PACKAGE,
            f"The worker on {endpoint} cannot import uxarray-mcp or uxarray. "
            "Install on the worker env: pip install uxarray[geo,viz] && "
            "pip install --no-deps uxarray-mcp, then restart the endpoint.",
        )
    if "ENDPOINT_NOT_ONLINE" in text or "did not signal readiness" in text:
        return RemoteError(
            NO_WORKER,
            f"{endpoint} is registered but has no worker to run on. On a "
            "scheduler-backed endpoint the allocation has expired; retry in a "
            "minute.",
        )
    if "WorkerLost" in text or "loss of worker" in text:
        return RemoteError(
            WORKER_LOST,
            f"The worker on {endpoint} died running this task; usually the "
            "node's memory. Subset first or use a lighter operation.",
        )
    if len(text) > 600:
        return RemoteError(
            REMOTE_FAILED, f"Remote execution failed on {endpoint}: {final}"
        )
    return RemoteError(REMOTE_FAILED, f"Remote execution failed on {endpoint}: {text}")


def _drift_warnings(worker: dict[str, Any], endpoint: str) -> list[str]:
    """Version-skew warnings, each reported once per process per endpoint."""
    import uxarray

    out: list[str] = []
    pairs = (
        (
            "uxarray",
            getattr(uxarray, "__version__", None),
            worker.get("uxarray_version"),
        ),
        ("uxarray-mcp", LOCAL_SERVER_VERSION, worker.get("server_version")),
    )
    for name, local, remote in pairs:
        if local and remote and local != remote:
            key = f"{endpoint}:{name}:{local}:{remote}"
            if key in _drift_reported:
                continue
            _drift_reported.add(key)
            out.append(
                f"{name} version drift on {endpoint}: local {local}, worker {remote}. "
                "Update the worker env and restart the endpoint."
            )
    return out


def _finish(
    result: Any, operation_id: str, endpoint: str, elapsed: float
) -> dict[str, Any]:
    from uxarray_mcp.server.state import finalize_operation

    if not isinstance(result, dict):
        result = {"value": result}
    worker = result.pop("_worker", {}) or {}
    result["_remote"] = {
        "endpoint": endpoint,
        "operation_id": operation_id,
        "elapsed_seconds": round(elapsed, 2),
        "worker_elapsed_seconds": worker.get("elapsed_seconds"),
        "hostname": worker.get("hostname"),
        "python_version": worker.get("python_version"),
        "uxarray_version": worker.get("uxarray_version"),
        "server_version": worker.get("server_version"),
        "job_id": worker.get("slurm_job_id") or worker.get("pbs_job_id"),
    }
    drift = _drift_warnings(worker, endpoint)
    if drift:
        result.setdefault("warnings", []).extend(drift)
    finalize_operation(operation_id, status="completed", summary=f"{endpoint} ok")
    return result


def submit(
    op: str,
    kwargs: dict[str, Any],
    *,
    endpoint: str | None = None,
    path: str | None = None,
    timeout_seconds: int | None = None,
    session_id: str | None = None,
    config: HPCConfig | None = None,
) -> dict[str, Any]:
    """Run ``op`` on an endpoint and return its result or a running handle.

    Returns the operation result, or ``{"status": "running", "operation_id":
    ...}`` when ``timeout_seconds`` elapses first. Raises :class:`RemoteError`
    for anything the worker could not do.
    """
    from uxarray_mcp.server.state import create_operation, record_task_handle

    base = config or load_config()
    resolved = base.for_endpoint(endpoint=endpoint, path=path)
    if not resolved.endpoint_id:
        raise RemoteError(
            NOT_CONFIGURED,
            "No Globus Compute endpoint is configured. Run `uxarray-mcp endpoints "
            "add <name> <uuid> --path-prefix /...` or pass endpoint=.",
        )
    name = resolved.endpoint_name or resolved.endpoint_id
    timeout = timeout_seconds or resolved.timeout_seconds

    record = create_operation(
        tool_name=op, session_id=session_id, endpoint_id=resolved.endpoint_id
    )
    operation_id = record["operation_id"]
    started = time.monotonic()
    try:
        executor = _executor_for(resolved)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=_ENV_DIFF_WARNING)
            future = executor.submit(shim.run_op, op, kwargs)
    except Exception as exc:
        err = _classify(exc, name)
        err.operation_id = operation_id
        _fail(operation_id, err)
        raise err from None

    task_id = getattr(future, "task_id", None)
    if task_id:
        record_task_handle(
            operation_id, task_id=task_id, endpoint_id=resolved.endpoint_id
        )
    try:
        result = future.result(timeout=timeout)
    except TimeoutError:
        with _lock:
            _pending[operation_id] = _Pending(future, op, name, started)
        return {
            "status": "running",
            "operation_id": operation_id,
            "endpoint": name,
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "message": (
                f"{op} is still running on {name} after {timeout}s. Call "
                f"get_operation(operation_id='{operation_id}') to collect it."
            ),
        }
    except Exception as exc:
        err = _classify(exc, name)
        err.operation_id = operation_id
        _fail(operation_id, err)
        raise err from None
    return _finish(result, operation_id, name, time.monotonic() - started)


def redeem(operation_id: str, wait_seconds: float = 0) -> dict[str, Any]:
    """Collect a task that outlived its caller's timeout."""
    from uxarray_mcp.server.state import get_operation

    with _lock:
        pending = _pending.get(operation_id)
    if pending is None:
        try:
            record = get_operation(operation_id)
        except FileNotFoundError:
            raise RemoteError(OPERATION_UNKNOWN, f"Unknown operation {operation_id!r}.")
        return {"status": record.get("status"), "operation": record}
    try:
        result = pending.future.result(timeout=wait_seconds)
    except TimeoutError:
        return {
            "status": "running",
            "operation_id": operation_id,
            "endpoint": pending.endpoint,
            "elapsed_seconds": round(time.monotonic() - pending.started, 1),
        }
    except Exception as exc:
        err = _classify(exc, pending.endpoint)
        err.operation_id = operation_id
        _fail(operation_id, err)
        with _lock:
            _pending.pop(operation_id, None)
        raise err from None
    with _lock:
        _pending.pop(operation_id, None)
    return _finish(
        result, operation_id, pending.endpoint, time.monotonic() - pending.started
    )


def probe(endpoint: str | None = None, timeout_seconds: int = 60) -> dict[str, Any]:
    """Run :func:`shim.probe` on the worker and time the round trip."""
    resolved = load_config().for_endpoint(endpoint=endpoint)
    if not resolved.endpoint_id:
        raise RemoteError(NOT_CONFIGURED, "No endpoint configured.")
    name = resolved.endpoint_name or resolved.endpoint_id
    started = time.monotonic()
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=_ENV_DIFF_WARNING)
            future = _executor_for(resolved).submit(shim.probe)
        info = future.result(timeout=timeout_seconds)
    except TimeoutError:
        raise RemoteError(
            TIMEOUT_EXPIRED,
            f"No worker on {name} answered within {timeout_seconds}s. The "
            "manager may be up while the scheduler has granted no node yet.",
        )
    except Exception as exc:
        raise _classify(exc, name) from None
    info["round_trip_seconds"] = round(time.monotonic() - started, 1)
    info["endpoint"] = name
    return info


def _fail(operation_id: str, err: RemoteError) -> None:
    from uxarray_mcp.server.state import finalize_operation

    try:
        finalize_operation(operation_id, status="failed", summary=f"{err.code}: {err}")
    except Exception:  # pragma: no cover - state dir unwritable
        pass


def reset() -> None:
    """Drop cached executors and pending tasks (tests)."""
    with _lock:
        _executors.clear()
        _pending.clear()
        _drift_reported.clear()
