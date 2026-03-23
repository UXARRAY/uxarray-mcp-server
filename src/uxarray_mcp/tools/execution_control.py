"""Execution mode control tools.

Let users switch between local and HPC execution at runtime without
editing config files manually.
"""

from pathlib import Path
from typing import Dict, Any

import yaml

from uxarray_mcp.provenance import attach_provenance

_VALID_MODES = ("local", "remote", "auto")
_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config.yaml"


def get_execution_mode() -> Dict[str, Any]:
    """Return the current execution mode and HPC endpoint status.

    Returns
    -------
    dict
        Dictionary containing:
        - mode: Current execution mode ("local", "remote", or "auto")
        - endpoint_id: Configured Globus Compute endpoint UUID, or None
        - endpoint_status: "healthy", "no_endpoint", "unreachable", or "unknown"
        - description: Plain-English explanation of what the current mode means

    Example:
        >>> get_execution_mode()
        {
            "mode": "auto",
            "endpoint_id": "14e272c4-...",
            "endpoint_status": "online",
            "description": "Auto mode: uses HPC when endpoint is available, local otherwise."
        }
    """
    from uxarray_mcp.remote.config import load_config
    from uxarray_mcp.remote.health import check_endpoint_health

    config = load_config(_CONFIG_PATH)
    health = check_endpoint_health(config)

    descriptions = {
        "local": "Local mode: all computations run on this machine regardless of HPC availability.",
        "remote": "Remote mode: all computations are sent to the HPC endpoint. Fails if endpoint is down.",
        "auto": "Auto mode: uses HPC when endpoint is available, local otherwise.",
    }

    result = {
        "mode": config.execution_mode,
        "endpoint_id": config.endpoint_id,
        "endpoint_status": health.get("status", "unknown"),
        "description": descriptions.get(config.execution_mode, "Unknown mode."),
    }

    return attach_provenance(
        result,
        tool="get_execution_mode",
        inputs={},
    )


def set_execution_mode(mode: str) -> Dict[str, Any]:
    """Switch execution mode at runtime and persist it to config.yaml.

    Parameters
    ----------
    mode : str
        Execution mode to set. One of:
        - "local"  — always run on this machine
        - "remote" — always send to HPC endpoint (fails if endpoint is down)
        - "auto"   — use HPC when available, fall back to local otherwise

    Returns
    -------
    dict
        Dictionary containing:
        - mode: The new execution mode
        - previous_mode: The mode that was active before this call
        - endpoint_id: Configured endpoint UUID, or None
        - message: Confirmation message

    Raises
    ------
    ValueError
        If mode is not one of "local", "remote", or "auto".

    Example:
        >>> set_execution_mode("local")
        {"mode": "local", "previous_mode": "auto", "message": "Switched to local mode."}

        >>> set_execution_mode("auto")
        {"mode": "auto", "previous_mode": "local", "message": "Switched to auto mode."}
    """
    if mode not in _VALID_MODES:
        raise ValueError(
            f"Invalid mode {mode!r}. Must be one of: {', '.join(_VALID_MODES)}"
        )

    from uxarray_mcp.remote.config import load_config
    from uxarray_mcp.remote import agent as _agent_module

    config = load_config(_CONFIG_PATH)
    previous_mode = config.execution_mode

    # Read the current config file and update execution_mode in place
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    if "hpc" not in data or not isinstance(data.get("hpc"), dict):
        data["hpc"] = {}
    data["hpc"]["execution_mode"] = mode

    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    # Reset singleton agent so next call picks up the new config
    _agent_module._agent_instance = None

    result = {
        "mode": mode,
        "previous_mode": previous_mode,
        "endpoint_id": config.endpoint_id,
        "message": f"Switched to {mode!r} mode. Config saved to {_CONFIG_PATH.name}.",
    }

    return attach_provenance(
        result,
        tool="set_execution_mode",
        inputs={"mode": mode},
    )
