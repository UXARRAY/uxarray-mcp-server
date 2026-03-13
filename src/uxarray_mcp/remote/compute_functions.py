"""Globus Compute functions for remote execution.

These functions are serialized and sent to HPC endpoints.
All imports must be inside the function body for Globus Compute compatibility.
Scientific logic is shared via uxarray_mcp.domain — write science once, run anywhere.
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
    from uxarray_mcp.domain.mesh import load_grid
    from uxarray_mcp.domain.area import compute_area_stats

    grid = load_grid(file_path)
    return compute_area_stats(grid)


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
    from uxarray_mcp.domain.variable import compute_variable_info

    uxds = ux.open_dataset(grid_path, data_path)
    return compute_variable_info(uxds, variable_name)


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
    from uxarray_mcp.domain.zonal import compute_zonal_mean_stats

    uxds = ux.open_dataset(grid_path, data_path)
    return compute_zonal_mean_stats(uxds, variable_name, lat_spec, conservative)
