"""MCP tools with remote execution support."""

import asyncio
import concurrent.futures
from typing import Any, Dict, Optional


def _run_sync(coro):
    """Run a coroutine synchronously, works inside or outside a running event loop."""
    try:
        asyncio.get_running_loop()
        # Inside async context (e.g. FastMCP) — run in a new thread
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        # No event loop running (tests, CLI) — run directly
        return asyncio.run(coro)


def calculate_area_hpc(file_path: str, use_remote: bool = False) -> Dict[str, Any]:
    """Calculate face areas with optional HPC execution.

    Parameters
    ----------
    file_path : str
        Path to mesh file (supports UGRID, MPAS, SCRIP, ESMF, etc.)
        Can be local path or HPC filesystem path if use_remote=True
    use_remote : bool
        If True and HPC is configured, execute on remote endpoint

    Returns
    -------
    dict
        Dictionary containing:
        - total_area: Total surface area
        - mean_area: Mean face area
        - min_area: Minimum face area
        - max_area: Maximum face area
        - area_units: Units (m^2, km^2, etc.)
        - n_face: Number of faces

    Examples
    --------
    >>> calculate_area_hpc("mesh.nc", use_remote=False)
    {
        "total_area": 5.10064e14,
        "mean_area": 1.246e7,
        ...
    }

    >>> calculate_area_hpc("/hpc/data/mesh.nc", use_remote=True)
    {
        "total_area": 5.10064e14,
        ...
    }
    """
    try:
        from uxarray_mcp.remote.agent import get_agent

        return _run_sync(get_agent().calculate_area_remote(file_path, use_remote))
    except ImportError:
        from uxarray_mcp.tools.inspection import calculate_area

        return calculate_area(file_path)


def inspect_variable_hpc(
    grid_path: str,
    data_path: str,
    variable_name: Optional[str] = None,
    use_remote: bool = False,
) -> Dict[str, Any]:
    """Inspect data variables with optional HPC execution.

    Parameters
    ----------
    grid_path : str
        Path to mesh grid file
    data_path : str
        Path to data file
    variable_name : str | None
        Specific variable to inspect, or None for all
    use_remote : bool
        If True and HPC is configured, execute on remote endpoint

    Returns
    -------
    dict
        Dictionary containing:
        - variables: List of variable metadata
        - grid_info: Grid summary

    Examples
    --------
    >>> inspect_variable_hpc("grid.nc", "data.nc", "temperature")
    {
        "variables": [{
            "name": "temperature",
            "dims": ("n_face", "n_level"),
            ...
        }],
        "grid_info": {...}
    }
    """
    try:
        from uxarray_mcp.remote.agent import get_agent

        return _run_sync(
            get_agent().inspect_variable_remote(
                grid_path, data_path, variable_name, use_remote
            )
        )
    except ImportError:
        from uxarray_mcp.tools.inspection import inspect_variable

        return inspect_variable(grid_path, data_path, variable_name)


def calculate_zonal_mean_hpc(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
    use_remote: bool = False,
) -> Dict[str, Any]:
    """Calculate zonal mean with optional HPC execution.

    Parameters
    ----------
    grid_path : str
        Path to mesh grid file
    data_path : str
        Path to data file
    variable_name : str
        Variable to compute zonal mean for (must be face-centered)
    lat_spec : tuple | float | list | None
        Latitude specification
    conservative : bool
        Use area-weighted averaging over latitude bands
    use_remote : bool
        If True and HPC is configured, execute on remote endpoint

    Returns
    -------
    dict
        Dictionary containing:
        - variable_name: Name of variable
        - latitudes: List of latitude values
        - zonal_mean_values: List of zonal mean values
        - conservative: Whether conservative method was used
        - grid_info: Grid summary

    Examples
    --------
    >>> calculate_zonal_mean_hpc("grid.nc", "data.nc", "temperature")
    {
        "variable_name": "temperature",
        "latitudes": [-90, -80, ...],
        "zonal_mean_values": [271.5, 273.2, ...],
        ...
    }
    """
    try:
        from uxarray_mcp.remote.agent import get_agent

        return _run_sync(
            get_agent().calculate_zonal_mean_remote(
                grid_path, data_path, variable_name, lat_spec, conservative, use_remote
            )
        )
    except ImportError:
        from uxarray_mcp.tools.inspection import calculate_zonal_mean

        return calculate_zonal_mean(
            grid_path, data_path, variable_name, lat_spec, conservative
        )
