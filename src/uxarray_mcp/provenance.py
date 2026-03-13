"""Provenance tracking for UXarray MCP tool outputs.

Appends a _provenance key to every tool result so scientific workflows
can trace what ran, when, where, and with what software.
"""

import sys
from datetime import datetime, timezone
from typing import Any


def _get_uxarray_version() -> str:
    try:
        import uxarray
        return uxarray.__version__
    except Exception:
        return "unknown"


def attach_provenance(
    result: dict[str, Any],
    tool: str,
    inputs: dict[str, Any],
    venue: str = "local",
) -> dict[str, Any]:
    """Attach a _provenance block to a tool result dict.

    Parameters
    ----------
    result : dict
        The tool output to annotate.
    tool : str
        Name of the tool that produced the result.
    inputs : dict
        The input arguments passed to the tool.
    venue : str
        Execution venue: "local" or "hpc:<endpoint-id>".

    Returns
    -------
    dict
        The result dict with a _provenance key added.
    """
    result["_provenance"] = {
        "tool": tool,
        "inputs": inputs,
        "execution_venue": venue,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "uxarray_version": _get_uxarray_version(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "warnings": [],
    }
    return result
