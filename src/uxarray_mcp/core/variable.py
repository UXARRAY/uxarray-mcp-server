"""Variable inspection: dims, dtype, location and finite-only statistics.

``n_finite``/``n_total`` appear only when some entries are missing, so a
masked field is never reported as if it were whole.
"""

from __future__ import annotations

from typing import Any


def _numeric_statistics(values: Any) -> dict[str, Any]:
    """Statistics over the entries that are there, saying when some were not.

    Masked entries are dropped with a boolean index rather than by calling
    ``np.nanmin`` and friends. Those emit ``RuntimeWarning: All-NaN slice
    encountered`` on a fully masked field and then return ``NaN`` anyway, so
    the caller got a warning on stderr they never see and a number that is
    not JSON.

    Integers and booleans carry no missing value to skip, so they take the
    plain reductions and never grow the two extra keys.
    """
    import numpy as np

    if not np.issubdtype(values.dtype, np.inexact):
        return {
            "min": float(values.min()),
            "max": float(values.max()),
            "mean": float(values.mean()),
        }

    finite = np.isfinite(values)
    n_finite = int(finite.sum())
    usable = values[finite]
    stats: dict[str, Any] = {
        "min": float(usable.min()) if n_finite else None,
        "max": float(usable.max()) if n_finite else None,
        "mean": float(usable.mean()) if n_finite else None,
    }
    if n_finite != values.size:
        stats["n_finite"] = n_finite
        stats["n_total"] = int(values.size)
    return stats


def compute_variable_info(uxds: Any, variable_name: str | None = None) -> dict:
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
        Keys: variables (list of metadata dicts), grid_info.

        Each variable's ``statistics`` is ``{min, max, mean}`` over the
        entries that are actually present, plus ``n_finite`` and ``n_total``
        when those differ. ``min``/``max``/``mean`` are ``None`` when nothing
        is finite -- an honest absence rather than a ``NaN`` that no strict
        JSON decoder will accept. ``statistics`` itself is ``None`` for a
        variable that has no numeric statistics at all.
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
                var_info["statistics"] = _numeric_statistics(np.asarray(var.values))
            else:
                var_info["statistics"] = None
        except Exception:  # noqa: BLE001
            var_info["statistics"] = None

        variables_info.append(var_info)

    grid_info = {
        "n_face": int(uxds.uxgrid.n_face),
        "n_node": int(uxds.uxgrid.n_node),
        "n_edge": int(uxds.uxgrid.n_edge),
    }

    return {"variables": variables_info, "grid_info": grid_info}
