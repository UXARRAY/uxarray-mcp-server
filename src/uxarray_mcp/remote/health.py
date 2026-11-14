"""Endpoint health: manager registration (cheap) and worker probe (real).

``manager_status`` asks the Globus web service whether the endpoint process
is registered. It says nothing about whether a scheduler has granted a node;
only ``worker_probe`` -- which runs a function on the endpoint -- confirms
that, and on a Slurm/PBS endpoint it can take a minute to come back.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from uxarray_mcp.remote.config import HPCConfig, load_config

_lock = threading.Lock()
_client: Any = None
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_TTL_SECONDS = 10.0

_GLOBUS_TO_STATUS = {"online": "registered", "offline": "offline"}


def _get_client() -> Any:
    global _client
    with _lock:
        if _client is None:
            from globus_compute_sdk import Client

            _client = Client()
        return _client


def invalidate_cache() -> None:
    with _lock:
        _cache.clear()


def manager_status(config: HPCConfig, *, force: bool = False) -> dict[str, Any]:
    """``registered`` | ``offline`` | ``unreachable`` | ``no_endpoint``."""
    endpoint_id = config.endpoint_id
    if not endpoint_id:
        return {"status": "no_endpoint", "message": "No endpoint configured."}
    now = time.monotonic()
    if not force:
        hit = _cache.get(endpoint_id)
        if hit and now - hit[0] < _TTL_SECONDS:
            return {**hit[1], "cached": True}
    name = config.endpoint_name or "default"
    try:
        raw = _get_client().get_endpoint_status(endpoint_id)
        raw_status = raw.get("status", "unknown") if isinstance(raw, dict) else str(raw)
        payload: dict[str, Any] = {
            "status": _GLOBUS_TO_STATUS.get(raw_status, raw_status),
            "endpoint": name,
        }
    except Exception as exc:
        payload = {"status": "unreachable", "endpoint": name, "error": str(exc)}
    with _lock:
        _cache[endpoint_id] = (now, payload)
    return {**payload, "cached": False}


def worker_probe(
    endpoint: str | None = None, timeout_seconds: int = 60
) -> dict[str, Any]:
    """Run a trivial function on the worker; ``status`` is ``active`` or an error."""
    from uxarray_mcp.remote.executor import RemoteError, probe

    try:
        info = probe(endpoint=endpoint, timeout_seconds=timeout_seconds)
    except RemoteError as err:
        return {"status": "error", **err.to_dict()}
    info["status"] = "active"
    return info


def all_manager_statuses(config: HPCConfig | None = None) -> list[dict[str, Any]]:
    cfg = config or load_config()
    return [manager_status(cfg.for_endpoint(endpoint=n)) for n in cfg.endpoint_names]
