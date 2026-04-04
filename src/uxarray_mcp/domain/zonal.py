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
