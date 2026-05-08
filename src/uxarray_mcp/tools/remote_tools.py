"""MCP tools with remote execution support."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
from typing import Any, Callable, Dict, List, Optional

from mcp.types import ImageContent, TextContent

from uxarray_mcp.state import OperationTracker


def _endpoint_is_ready(agent) -> tuple[bool, str]:
    """Pre-flight check: return (ready, reason) before submitting an HPC job.

    Fails fast instead of waiting for the full timeout_seconds.
    """
    from uxarray_mcp.remote.health import check_endpoint_health

    health = check_endpoint_health(agent.config)
    status = health.get("status", "unknown")
    if status in ("online", "healthy"):
        return True, "ok"
    return (
        False,
        f"endpoint status={status!r}: {health.get('error', health.get('message', ''))}",
    )


def _run_sync(async_call: Callable[[], Any]) -> Dict[str, Any]:
    """Run an async call from sync code and always return the final result.

    This handles both:
    - normal sync contexts (no running loop)
    - sync calls made while an event loop is already running (Python 3.14-safe)
    """
    try:
        asyncio.get_running_loop()
        # Inside async context (e.g. FastMCP) — run in a new thread
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, async_call()).result()
    except RuntimeError:
        # No event loop running (tests, CLI) — run directly
        return asyncio.run(async_call())


def _run_with_optional_hpc(
    *,
    tool_name: str,
    use_remote: bool,
    endpoint: str | None = None,
    path_hint: str | None = None,
    session_id: str | None,
    local_call: Callable[[], Dict[str, Any]],
    remote_call: Callable[[Any], Dict[str, Any]],
) -> Dict[str, Any]:
    """Run a tool locally or remotely with a consistent fallback path."""
    tracker = OperationTracker(tool_name, session_id=session_id)
    if not use_remote:
        tracker.stage("running", f"Running {tool_name} locally.")
        result = local_call()
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.succeed(f"{tool_name} completed locally.")
        return result

    from uxarray_mcp.remote.agent import get_agent

    agent = get_agent(endpoint=endpoint, path=path_hint)
    if not agent.config.endpoint_id:
        tracker.stage("fallback", "No endpoint configured; running locally.")
        result = local_call()
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.succeed(
            f"{tool_name} completed locally because no endpoint is configured."
        )
        return result

    ready, reason = _endpoint_is_ready(agent)
    if not ready:
        tracker.stage("fallback", "Endpoint not ready; running locally.")
        result = local_call()
        result["_provenance"]["warnings"].append(
            f"HPC endpoint not ready ({reason}); ran locally."
        )
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.succeed(
            f"{tool_name} completed locally because the endpoint was not ready."
        )
        return result

    endpoint_label = agent.config.endpoint_name or agent.config.endpoint_id
    tracker.stage(
        "submitted", f"Submitting {tool_name} to the HPC endpoint {endpoint_label}."
    )
    result = remote_call(agent)
    result["_provenance"]["operation_id"] = tracker.operation_id
    tracker.succeed(f"{tool_name} completed with remote execution.")
    return result


def _plot_result_to_mcp_contents(result: Dict[str, Any]) -> list[Any]:
    """Convert a plot result dict into inline MCP image + metadata contents."""
    metadata = {key: value for key, value in result.items() if key != "png_b64"}
    return [
        ImageContent(type="image", data=result["png_b64"], mimeType="image/png"),
        TextContent(type="text", text=json.dumps(metadata, indent=2)),
    ]


def inspect_mesh_hpc(
    file_path: str,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    """Inspect mesh topology with optional HPC execution.

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
        Dictionary containing mesh topology info:
        - n_face: Number of faces
        - n_node: Number of nodes
        - n_edge: Number of edges
        - source: File path

    Examples
    --------
    >>> inspect_mesh_hpc("mesh.nc", use_remote=False)
    {"n_face": 2562, "n_node": 5762, ...}

    >>> inspect_mesh_hpc("/hpc/data/mesh.nc", use_remote=True)
    {"n_face": 2562, ...}
    """
    from .inspection import inspect_mesh

    return _run_with_optional_hpc(
        tool_name="inspect_mesh_hpc",
        use_remote=use_remote,
        endpoint=endpoint,
        path_hint=file_path,
        session_id=session_id,
        local_call=lambda: inspect_mesh(file_path),
        remote_call=lambda agent: _run_sync(
            lambda: agent.inspect_mesh_remote(file_path, use_remote)
        ),
    )


def calculate_area_hpc(
    file_path: str,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
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
    from .inspection import calculate_area

    return _run_with_optional_hpc(
        tool_name="calculate_area_hpc",
        use_remote=use_remote,
        endpoint=endpoint,
        path_hint=file_path,
        session_id=session_id,
        local_call=lambda: calculate_area(file_path),
        remote_call=lambda agent: _run_sync(
            lambda: agent.calculate_area_remote(file_path, use_remote)
        ),
    )


def inspect_variable_hpc(
    grid_path: str,
    data_path: str,
    variable_name: Optional[str] = None,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
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
    from .inspection import inspect_variable

    return _run_with_optional_hpc(
        tool_name="inspect_variable_hpc",
        use_remote=use_remote,
        endpoint=endpoint,
        path_hint=grid_path,
        session_id=session_id,
        local_call=lambda: inspect_variable(grid_path, data_path, variable_name),
        remote_call=lambda agent: _run_sync(
            lambda: agent.inspect_variable_remote(
                grid_path, data_path, variable_name, use_remote
            )
        ),
    )


def calculate_zonal_mean_hpc(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
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
    from .inspection import calculate_zonal_mean

    return _run_with_optional_hpc(
        tool_name="calculate_zonal_mean_hpc",
        use_remote=use_remote,
        endpoint=endpoint,
        path_hint=grid_path,
        session_id=session_id,
        local_call=lambda: calculate_zonal_mean(
            grid_path, data_path, variable_name, lat_spec, conservative
        ),
        remote_call=lambda agent: _run_sync(
            lambda: agent.calculate_zonal_mean_remote(
                grid_path, data_path, variable_name, lat_spec, conservative, use_remote
            )
        ),
    )


def plot_mesh_hpc(
    grid_path: str,
    width: int = 800,
    height: int = 400,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
) -> list[Any]:
    """Render a mesh wireframe PNG with optional HPC execution.

    When use_remote=True the mesh is rendered on the HPC endpoint and only
    the base64-encoded PNG is transferred back to the client — no large
    grid file needs to cross the network.

    Parameters
    ----------
    grid_path : str
        Path to mesh file. Can be a local path or an HPC filesystem path
        when use_remote=True.
    width : int
        Image width in pixels (default 800).
    height : int
        Image height in pixels (default 400).
    use_remote : bool
        If True and HPC is configured, render on the remote endpoint.

    Returns
    -------
    dict
        - png_b64: Base64-encoded PNG string
        - image_size_bytes: PNG size in bytes
        - grid_info: {n_face, n_node, n_edge}
        - execution_venue: "local" or "hpc:<endpoint_id>"

    Examples
    --------
    >>> result = plot_mesh_hpc("/hpc/data/grid.nc", use_remote=True)
    >>> open("mesh.png", "wb").write(base64.b64decode(result["png_b64"]))
    """
    from .plotting import plot_mesh

    def _local() -> Dict[str, Any]:
        import base64
        import json

        items = plot_mesh(grid_path, width=width, height=height)
        # plot_mesh returns [ImageContent, TextContent]; extract png_b64 + metadata
        img = items[0]
        meta = json.loads(items[1].text)
        return {
            "png_b64": img.data,
            "image_size_bytes": meta.get(
                "image_size_bytes", len(base64.b64decode(img.data))
            ),
            "grid_info": meta.get("grid_info", {}),
            "execution_venue": "local",
            "_provenance": meta.get("_provenance", {}),
        }

    result = _run_with_optional_hpc(
        tool_name="plot_mesh_hpc",
        use_remote=use_remote,
        endpoint=endpoint,
        path_hint=grid_path,
        session_id=session_id,
        local_call=_local,
        remote_call=lambda agent: _run_sync(
            lambda: agent.plot_mesh_remote(grid_path, width, height, use_remote)
        ),
    )
    return _plot_result_to_mcp_contents(result)


def plot_variable_hpc(
    grid_path: str,
    data_path: str,
    variable_name: Optional[str] = None,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    title: Optional[str] = None,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
) -> list[Any]:
    """Render a face-centered variable as a filled-polygon PNG with optional HPC execution.

    Parameters
    ----------
    grid_path : str
        Path to mesh grid file (local or HPC filesystem).
    data_path : str
        Path to data file (local or HPC filesystem).
    variable_name : str | None
        Variable to plot. If None, the first face-centered variable is used.
    width : int
        Image width in pixels (default 800).
    height : int
        Image height in pixels (default 400).
    cmap : str
        Matplotlib colormap name (default "viridis").
    vmin : float | None
        Colormap minimum. Defaults to data minimum.
    vmax : float | None
        Colormap maximum. Defaults to data maximum.
    title : str | None
        Custom plot title.
    use_remote : bool
        If True and HPC is configured, render on the remote endpoint.

    Returns
    -------
    dict
        - png_b64: Base64-encoded PNG string
        - image_size_bytes: PNG size in bytes
        - variable_name: Name of the plotted variable
        - grid_info: {n_face, n_node, n_edge}
        - execution_venue: "local" or "hpc:<endpoint_id>"
    """
    from .plotting import plot_variable

    def _local() -> Dict[str, Any]:
        import base64
        import json

        items = plot_variable(
            grid_path,
            data_path,
            variable_name,
            width=width,
            height=height,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            title=title,
        )
        img = items[0]
        meta = json.loads(items[1].text)
        return {
            "png_b64": img.data,
            "image_size_bytes": meta.get(
                "image_size_bytes", len(base64.b64decode(img.data))
            ),
            "variable_name": meta.get("variable_name", variable_name),
            "grid_info": meta.get("grid_info", {}),
            "execution_venue": "local",
            "_provenance": meta.get("_provenance", {}),
        }

    result = _run_with_optional_hpc(
        tool_name="plot_variable_hpc",
        use_remote=use_remote,
        endpoint=endpoint,
        path_hint=grid_path,
        session_id=session_id,
        local_call=_local,
        remote_call=lambda agent: _run_sync(
            lambda: agent.plot_variable_remote(
                grid_path,
                data_path,
                variable_name,
                width,
                height,
                cmap,
                vmin,
                vmax,
                title,
                use_remote,
            )
        ),
    )
    return _plot_result_to_mcp_contents(result)


def plot_zonal_mean_hpc(
    grid_path: str,
    data_path: str,
    variable_name: str,
    width: int = 800,
    height: int = 400,
    lat_spec: Optional[tuple | float | List] = None,
    conservative: bool = False,
    line_color: str = "#1f77b4",
    title: Optional[str] = None,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
) -> list[Any]:
    """Render a zonal mean profile PNG with optional HPC execution.

    Parameters
    ----------
    grid_path : str
        Path to mesh grid file (local or HPC filesystem).
    data_path : str
        Path to data file (local or HPC filesystem).
    variable_name : str
        Face-centered variable to compute and plot.
    width : int
        Image width in pixels (default 800).
    height : int
        Image height in pixels (default 400).
    lat_spec : tuple | float | list | None
        Latitude specification for zonal bands.
    conservative : bool
        Use area-weighted conservative averaging.
    line_color : str
        Matplotlib color for the profile line (default "#1f77b4").
    title : str | None
        Custom plot title.
    use_remote : bool
        If True and HPC is configured, render on the remote endpoint.

    Returns
    -------
    dict
        - png_b64: Base64-encoded PNG string
        - image_size_bytes: PNG size in bytes
        - variable_name: Name of the plotted variable
        - latitudes: List of latitude values
        - zonal_mean_values: List of zonal mean values
        - execution_venue: "local" or "hpc:<endpoint_id>"
    """
    from .plotting import plot_zonal_mean

    def _local() -> Dict[str, Any]:
        import base64
        import json

        items = plot_zonal_mean(
            grid_path,
            data_path,
            variable_name,
            width=width,
            height=height,
            lat_spec=lat_spec,
            conservative=conservative,
            line_color=line_color,
            title=title,
        )
        img = items[0]
        meta = json.loads(items[1].text)
        return {
            "png_b64": img.data,
            "image_size_bytes": meta.get(
                "image_size_bytes", len(base64.b64decode(img.data))
            ),
            "variable_name": meta.get("variable_name", variable_name),
            "latitudes": meta.get("latitudes", []),
            "zonal_mean_values": meta.get("zonal_mean_values", []),
            "execution_venue": "local",
            "_provenance": meta.get("_provenance", {}),
        }

    result = _run_with_optional_hpc(
        tool_name="plot_zonal_mean_hpc",
        use_remote=use_remote,
        endpoint=endpoint,
        path_hint=grid_path,
        session_id=session_id,
        local_call=_local,
        remote_call=lambda agent: _run_sync(
            lambda: agent.plot_zonal_mean_remote(
                grid_path,
                data_path,
                variable_name,
                width,
                height,
                lat_spec,
                conservative,
                line_color,
                title,
                use_remote,
            )
        ),
    )
    return _plot_result_to_mcp_contents(result)
