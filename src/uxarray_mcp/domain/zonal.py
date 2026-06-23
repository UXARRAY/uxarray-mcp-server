"""Shared zonal mean computation logic."""

from __future__ import annotations

from typing import Any, Optional


def compute_zonal_mean_stats(
    uxds: Any,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
) -> dict:
    """Compute zonal mean statistics from a loaded UXarray dataset.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset.
    variable_name : str
        Name of face-centered variable to average.
    lat_spec : tuple | float | list | None
        Latitude specification for zonal bands.
    conservative : bool
        If True, use area-weighted conservative averaging.

    Returns
    -------
    dict
        Keys: variable_name, latitudes, zonal_mean_values, conservative, grid_info
    """
    if variable_name not in uxds.data_vars:
        available = list(uxds.data_vars.keys())
        raise ValueError(
            f"Variable '{variable_name}' not found. Available variables: {available}"
        )

    var = uxds[variable_name]

    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Zonal mean only supports face-centered data."
        )

    if lat_spec is not None:
        zonal_result = var.zonal_mean(lat=lat_spec, conservative=conservative)
    else:
        zonal_result = var.zonal_mean(conservative=conservative)

    latitudes = zonal_result.coords["latitudes"].values.tolist()
    zonal_mean_values = zonal_result.values.tolist()

    grid_info = {
        "n_face": int(uxds.uxgrid.n_face),
        "n_node": int(uxds.uxgrid.n_node),
        "n_edge": int(uxds.uxgrid.n_edge),
    }

    return {
        "variable_name": variable_name,
        "latitudes": latitudes,
        "zonal_mean_values": zonal_mean_values,
        "conservative": conservative,
        "grid_info": grid_info,
    }


def compute_zonal_anomaly_stats(
    uxds: Any,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
) -> dict:
    """Compute zonal-anomaly statistics from a loaded UXarray dataset.

    The zonal anomaly is each face value minus the zonal mean of its latitude
    band, producing a per-face field with the same shape as the input variable.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset.
    variable_name : str
        Name of the face-centered variable.
    lat_spec : tuple | float | list | None
        Latitude band specification passed through to ``zonal_anomaly``. A
        ``(start, end, step)`` tuple or explicit band edges. ``None`` uses the
        UXarray default ``(-90, 90, 10)``.
    conservative : bool
        If True, use area-weighted band means.

    Returns
    -------
    dict
        Keys: variable_name, conservative, n_face, stats (min/max/mean/std of
        the anomaly field), grid_info.

    Raises
    ------
    NotImplementedError
        If the installed UXarray does not provide ``UxDataArray.zonal_anomaly``.
    """
    import numpy as np

    if variable_name not in uxds.data_vars:
        available = list(uxds.data_vars.keys())
        raise ValueError(
            f"Variable '{variable_name}' not found. Available variables: {available}"
        )

    var = uxds[variable_name]

    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Zonal anomaly only supports face-centered data."
        )

    if not hasattr(var, "zonal_anomaly"):
        raise NotImplementedError(
            "zonal_anomaly requires a UXarray release that provides "
            "UxDataArray.zonal_anomaly. Upgrade uxarray to use this operation."
        )

    if lat_spec is not None:
        result = var.zonal_anomaly(lat=lat_spec, conservative=conservative)
    else:
        result = var.zonal_anomaly(conservative=conservative)

    vals = result.values
    finite = vals[np.isfinite(vals)]
    stats: dict[str, float | None]
    if finite.size > 0:
        stats = {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "std": float(finite.std()),
        }
    else:
        stats = {"min": None, "max": None, "mean": None, "std": None}

    return {
        "variable_name": variable_name,
        "conservative": conservative,
        "n_face": int(uxds.uxgrid.n_face),
        "stats": stats,
        "interpretation": "per-face deviation from the zonal mean of its latitude band",
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }
