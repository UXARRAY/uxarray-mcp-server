"""Endpoint manager status checking for HPC execution.

## Status vocabulary

Every function in this module returns one of four manager-level statuses:

``"registered"``
    The endpoint manager process is running and visible to Globus Compute.
    Slurm/PBS jobs will be submitted when tasks arrive. Workers are not
    necessarily running yet — the scheduler allocates them on demand.
    This was formerly reported as ``"online"`` by the Globus SDK.

``"active"``
    Manager is registered AND a lightweight probe task ran successfully on a
    real compute node. Use :func:`probe_endpoint_worker` to obtain this status.

``"offline"``
    The endpoint manager is not running. Someone must SSH in and run
    ``globus-compute-endpoint start <name>``.

``"unreachable"``
    The Globus Compute service cannot be contacted (auth error, network issue).

``"no_endpoint"``
    No endpoint UUID is configured for this name.

## Why "registered" not "online"

Globus reports ``"online"`` when the manager process is registered. This is
purely a registration state — it says nothing about whether Slurm has idle
nodes, whether the worker environment is healthy, or whether submitted tasks
will actually run. Using ``"online"`` led to misleading status messages.
``"registered"`` is honest: the manager is up and accepting submissions.

## Caching

The Globus Compute ``Client()`` constructor and ``get_endpoint_status()`` are
both network round-trips that take 1–5 s. This module keeps a process-level
Client cache plus a short-TTL per-endpoint status cache so back-to-back checks
are effectively free.
"""

from __future__ import annotations

import threading
import time
import warnings
from typing import Any

# ── Process-wide cached Client ────────────────────────────────────────────────
_CLIENT: Any = None
_CLIENT_LOCK = threading.Lock()

# ── Per-endpoint status cache ─────────────────────────────────────────────────
# Keyed by endpoint_id; value is (monotonic_ts, status_dict).
# The stored dict never contains "cached"/"cache_age_seconds" — those are
# added on the way out by _cached_entry().
_STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_STATUS_CACHE_LOCK = threading.Lock()

# Registered endpoints stay valid longer; offline/unreachable are re-checked sooner.
_TTL_REGISTERED_SECONDS = 10.0
_TTL_OTHER_SECONDS = 3.0

# ── Globus → our vocabulary mapping ──────────────────────────────────────────
_GLOBUS_TO_STATUS: dict[str, str] = {
    "online": "registered",
    "healthy": "registered",
    "offline": "offline",
    "stopped": "offline",
}


def _translate_globus_status(raw: str) -> str:
    """Map a raw Globus status string to our vocabulary."""
    return _GLOBUS_TO_STATUS.get(raw.lower(), "unreachable")


def _endpoint_public_fields(config: Any) -> dict[str, Any]:
    """Return non-sensitive endpoint metadata for public tool payloads."""
    return {
        "endpoint_name": getattr(config, "endpoint_name", None) or "configured",
        "endpoint_configured": bool(getattr(config, "endpoint_id", None)),
    }


def _get_client() -> Any:
    """Return a process-wide cached Globus Compute ``Client``."""
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                from globus_compute_sdk import Client

                _CLIENT = Client()
    return _CLIENT


def invalidate_cache(endpoint_id: str | None = None) -> None:
    """Drop cached status entries.

    Parameters
    ----------
    endpoint_id : str | None
        If ``None``, clear the entire cache. The cached Client is preserved.
    """
    with _STATUS_CACHE_LOCK:
        if endpoint_id is None:
            _STATUS_CACHE.clear()
        else:
            _STATUS_CACHE.pop(endpoint_id, None)


def _cached_entry(endpoint_id: str) -> dict[str, Any] | None:
    with _STATUS_CACHE_LOCK:
        entry = _STATUS_CACHE.get(endpoint_id)
    if entry is None:
        return None
    ts, payload = entry
    age = time.monotonic() - ts
    ttl = (
        _TTL_REGISTERED_SECONDS
        if payload.get("status") == "registered"
        else _TTL_OTHER_SECONDS
    )
    if age > ttl:
        return None
    cached = dict(payload)
    cached["cached"] = True
    cached["cache_age_seconds"] = round(age, 3)
    return cached


def _store(endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _STATUS_CACHE_LOCK:
        _STATUS_CACHE[endpoint_id] = (time.monotonic(), payload)
    fresh = dict(payload)
    fresh["cached"] = False
    return fresh


def check_endpoint_manager_status(
    config: Any, *, force: bool = False
) -> dict[str, Any]:
    """Check whether the Globus Compute endpoint manager is registered.

    This is a fast, cached check that queries the Globus cloud about the
    manager process. It does **not** verify that workers are running or that
    submitted tasks will succeed.

    Parameters
    ----------
    config : HPCConfig
        HPC configuration with ``endpoint_id``.
    force : bool, default False
        Bypass the short-TTL cache and re-query the SDK.

    Returns
    -------
    dict
        Keys:

        ``status``
            One of ``"registered"``, ``"offline"``, ``"unreachable"``,
            ``"no_endpoint"``.
        ``endpoint_name`` / ``endpoint_configured``
            Non-sensitive endpoint metadata. Raw UUIDs stay in private config.
        ``error``
            Error message when ``status`` is ``"unreachable"``.
        ``cached``
            ``True`` if this result was served from the in-process cache.
        ``cache_age_seconds``
            Age of the cached entry in seconds (only when ``cached=True``).

    Examples
    --------
    >>> from uxarray_mcp.remote.config import load_config
    >>> config = load_config()
    >>> check_endpoint_manager_status(config)
    {"status": "registered", "endpoint_name": "improv", "cached": False}
    """
    endpoint_id = getattr(config, "endpoint_id", None)
    if not endpoint_id:
        return {"status": "no_endpoint", "message": "No endpoint configured"}

    if not force:
        cached = _cached_entry(endpoint_id)
        if cached is not None:
            return cached

    try:
        client = _get_client()
        raw = client.get_endpoint_status(endpoint_id)
        raw_status = raw.get("status", "unknown") if isinstance(raw, dict) else str(raw)
        status = _translate_globus_status(raw_status)
        payload: dict[str, Any] = {"status": status, **_endpoint_public_fields(config)}
        return _store(endpoint_id, payload)
    except Exception as exc:
        payload = {
            "status": "unreachable",
            **_endpoint_public_fields(config),
            "error": str(exc),
        }
        return _store(endpoint_id, payload)


def probe_endpoint_worker(
    config: Any,
    *,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Submit a lightweight task to confirm a real worker responds.

    Unlike :func:`check_endpoint_manager_status`, this function actually
    submits a task via Globus Compute and waits for it to run on a scheduler
    node. This is the only way to confirm that Slurm/PBS allocated a worker
    and the Python environment is intact.

    Parameters
    ----------
    config : HPCConfig
        HPC configuration with ``endpoint_id``.
    timeout_seconds : int, default 60
        How long to wait for the probe task to complete.

    Returns
    -------
    dict
        Keys:

        ``status``
            ``"active"`` if a worker responded, ``"registered"`` if the
            manager is up but the probe timed out, ``"offline"`` or
            ``"unreachable"`` if the manager itself is down.
        ``node``
            Hostname of the compute node that ran the task (when active).
        ``python``
            Python version on the worker (when active).
        ``slurm_job_id``
            Slurm job ID (when active and running under Slurm).
        ``elapsed_seconds``
            Wall-clock time the probe took.
        ``error``
            Error message on failure.

    Examples
    --------
    >>> probe_endpoint_worker(config, timeout_seconds=90)
    {"status": "active", "node": "chr-0497", "python": "3.13.13",
     "slurm_job_id": "1228500", "elapsed_seconds": 28.4}
    """
    endpoint_id = getattr(config, "endpoint_id", None)
    if not endpoint_id:
        return {"status": "no_endpoint", "message": "No endpoint configured"}

    # Fast manager check first — no point probing an offline endpoint
    manager = check_endpoint_manager_status(config, force=True)
    if manager["status"] not in ("registered", "active"):
        return manager

    try:
        from globus_compute_sdk import Executor
        from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer
    except ImportError:
        return {
            "status": "unreachable",
            **_endpoint_public_fields(config),
            "error": "globus-compute-sdk not installed. Run: uv sync --extra hpc",
        }

    def _worker_probe() -> dict:
        import os
        import platform

        return {
            "node": platform.node(),
            "python": platform.python_version(),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID", ""),
            "pbs_job_id": os.environ.get("PBS_JOBID", ""),
            "pythonpath": os.environ.get("PYTHONPATH", ""),
        }

    t0 = time.monotonic()
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"(?s).*Environment differences detected between local SDK and endpoint.*",
                category=UserWarning,
            )
            with Executor(
                endpoint_id=endpoint_id,
                serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
            ) as ex:
                fut = ex.submit(_worker_probe)
                result = fut.result(timeout=timeout_seconds)

        elapsed = round(time.monotonic() - t0, 1)
        payload = {
            "status": "active",
            **_endpoint_public_fields(config),
            "node": result.get("node", ""),
            "python": result.get("python", ""),
            "slurm_job_id": result.get("slurm_job_id") or None,
            "pbs_job_id": result.get("pbs_job_id") or None,
            "pythonpath_set": bool(result.get("pythonpath")),
            "elapsed_seconds": elapsed,
        }
        # Warn if PYTHONPATH is set — this is the root cause of most worker crashes
        if result.get("pythonpath"):
            payload["warning"] = (
                "PYTHONPATH is set on the worker. This can cause pydantic/dill "
                "conflicts. Add 'unset PYTHONPATH' to worker_init in the endpoint "
                "config, and set PYTHONPATH: '' in user_environment.yaml."
            )
        return payload

    except TimeoutError:
        return {
            "status": "registered",
            **_endpoint_public_fields(config),
            "error": f"Probe timed out after {timeout_seconds}s. Manager is up but "
            "no worker responded. The scheduler may be busy or the worker "
            "environment may be broken.",
            "elapsed_seconds": round(time.monotonic() - t0, 1),
        }
    except Exception as exc:
        return {
            "status": "unreachable",
            **_endpoint_public_fields(config),
            "error": str(exc),
            "elapsed_seconds": round(time.monotonic() - t0, 1),
        }


def check_all_endpoints_manager_status(
    config: Any, *, force: bool = False
) -> list[dict[str, Any]]:
    """Return a status row for every configured endpoint.

    Each row contains ``name`` and the same fields produced
    by :func:`check_endpoint_manager_status`. Uses the cache by default.
    """
    rows: list[dict[str, Any]] = []
    names = list(getattr(config, "endpoint_names", []) or [])
    if not names:
        if getattr(config, "endpoint_id", None):
            status = check_endpoint_manager_status(config, force=force)
            rows.append({"name": config.endpoint_name or "default", **status})
        return rows

    for name in names:
        endpoint_cfg = config.for_endpoint(endpoint=name)
        status = check_endpoint_manager_status(endpoint_cfg, force=force)
        rows.append({"name": name, **status})
    return rows


# ---------------------------------------------------------------------------
# Backwards-compatibility aliases — kept so existing callers don't break
# while we migrate. Will be removed in a future release.
# ---------------------------------------------------------------------------
def check_endpoint_health(config: Any, *, force: bool = False) -> dict[str, Any]:
    """Deprecated alias for :func:`check_endpoint_manager_status`."""
    return check_endpoint_manager_status(config, force=force)


def check_all_endpoints_health(
    config: Any, *, force: bool = False
) -> list[dict[str, Any]]:
    """Deprecated alias for :func:`check_all_endpoints_manager_status`."""
    return check_all_endpoints_manager_status(config, force=force)
