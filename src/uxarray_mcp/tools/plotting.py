"""MCP plotting tools for UXarray mesh visualization."""

import base64
import json
from pathlib import Path
from typing import Any, Optional

import uxarray as ux
from mcp.types import ImageContent, TextContent

from uxarray_mcp.domain.mesh import load_grid
from uxarray_mcp.domain.plotting import (
    render_mesh,
    render_mesh_geo,
    render_variable,
    render_zonal_mean,
)
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


def plot_mesh_geo(
    grid_path: Optional[str] = None,
    width: int = 1200,
    height: int = 800,
    lon_bounds: Optional[list] = None,
    lat_bounds: Optional[list] = None,
    coastlines: bool = True,
    borders: bool = True,
    rivers: bool = False,
    lakes: bool = True,
    show_mesh_boundary: bool = False,
    basemap: bool = False,
    mesh_alpha: float = 0.35,
    mesh_edgecolor: str = "#333333",
    mesh_linewidth: float = 0.25,
    cities: bool = False,
    city_scale: str = "50m",
    session_id: Optional[str] = None,
    dataset_handle: Optional[str] = None,
) -> list[Any]:
    """Render a mesh with geographic context: coastlines, borders, lakes, and optional terrain.

    This tool produces a Cartopy-backed geographic plot that shows the mesh
    topology overlaid on a proper map with natural geographic features.
    It works for all mesh formats (MPAS, UGRID, SCRIP, ESMF, ICON, HEALPix).

    ## When to use this vs plot_mesh

    Use ``plot_mesh_geo`` when the user wants to see the mesh **in geographic
    context** — where it is on the globe, how it relates to coastlines, which
    regions it covers. Use ``plot_mesh`` (the HoloViews wireframe) for pure
    topology inspection without geographic reference.

    ## LLM routing guide — map user intent to parameters

    **Default call** — "show me the mesh", "plot the grid", "what does the mesh
    look like": call with all defaults. Coastlines and borders are on by default;
    the mesh cells are semi-transparent white so the land/ocean background shows
    through.

    **Regional zoom** — "zoom to the Gulf of Mexico", "show North America",
    "plot the European region":
      Set ``lon_bounds`` and ``lat_bounds``.
      Examples: Gulf of Mexico → lon_bounds=[-98,-79], lat_bounds=[17,32]
                North America → lon_bounds=[-140,-50], lat_bounds=[15,75]
                Europe → lon_bounds=[-15,45], lat_bounds=[35,72]

    **Mesh boundary** — "show the mesh boundary", "highlight where the mesh
    ends", "trace the coastline from the mesh itself":
      Set ``show_mesh_boundary=True``. Traces actual cell boundary edges in
      red. Only meaningful for culled/regional meshes (MPAS ocean, regional
      UGRID). Silently skipped for closed meshes (ICON, HEALPix). Off by
      default because boundary construction can be slow for large meshes.

    **Rivers** — "add rivers", "show major rivers", "include waterways":
      Set ``rivers=True``.

    **City labels** — "show cities", "label major cities", "add city names",
    "where is Chicago on this mesh":
      Set ``cities=True``. Use ``city_scale="50m"`` for major cities only
      (capitals + large cities, ~500 worldwide). Use ``city_scale="10m"``
      for dense coverage (~7000 cities). Default is "50m".
      Do NOT set cities=True unless the user explicitly asks for city labels.

    **Terrain basemap** — "with terrain", "satellite background",
    "topographic background", "show elevation":
      Set ``basemap=True``. Requires ``pip install contextily`` and internet
      access. Falls back to a NASA stock image if contextily is not installed.
      Do NOT set basemap=True by default — it requires an external network call.

    **Transparent cells** — "more transparent", "see through the cells",
    "show the background more":
      Decrease ``mesh_alpha`` (e.g. 0.15). Range 0–1.

    **Opaque / wireframe** — "just show the mesh edges", "wireframe only",
    "no fill":
      Set ``mesh_alpha=0.0`` or ``mesh_alpha=0.05``, increase ``mesh_linewidth``
      (e.g. 0.5).

    **No borders** — "no political boundaries", "just coastlines":
      Set ``borders=False``.

    **No geographic features** — "clean mesh", "mesh only":
      Set ``coastlines=False, borders=False, lakes=False``.

    Parameters
    ----------
    grid_path : str
        Path to the mesh file (UGRID, MPAS, SCRIP, ESMF, ICON, etc.) or
        ``"healpix:<zoom>"`` for HEALPix grids.
    width : int, default 1200
        Image width in pixels.
    height : int, default 800
        Image height in pixels.
    lon_bounds : list[float, float] | None
        Longitude range [west, east] to zoom the plot. None = global.
    lat_bounds : list[float, float] | None
        Latitude range [south, north] to zoom the plot. None = global.
    coastlines : bool, default True
        Draw Cartopy 50m Natural Earth coastlines.
    borders : bool, default True
        Draw national borders.
    rivers : bool, default False
        Draw major rivers in blue. Set True only when user asks.
    lakes : bool, default True
        Fill lakes with light blue.
    show_mesh_boundary : bool, default False
        Trace the actual mesh boundary edges in red. Only useful for culled/
        open meshes. Off by default — can be slow for large meshes.
    basemap : bool, default False
        Fetch terrain tile background via contextily. Requires internet access.
        Off by default — set True only when user explicitly requests terrain.
    mesh_alpha : float, default 0.35
        Cell fill transparency (0 = invisible, 1 = opaque).
    mesh_edgecolor : str, default "#333333"
        Cell edge colour.
    mesh_linewidth : float, default 0.25
        Cell edge width in points.
    cities : bool, default False
        Add city labels. Off by default. Set True only when user asks for
        city names or wants to identify specific locations.
    city_scale : str, default "50m"
        ``"50m"`` = major cities only (~500 worldwide).
        ``"10m"`` = dense coverage (~7000 cities).
    session_id : str | None
        Session for dataset handle resolution.
    dataset_handle : str | None
        Handle from ``register_dataset``.

    Returns
    -------
    list
        MCP content list: [ImageContent (inline PNG), TextContent (provenance JSON)].
    """
    grid_path, _ = _resolve_plot_paths(grid_path, None, session_id, dataset_handle)

    if not grid_path.lower().startswith("healpix"):
        grid_file = Path(grid_path)
        if not grid_file.exists():
            raise FileNotFoundError(f"Grid file not found: {grid_path}")
        if grid_file.stat().st_size == 0:
            raise ValueError(f"Grid file is empty: {grid_path}")

    grid = load_grid(grid_path)

    png_bytes = render_mesh_geo(
        grid,
        width=width,
        height=height,
        lon_bounds=tuple(lon_bounds) if lon_bounds else None,
        lat_bounds=tuple(lat_bounds) if lat_bounds else None,
        coastlines=coastlines,
        borders=borders,
        rivers=rivers,
        lakes=lakes,
        show_mesh_boundary=show_mesh_boundary,
        basemap=basemap,
        mesh_alpha=mesh_alpha,
        mesh_edgecolor=mesh_edgecolor,
        mesh_linewidth=mesh_linewidth,
    )

    # ── Optional city labels (post-render pass) ───────────────────────────────
    if cities:
        png_bytes = _add_city_labels(
            png_bytes,
            width,
            height,
            lon_bounds,
            lat_bounds,
            city_scale=city_scale,
        )

    b64 = base64.b64encode(png_bytes).decode("utf-8")
    result = {
        "image_size_bytes": len(png_bytes),
        "grid_info": {
            "n_face": int(grid.n_face),
            "n_node": int(grid.n_node),
            "n_edge": int(grid.n_edge),
        },
        "parameters": {
            "coastlines": coastlines,
            "borders": borders,
            "rivers": rivers,
            "lakes": lakes,
            "show_mesh_boundary": show_mesh_boundary,
            "basemap": basemap,
            "cities": cities,
        },
    }
    provenance = attach_provenance(
        result,
        tool="plot_mesh_geo",
        inputs={
            "grid_path": grid_path,
            "lon_bounds": lon_bounds,
            "lat_bounds": lat_bounds,
            "show_mesh_boundary": show_mesh_boundary,
            "basemap": basemap,
            "cities": cities,
        },
        artifacts=[
            {
                "type": "plot",
                "plot_type": "mesh_geographic",
                "format": "png",
                "size_bytes": len(png_bytes),
            }
        ],
    )
    return [
        ImageContent(type="image", data=b64, mimeType="image/png"),
        TextContent(type="text", text=json.dumps(provenance, indent=2)),
    ]


def _add_city_labels(
    png_bytes: bytes,
    width: int,
    height: int,
    lon_bounds: Optional[list],
    lat_bounds: Optional[list],
    city_scale: str = "50m",
) -> bytes:
    """Overlay city labels on an existing PNG using cartopy populated places."""
    import io as _io

    import cartopy.crs as ccrs
    import cartopy.io.shapereader as shpreader
    from PIL import Image

    # Load the existing PNG and composite city labels on top
    base_img = Image.open(_io.BytesIO(png_bytes)).convert("RGBA")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dpi = 120
    proj = ccrs.PlateCarree()
    fig, ax = plt.subplots(
        figsize=(width / dpi, height / dpi),
        dpi=dpi,
        subplot_kw={"projection": proj},
        facecolor=(0, 0, 0, 0),  # transparent
    )
    fig.patch.set_alpha(0)
    ax.patch.set_alpha(0)

    if lon_bounds and lat_bounds:
        ax.set_extent(
            [lon_bounds[0], lon_bounds[1], lat_bounds[0], lat_bounds[1]], crs=proj
        )
    else:
        ax.set_global()

    try:
        shpfile = shpreader.natural_earth(
            resolution=city_scale, category="cultural", name="populated_places"
        )
        reader = shpreader.Reader(shpfile)
        for record in reader.records():
            geom = record.geometry
            name = record.attributes.get("NAME", "")
            lon, lat = geom.x, geom.y
            if lon_bounds and lat_bounds:
                if not (
                    lon_bounds[0] <= lon <= lon_bounds[1]
                    and lat_bounds[0] <= lat <= lat_bounds[1]
                ):
                    continue
            ax.plot(lon, lat, "k.", markersize=2, transform=proj, zorder=6)
            ax.text(
                lon + 0.3,
                lat,
                name,
                fontsize=5.5,
                color="#111",
                transform=proj,
                zorder=7,
                bbox=dict(
                    facecolor="white",
                    alpha=0.6,
                    pad=0.5,
                    edgecolor="none",
                    boxstyle="round,pad=0.2",
                ),
            )
    except Exception:
        pass  # silently skip if shapefile unavailable

    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)

    overlay = Image.open(buf).convert("RGBA").resize(base_img.size)
    composite = Image.alpha_composite(base_img, overlay)

    out = _io.BytesIO()
    composite.save(out, format="PNG")
    out.seek(0)
    return out.read()


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
