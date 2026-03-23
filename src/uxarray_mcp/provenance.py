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
    warnings: list[str] | None = None,
    validation_summary: dict[str, Any] | None = None,
    selected_variable: str | None = None,
    artifacts: list[dict[str, Any]] | None = None,
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
    warnings : list[str] | None
        Any warnings generated during execution.
    validation_summary : dict | None
        Summary from validate_dataset: passed, n_variables_checked,
        n_variables_failed. Included when a validation step ran upstream.
    selected_variable : str | None
        The variable name that was analysed, when applicable.
    artifacts : list[dict] | None
        Computational outputs produced by this run. Each entry is a dict
        with at minimum a "type" key describing what was computed
        (e.g. mesh_topology, face_areas, zonal_mean, validation).

    Returns
    -------
    dict
        The result dict with a _provenance key added.
    """
    provenance: dict[str, Any] = {
        "tool": tool,
        "inputs": inputs,
        "execution_venue": venue,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "uxarray_version": _get_uxarray_version(),
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "warnings": warnings if warnings is not None else [],
        "artifacts": artifacts if artifacts is not None else [],
    }
    if selected_variable is not None:
        provenance["selected_variable"] = selected_variable
    if validation_summary is not None:
        provenance["validation_summary"] = validation_summary
    result["_provenance"] = provenance
    return result
