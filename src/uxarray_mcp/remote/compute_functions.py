"""Globus Compute functions for remote execution.

These functions are serialized and sent to HPC endpoints.
All imports must be inside the function body for Globus Compute compatibility.
"""

from typing import Dict, Any, Optional


def remote_calculate_area(file_path: str) -> Dict[str, Any]:
    """Calculate face areas on remote HPC node.

    Parameters
    ----------
    file_path : str
        Path to mesh file on HPC filesystem

    Returns
    -------
    dict
        Area statistics including total_area, mean_area, min_area, max_area

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    All imports must be within function scope for serialization.
    """
    import uxarray as ux

    if file_path.lower().startswith("healpix"):
        parts = file_path.split(":")
        zoom = int(parts[1]) if len(parts) > 1 else 1
        grid = ux.Grid.from_healpix(zoom=zoom)
    else:
        grid = ux.open_grid(file_path)

    face_areas = grid.face_areas

    return {
        "total_area": float(face_areas.sum()),
        "mean_area": float(face_areas.mean()),
        "min_area": float(face_areas.min()),
        "max_area": float(face_areas.max()),
        "area_units": "m^2",
        "n_face": int(grid.n_face),
    }


def remote_inspect_variable(
    grid_path: str, data_path: str, variable_name: Optional[str] = None
) -> Dict[str, Any]:
    """Inspect data variables on remote HPC node.

    Parameters
    ----------
    grid_path : str
        Path to grid file on HPC filesystem
    data_path : str
        Path to data file on HPC filesystem
    variable_name : str | None
        Specific variable to inspect, or None for all variables

    Returns
    -------
    dict
        Variable metadata including dimensions, shapes, statistics

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    """
    import uxarray as ux
    import numpy as np

    uxds = ux.open_dataset(grid_path, data_path)

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

        if np.issubdtype(var.dtype, np.number):
            values = var.values
            var_info["statistics"] = {
                "min": float(np.nanmin(values)),
                "max": float(np.nanmax(values)),
                "mean": float(np.nanmean(values)),
            }
        else:
            var_info["statistics"] = None

        variables_info.append(var_info)

    grid_info = {
        "n_face": int(uxds.uxgrid.n_face),
        "n_node": int(uxds.uxgrid.n_node),
        "n_edge": int(uxds.uxgrid.n_edge),
    }

    return {"variables": variables_info, "grid_info": grid_info}


def remote_calculate_zonal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
) -> Dict[str, Any]:
    """Calculate zonal mean on remote HPC node.

    Parameters
    ----------
    grid_path : str
        Path to grid file on HPC filesystem
    data_path : str
        Path to data file on HPC filesystem
    variable_name : str
        Variable to compute zonal mean for
    lat_spec : tuple | float | list | None
        Latitude specification
    conservative : bool
        Whether to use conservative averaging

    Returns
    -------
    dict
        Zonal mean results including latitudes and values

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    """
    import uxarray as ux

    uxds = ux.open_dataset(grid_path, data_path)

    if variable_name not in uxds.data_vars:
        available = list(uxds.data_vars.keys())
        raise ValueError(
            f"Variable '{variable_name}' not found. Available variables: {available}"
        )

    var = uxds[variable_name]

    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. Zonal mean only supports face-centered data."
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
