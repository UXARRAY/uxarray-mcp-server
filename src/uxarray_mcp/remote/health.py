"""Endpoint health checking for HPC execution.

The Globus Compute ``Client()`` constructor performs token refresh and network
lookups that take 1–5 s on the first call. ``client.get_endpoint_status()``
itself is also a network round-trip. In a chat session that polls execution
mode on every prompt this latency stacks up quickly.

This module keeps a process-level Client cache plus a short-TTL per-endpoint
health cache so back-to-back checks are effectively free.
"""

from __future__ import annotations

import threading
import time
from typing import Any

# Process-wide cached Client. The constructor is the slow part.
_CLIENT: Any = None
_CLIENT_LOCK = threading.Lock()

# Per-endpoint health cache. Keyed by endpoint_id; value is
# (monotonic_ts, status_dict) where status_dict is the canonical fresh payload
# (with no "cached" / "cache_age_seconds" keys mixed in).
_HEALTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_HEALTH_CACHE_LOCK = threading.Lock()

# How long a healthy result stays valid before we re-query the SDK.
# Unhealthy results expire faster so a recovering endpoint is noticed promptly.
HEALTH_TTL_HEALTHY_SECONDS = 10.0
HEALTH_TTL_UNHEALTHY_SECONDS = 3.0


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
    """Drop cached health entries.

    If ``endpoint_id`` is None, clear the entire health cache. The cached
    Client itself is preserved — it does not go stale.
    """
    with _HEALTH_CACHE_LOCK:
        if endpoint_id is None:
            _HEALTH_CACHE.clear()
        else:
            _HEALTH_CACHE.pop(endpoint_id, None)


def _cached_entry(endpoint_id: str) -> dict[str, Any] | None:
    with _HEALTH_CACHE_LOCK:
        entry = _HEALTH_CACHE.get(endpoint_id)
    if entry is None:
        return None
    ts, payload = entry
    age = time.monotonic() - ts
    ttl = (
        HEALTH_TTL_HEALTHY_SECONDS
        if payload.get("status") in {"online", "healthy"}
        else HEALTH_TTL_UNHEALTHY_SECONDS
    )
    if age > ttl:
        return None
    cached = dict(payload)
    cached["cached"] = True
    cached["cache_age_seconds"] = round(age, 3)
    return cached


def _store(endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _HEALTH_CACHE_LOCK:
        _HEALTH_CACHE[endpoint_id] = (time.monotonic(), payload)
    fresh = dict(payload)
    fresh["cached"] = False
    return fresh


def check_endpoint_health(config: Any, *, force: bool = False) -> dict[str, Any]:
    """Check if the Globus Compute endpoint is reachable.

    Parameters
    ----------
    config : HPCConfig
        HPC configuration with endpoint_id
    force : bool, default False
        Bypass the short-TTL cache and re-query the SDK.

    Returns
    -------
    dict
        Status dict with keys:
        - status: "healthy", "online", "no_endpoint", "unreachable", or "unknown"
        - endpoint_id: The endpoint UUID (if configured)
        - error: Error message (if unreachable)
        - cached: True if served from the in-process cache
        - cache_age_seconds: Age of the cached entry (if cached)

    Examples
    --------
    >>> from uxarray_mcp.remote.config import load_config
    >>> config = load_config()
    >>> check_endpoint_health(config)
    {"status": "online", "endpoint_id": "14e272c4-...", "cached": False}
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
        endpoint_status = client.get_endpoint_status(endpoint_id)
        status = endpoint_status.get("status", "unknown")
        payload: dict[str, Any] = {
            "status": status,
            "endpoint_id": endpoint_id,
        }
        return _store(endpoint_id, payload)
    except Exception as exc:
        payload = {
            "status": "unreachable",
            "endpoint_id": endpoint_id,
            "error": str(exc),
        }
        return _store(endpoint_id, payload)


def check_all_endpoints_health(
    config: Any, *, force: bool = False
) -> list[dict[str, Any]]:
    """Return a status row for every configured endpoint.

    Each row contains ``name``, ``endpoint_id``, and the same fields produced
    by :func:`check_endpoint_health`. Uses the cache by default, so calling
    this on every chat turn is cheap.
    """
    rows: list[dict[str, Any]] = []
    names = list(getattr(config, "endpoint_names", []) or [])
    if not names:
        if getattr(config, "endpoint_id", None):
            health = check_endpoint_health(config, force=force)
            rows.append({"name": config.endpoint_name or "default", **health})
        return rows

    for name in names:
        endpoint_cfg = config.for_endpoint(endpoint=name)
        health = check_endpoint_health(endpoint_cfg, force=force)
        rows.append({"name": name, **health})
    return rows
