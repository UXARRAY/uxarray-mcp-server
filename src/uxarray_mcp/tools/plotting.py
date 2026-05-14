"""MCP plotting tools for UXarray mesh visualization."""

import base64
import json
from pathlib import Path
from typing import Any, Optional

import uxarray as ux
from mcp.types import ImageContent, TextContent

from uxarray_mcp.domain.mesh import load_grid
from uxarray_mcp.domain.plotting import render_mesh, render_variable, render_zonal_mean
from uxarray_mcp.domain.zonal import compute_zonal_mean_stats
from uxarray_mcp.provenance import attach_provenance


def _resolve_plot_paths(
    grid_path: Optional[str],
    data_path: Optional[str],
    session_id: Optional[str],
    dataset_handle: Optional[str],
) -> tuple[str, Optional[str]]:
    """Resolve grid/data paths from either direct paths or a session dataset handle."""
    if dataset_handle is not None:
        if session_id is None:
            raise ValueError("session_id is required when dataset_handle is provided.")
        from uxarray_mcp.state import get_session

        session = get_session(session_id)
        dataset = session["datasets"].get(dataset_handle)
        if dataset is None:
            raise FileNotFoundError(
                f"Dataset handle {dataset_handle!r} not found in session {session_id!r}"
            )
        return dataset["grid_path"], dataset.get("data_path")
    if grid_path is None:
        raise ValueError("grid_path is required when dataset_handle is not provided.")
    return grid_path, data_path


def _plot_mesh_local(
    grid_path: Optional[str] = None,
    width: int = 800,
    height: int = 400,
    session_id: Optional[str] = None,
    dataset_handle: Optional[str] = None,
) -> list[Any]:
    """Plot an unstructured mesh wireframe.

    Renders the mesh topology (edges/faces outline) and returns the image
    as a base64 PNG data URI that MCP clients can display inline.

    Args:
        grid_path: Path to the mesh file (supports UGRID, MPAS, SCRIP, ESMF,
                   etc.) or "healpix:<zoom_level>" for HEALPix grids.
                   Optional when session_id + dataset_handle are provided.
        width: Image width in pixels (default 800).
        height: Image height in pixels (default 400).
        session_id: Session ID for looking up a registered dataset handle.
        dataset_handle: Handle returned by register_dataset. When provided,
                        grid_path is looked up from the session.

    Returns:
        Dictionary containing:
        - image: Base64-encoded PNG data URI (data:image/png;base64,...)
        - image_size_bytes: Size of the PNG in bytes
        - grid_info: Grid summary (n_face, n_node, n_edge)
        - _provenance: Provenance metadata
    """
    grid_path, _ = _resolve_plot_paths(grid_path, None, session_id, dataset_handle)

    grid_file = Path(grid_path) if not grid_path.lower().startswith("healpix") else None
    if grid_file:
        if not grid_file.exists():
            raise FileNotFoundError(f"Grid file not found: {grid_path}")
        if grid_file.stat().st_size == 0:
            raise ValueError(
                f"Grid file appears to be empty: {grid_path}. "
                "The file may not have been written correctly."
            )

    grid = load_grid(grid_path)

    png_bytes = render_mesh(grid, width=width, height=height)
    b64 = base64.b64encode(png_bytes).decode("utf-8")

    result = {
        "image_size_bytes": len(png_bytes),
        "grid_info": {
            "n_face": int(grid.n_face),
            "n_node": int(grid.n_node),
            "n_edge": int(grid.n_edge),
        },
    }

    provenance = attach_provenance(
        result,
        tool="plot_mesh",
        inputs={
            "grid_path": grid_path,
            "width": width,
            "height": height,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
        artifacts=[
            {
                "type": "plot",
                "plot_type": "mesh_wireframe",
                "format": "png",
                "size_bytes": len(png_bytes),
            }
        ],
    )

    return [
        ImageContent(type="image", data=b64, mimeType="image/png"),
        TextContent(type="text", text=json.dumps(provenance, indent=2)),
    ]


def _plot_variable_local(
    grid_path: Optional[str] = None,
    data_path: Optional[str] = None,
    variable_name: Optional[str] = None,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    title: Optional[str] = None,
    time_index: int = 0,
    session_id: Optional[str] = None,
    dataset_handle: Optional[str] = None,
) -> list[Any]:
    """Plot a face-centered variable as a filled polygon map.

    Renders a choropleth-style visualization of the variable on the mesh
    and returns the image as a base64 PNG data URI.

    Args:
        grid_path: Path to the mesh grid file.
        data_path: Path to the data file with variables.
        variable_name: Name of the variable to plot. If None, the first
                       face-centered variable is used.
        width: Image width in pixels (default 800).
        height: Image height in pixels (default 400).
        cmap: Matplotlib colormap name (default "viridis"). Common choices:
              "plasma", "inferno", "magma", "RdBu_r", "coolwarm", "bwr",
              "seismic", "PiYG", "PRGn". Append "_r" to reverse any colormap.
        vmin: Minimum value for the colormap scale. Defaults to data minimum.
              Useful for comparing plots across datasets on a consistent scale.
        vmax: Maximum value for the colormap scale. Defaults to data maximum.
        title: Custom plot title. Defaults to the variable name.

    Returns:
        Dictionary containing:
        - image: Base64-encoded PNG data URI
        - image_size_bytes: Size of the PNG in bytes
        - variable_name: Name of the plotted variable
        - grid_info: Grid summary (n_face, n_node, n_edge)
        - _provenance: Provenance metadata

    Examples:
        Basic plot with default colormap::

            plot_variable("grid.nc", "data.nc", "temperature")

        Diverging colormap centered on zero for anomaly data::

            plot_variable(
                "grid.nc", "data.nc", "temp_anomaly", cmap="RdBu_r", vmin=-5.0, vmax=5.0
            )

        Fixed scale for comparing two datasets::

            plot_variable("grid.nc", "jan.nc", "precip", vmin=0, vmax=100)
            plot_variable("grid.nc", "jul.nc", "precip", vmin=0, vmax=100)
    """
    grid_path, data_path = _resolve_plot_paths(
        grid_path, data_path, session_id, dataset_handle
    )
    if data_path is None:
        raise ValueError(
            "data_path is required for plot_variable. "
            "Provide data_path directly or register a dataset with a data file."
        )

    grid_file = Path(grid_path) if not grid_path.lower().startswith("healpix") else None
    data_file = Path(data_path)
    if grid_file:
        if not grid_file.exists():
            raise FileNotFoundError(f"Grid file not found: {grid_path}")
        if grid_file.stat().st_size == 0:
            raise ValueError(
                f"Grid file appears to be empty: {grid_path}. "
                "The file may not have been written correctly."
            )
    if not data_file.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")
    if data_file.stat().st_size == 0:
        raise ValueError(
            f"Data file appears to be empty: {data_path}. "
            "The file may not have been written correctly."
        )

    uxds = ux.open_dataset(grid_path, data_path)

    if variable_name is None:
        for var in uxds.data_vars:
            if "n_face" in uxds[var].dims or "nCells" in uxds[var].dims:
                variable_name = var
                break
        if variable_name is None:
            raise ValueError(
                "No face-centered variable found. "
                f"Available variables: {list(uxds.data_vars.keys())}"
            )

    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. "
            f"Available: {list(uxds.data_vars.keys())}"
        )

    uxda = uxds[variable_name]
    if "n_face" not in uxda.dims and "nCells" not in uxda.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Polygon plots require face-centered data."
        )

    png_bytes = render_variable(
        uxda,
        width=width,
        height=height,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        title=title,
        time_index=time_index,
    )
    b64 = base64.b64encode(png_bytes).decode("utf-8")

    result = {
        "image_size_bytes": len(png_bytes),
        "variable_name": variable_name,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }

    provenance = attach_provenance(
        result,
        tool="plot_variable",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "width": width,
            "height": height,
            "cmap": cmap,
            "vmin": vmin,
            "vmax": vmax,
            "title": title,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
        selected_variable=variable_name,
        artifacts=[
            {
                "type": "plot",
                "plot_type": "variable_polygons",
                "variable": variable_name,
                "format": "png",
                "size_bytes": len(png_bytes),
            }
        ],
    )

    return [
        ImageContent(type="image", data=b64, mimeType="image/png"),
        TextContent(type="text", text=json.dumps(provenance, indent=2)),
    ]


def _plot_zonal_mean_local(
    grid_path: Optional[str] = None,
    data_path: Optional[str] = None,
    variable_name: Optional[str] = None,
    width: int = 800,
    height: int = 400,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
    line_color: str = "#1f77b4",
    title: Optional[str] = None,
    session_id: Optional[str] = None,
    dataset_handle: Optional[str] = None,
) -> list[Any]:
    """Plot a zonal mean profile (latitude vs value).

    Computes the zonal mean of a face-centered variable and renders
    a line chart as a base64 PNG data URI.

    Args:
        grid_path: Path to the mesh grid file.
        data_path: Path to the data file with variables.
        variable_name: Name of the face-centered variable to plot.
        width: Image width in pixels (default 800).
        height: Image height in pixels (default 400).
        lat_spec: Latitude specification for zonal bands. None uses default
                  bands from -90 to 90 in 10-degree steps.
        conservative: If True, use area-weighted conservative averaging.
        line_color: Matplotlib color string for the profile line. Accepts
                    named colors ("red", "steelblue", "darkorange"), hex
                    strings ("#e74c3c"), or any valid matplotlib color.
                    Defaults to "#1f77b4" (matplotlib blue).
        title: Custom plot title. Defaults to "Zonal Mean — <variable_name>".

    Returns:
        Dictionary containing:
        - image: Base64-encoded PNG data URI
        - image_size_bytes: Size of the PNG in bytes
        - variable_name: Name of the plotted variable
        - latitudes: List of latitude values
        - zonal_mean_values: List of zonal mean values
        - _provenance: Provenance metadata

    Examples:
        Default profile::

            plot_zonal_mean("grid.nc", "data.nc", "temperature")

        Custom color and title::

            plot_zonal_mean(
                "grid.nc",
                "data.nc",
                "temperature",
                line_color="darkorange",
                title="Jan Temperature Zonal Mean",
            )

        High-resolution latitude bands::

            plot_zonal_mean(
                "grid.nc",
                "data.nc",
                "precipitation",
                lat_spec=(-90, 90, 2),
                conservative=True,
            )
    """
    grid_path, data_path = _resolve_plot_paths(
        grid_path, data_path, session_id, dataset_handle
    )
    if data_path is None:
        raise ValueError(
            "data_path is required for plot_zonal_mean. "
            "Provide data_path directly or register a dataset with a data file."
        )
    if variable_name is None:
        raise ValueError("variable_name is required for plot_zonal_mean.")

    grid_file = Path(grid_path) if not grid_path.lower().startswith("healpix") else None
    data_file = Path(data_path)
    if grid_file:
        if not grid_file.exists():
            raise FileNotFoundError(f"Grid file not found: {grid_path}")
        if grid_file.stat().st_size == 0:
            raise ValueError(
                f"Grid file appears to be empty: {grid_path}. "
                "The file may not have been written correctly."
            )
    if not data_file.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")
    if data_file.stat().st_size == 0:
        raise ValueError(
            f"Data file appears to be empty: {data_path}. "
            "The file may not have been written correctly."
        )

    uxds = ux.open_dataset(grid_path, data_path)

    zonal_result = compute_zonal_mean_stats(
        uxds, variable_name, lat_spec=lat_spec, conservative=conservative
    )

    latitudes = zonal_result["latitudes"]
    values = zonal_result["zonal_mean_values"]

    png_bytes = render_zonal_mean(
        latitudes,
        values,
        variable_name,
        width=width,
        height=height,
        line_color=line_color,
        title=title,
    )
    b64 = base64.b64encode(png_bytes).decode("utf-8")

    result = {
        "image_size_bytes": len(png_bytes),
        "variable_name": variable_name,
        "latitudes": latitudes,
        "zonal_mean_values": values,
    }

    provenance = attach_provenance(
        result,
        tool="plot_zonal_mean",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "width": width,
            "height": height,
            "conservative": conservative,
            "line_color": line_color,
            "title": title,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
        selected_variable=variable_name,
        artifacts=[
            {
                "type": "plot",
                "plot_type": "zonal_mean_profile",
                "variable": variable_name,
                "format": "png",
                "size_bytes": len(png_bytes),
            }
        ],
    )

    return [
        ImageContent(type="image", data=b64, mimeType="image/png"),
        TextContent(type="text", text=json.dumps(provenance, indent=2)),
    ]
