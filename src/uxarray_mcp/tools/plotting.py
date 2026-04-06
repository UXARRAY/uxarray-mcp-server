"""MCP plotting tools for UXarray mesh visualization."""

import base64
from pathlib import Path
from typing import Any, Optional

import uxarray as ux

from uxarray_mcp.domain.mesh import load_grid
from uxarray_mcp.domain.plotting import render_mesh, render_variable, render_zonal_mean
from uxarray_mcp.domain.zonal import compute_zonal_mean_stats
from uxarray_mcp.provenance import attach_provenance


def plot_mesh(
    grid_path: str,
    width: int = 800,
    height: int = 400,
) -> dict[str, Any]:
    """Plot an unstructured mesh wireframe.

    Renders the mesh topology (edges/faces outline) and returns the image
    as a base64 PNG data URI that MCP clients can display inline.

    Args:
        grid_path: Path to the mesh file (supports UGRID, MPAS, SCRIP, ESMF,
                   etc.) or "healpix:<zoom_level>" for HEALPix grids.
        width: Image width in pixels (default 800).
        height: Image height in pixels (default 400).

    Returns:
        Dictionary containing:
        - image: Base64-encoded PNG data URI (data:image/png;base64,...)
        - image_size_bytes: Size of the PNG in bytes
        - grid_info: Grid summary (n_face, n_node, n_edge)
        - _provenance: Provenance metadata
    """
    grid = load_grid(grid_path)

    png_bytes = render_mesh(grid, width=width, height=height)
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    data_uri = f"data:image/png;base64,{b64}"

    result = {
        "image": data_uri,
        "image_size_bytes": len(png_bytes),
        "grid_info": {
            "n_face": int(grid.n_face),
            "n_node": int(grid.n_node),
            "n_edge": int(grid.n_edge),
        },
    }

    return attach_provenance(
        result,
        tool="plot_mesh",
        inputs={"grid_path": grid_path, "width": width, "height": height},
        artifacts=[
            {
                "type": "plot",
                "plot_type": "mesh_wireframe",
                "format": "png",
                "size_bytes": len(png_bytes),
            }
        ],
    )


def plot_variable(
    grid_path: str,
    data_path: str,
    variable_name: Optional[str] = None,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
) -> dict[str, Any]:
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
        cmap: Matplotlib colormap name (default "viridis").

    Returns:
        Dictionary containing:
        - image: Base64-encoded PNG data URI
        - image_size_bytes: Size of the PNG in bytes
        - variable_name: Name of the plotted variable
        - grid_info: Grid summary (n_face, n_node, n_edge)
        - _provenance: Provenance metadata
    """
    grid_file = Path(grid_path) if not grid_path.lower().startswith("healpix") else None
    data_file = Path(data_path)
    if grid_file and not grid_file.exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")
    if not data_file.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

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

    png_bytes = render_variable(uxda, width=width, height=height, cmap=cmap)
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    data_uri = f"data:image/png;base64,{b64}"

    result = {
        "image": data_uri,
        "image_size_bytes": len(png_bytes),
        "variable_name": variable_name,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }

    return attach_provenance(
        result,
        tool="plot_variable",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "width": width,
            "height": height,
            "cmap": cmap,
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


def plot_zonal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    width: int = 800,
    height: int = 400,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
) -> dict[str, Any]:
    """Plot a zonal mean profile (latitude vs value).

    Computes the zonal mean of a face-centered variable and renders
    a line chart as a base64 PNG data URI.

    Args:
        grid_path: Path to the mesh grid file.
        data_path: Path to the data file with variables.
        variable_name: Name of the face-centered variable to plot.
        width: Image width in pixels (default 800).
        height: Image height in pixels (default 400).
        lat_spec: Latitude specification for zonal bands. None uses default.
        conservative: If True, use area-weighted conservative averaging.

    Returns:
        Dictionary containing:
        - image: Base64-encoded PNG data URI
        - image_size_bytes: Size of the PNG in bytes
        - variable_name: Name of the plotted variable
        - latitudes: List of latitude values
        - zonal_mean_values: List of zonal mean values
        - _provenance: Provenance metadata
    """
    grid_file = Path(grid_path) if not grid_path.lower().startswith("healpix") else None
    data_file = Path(data_path)
    if grid_file and not grid_file.exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")
    if not data_file.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    uxds = ux.open_dataset(grid_path, data_path)

    zonal_result = compute_zonal_mean_stats(
        uxds, variable_name, lat_spec=lat_spec, conservative=conservative
    )

    latitudes = zonal_result["latitudes"]
    values = zonal_result["zonal_mean_values"]

    png_bytes = render_zonal_mean(
        latitudes, values, variable_name, width=width, height=height
    )
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    data_uri = f"data:image/png;base64,{b64}"

    result = {
        "image": data_uri,
        "image_size_bytes": len(png_bytes),
        "variable_name": variable_name,
        "latitudes": latitudes,
        "zonal_mean_values": values,
    }

    return attach_provenance(
        result,
        tool="plot_zonal_mean",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "width": width,
            "height": height,
            "conservative": conservative,
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
