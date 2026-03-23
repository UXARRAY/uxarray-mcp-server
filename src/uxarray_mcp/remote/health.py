"""Endpoint health checking for HPC execution."""

from typing import Any


def check_endpoint_health(config: Any) -> dict[str, Any]:
    """Check if the Globus Compute endpoint is reachable.

    Parameters
    ----------
    config : HPCConfig
        HPC configuration with endpoint_id

    Returns
    -------
    dict
        Status dict with keys:
        - status: "healthy", "no_endpoint", "unreachable", or "unknown"
        - endpoint_id: The endpoint UUID (if configured)
        - error: Error message (if unreachable)

    Examples
    --------
    >>> from uxarray_mcp.remote.config import load_config
    >>> config = load_config()
    >>> check_endpoint_health(config)
    {"status": "healthy", "endpoint_id": "14e272c4-..."}
    """
    if not config.has_endpoint:
        return {"status": "no_endpoint", "message": "No endpoint configured"}

    try:
        from globus_compute_sdk import Client

        client = Client()
        endpoint_status = client.get_endpoint_status(config.endpoint_id)
        status = endpoint_status.get("status", "unknown")
        return {
            "status": status,
            "endpoint_id": config.endpoint_id,
        }
    except Exception as exc:
        return {
            "status": "unreachable",
            "endpoint_id": config.endpoint_id,
            "error": str(exc),
        }
