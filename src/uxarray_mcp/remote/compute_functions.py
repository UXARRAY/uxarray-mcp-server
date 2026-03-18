"""Globus Compute functions for remote execution.

These functions are serialized and sent to HPC endpoints via AllCodeStrategies.
They must be FULLY SELF-CONTAINED — only import packages available on the HPC
environment (uxarray, numpy, etc.). Never import from uxarray_mcp here.
"""

from typing import Dict, Any, Optional


def remote_inspect_mesh(file_path: str) -> Dict[str, Any]:
    """Inspect mesh topology on remote HPC node.

    Parameters
    ----------
    file_path : str
        Path to mesh file on HPC filesystem

    Returns
    -------
    dict
        Mesh topology including n_face, n_node, n_edge, source

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    All imports must be within function scope for serialization.
    """
    import uxarray as ux

    if file_path.startswith("healpix:"):
        zoom = int(file_path.split(":")[1])
        grid = ux.Grid.from_healpix(zoom)
    else:
        grid = ux.open_grid(file_path)

    return {
        "n_face": int(grid.n_face),
        "n_node": int(grid.n_node),
        "n_edge": int(grid.n_edge),
        "source": file_path,
    }


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
    import numpy as np
    import uxarray as ux

    if file_path.startswith("healpix:"):
        zoom = int(file_path.split(":")[1])
        grid = ux.Grid.from_healpix(zoom)
    else:
        grid = ux.open_grid(file_path)

    areas = grid.face_areas
    units = getattr(areas, "units", "m^2") if hasattr(areas, "units") else "m^2"
    values = areas.values if hasattr(areas, "values") else np.asarray(areas)

    return {
        "total_area": float(np.sum(values)),
        "mean_area": float(np.mean(values)),
        "min_area": float(np.min(values)),
        "max_area": float(np.max(values)),
        "area_units": str(units),
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
    import numpy as np
    import uxarray as ux

    uxds = ux.open_dataset(grid_path, data_path)

    face_dims = {"n_face", "nCells"}
    node_dims = {"n_node", "nVertices"}
    edge_dims = {"n_edge", "nEdges"}

    var_names = [variable_name] if variable_name else list(uxds.keys())

    if variable_name and variable_name not in uxds:
        raise ValueError(f"Variable '{variable_name}' not found in dataset")

    variables = []

    for name in var_names:
        if name not in uxds:
            continue
        var = uxds[name]
        dims = var.dims

        location = "other"
        if any(d in face_dims for d in dims):
            location = "faces"
        elif any(d in node_dims for d in dims):
            location = "nodes"
        elif any(d in edge_dims for d in dims):
            location = "edges"

        stats = None
        try:
            values = var.values
            finite = values[np.isfinite(values)]
            if len(finite) > 0:
                stats = {
                    "min": float(np.min(finite)),
                    "max": float(np.max(finite)),
                    "mean": float(np.mean(finite)),
                }
        except Exception:
            pass

        variables.append(
            {
                "name": name,
                "dims": list(dims),
                "shape": list(var.shape),
                "dtype": str(var.dtype),
                "location": location,
                "attrs": dict(var.attrs),
                "statistics": stats,
            }
        )

    return {
        "variables": variables,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }


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

    if variable_name not in uxds:
        raise ValueError(f"Variable '{variable_name}' not found")

    var = uxds[variable_name]
    face_dims = {"n_face", "nCells"}
    if not any(d in face_dims for d in var.dims):
        raise ValueError(f"Variable '{variable_name}' is not face-centered")

    if lat_spec is None:
        lat_spec = (-90, 90, 10)

    if conservative:
        result = var.zonal_mean(lat=lat_spec, conservative=True)
    else:
        result = var.zonal_mean(lat=lat_spec)

    return {
        "variable_name": variable_name,
        "latitudes": result.coords[result.dims[0]].values.tolist(),
        "zonal_mean_values": result.values.tolist(),
        "conservative": conservative,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }
