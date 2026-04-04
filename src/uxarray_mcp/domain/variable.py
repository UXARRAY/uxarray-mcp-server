"""Shared variable inspection logic."""

from __future__ import annotations

from typing import Any, Optional


def compute_variable_info(uxds: Any, variable_name: Optional[str] = None) -> dict:
    """Extract variable metadata and statistics from a UXarray dataset.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset.
    variable_name : str | None
        Specific variable to inspect, or None for all variables.

    Returns
    -------
    dict
        Keys: variables (list of metadata dicts), grid_info
    """
    import numpy as np

    if variable_name:
        if variable_name not in uxds.data_vars:
            available = list(uxds.data_vars.keys())
            raise ValueError(
                f"Variable '{variable_name}' not found. Available variables: {available}"
            )
        variables_to_inspect = [variable_name]
    else:
        variables_to_inspect = list(uxds.data_vars.keys())

    variables_info = []
    for var_name in variables_to_inspect:
        var = uxds[var_name]

        location = "other"
        if "n_face" in var.dims or "nCells" in var.dims:
            location = "faces"
        elif "n_node" in var.dims or "nVertices" in var.dims:
            location = "nodes"
        elif "n_edge" in var.dims or "nEdges" in var.dims:
            location = "edges"

        var_info = {
            "name": var_name,
            "dims": var.dims,
            "shape": var.shape,
            "dtype": str(var.dtype),
            "location": location,
            "attrs": dict(var.attrs),
        }

        try:
            if np.issubdtype(var.dtype, np.number):
                values = var.values
                var_info["statistics"] = {
                    "min": float(np.nanmin(values)),
                    "max": float(np.nanmax(values)),
                    "mean": float(np.nanmean(values)),
                }
            else:
                var_info["statistics"] = None
        except Exception:
            var_info["statistics"] = None

        variables_info.append(var_info)

    grid_info = {
        "n_face": int(uxds.uxgrid.n_face),
        "n_node": int(uxds.uxgrid.n_node),
        "n_edge": int(uxds.uxgrid.n_edge),
    }

    return {"variables": variables_info, "grid_info": grid_info}
