"""Shared plotting logic for UXarray MCP Server.

Pure rendering functions that take loaded UXarray objects and return
PNG bytes. No MCP, provenance, or file-loading logic belongs here.

## Geographic rendering

``render_mesh_geo`` produces a Cartopy-backed figure with:

- Cartopy 50m Natural Earth land/ocean/coastlines/lakes (always, no new deps)
- Semi-transparent white mesh cells overlaid (alpha=0.35)
- Mesh-derived boundary edges in red — traced from ``boundary_edge_indices``
  using ``edge_node_connectivity`` so the boundary follows actual cell edges
  rather than a geographic dataset. This is format-agnostic: it works for
  MPAS, UGRID, SCRIP, ESMF, and any other format UXarray supports.
  For closed spherical meshes (ICON, HEALPix) ``boundary_edge_indices``
  returns an empty array and the feature is silently skipped.
- Optional contextily terrain basemap (``basemap=True``); requires
  ``pip install contextily`` and internet access. Falls back to
  ``ax.stock_img()`` when contextily is not installed.

## Performance note

``boundary_edge_indices`` triggers connectivity construction and can be slow
for very large meshes (>1M faces). The MCP tool exposes
``show_mesh_boundary`` which defaults to **False** — users opt in explicitly.
"""

import io
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render_mesh(
    grid: Any,
    width: int = 800,
    height: int = 400,
) -> bytes:
    """Render a mesh wireframe to PNG bytes.

    Parameters
    ----------
    grid : ux.Grid
        Loaded UXarray grid.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.

    Returns
    -------
    bytes
        PNG image data.
    """
    import holoviews as hv

    hv.extension("matplotlib")

    dpi = 100
    fig_w = width / dpi
    fig_h = height / dpi

    element = grid.plot.mesh(backend="matplotlib")

    renderer = hv.Store.renderers["matplotlib"]
    plot = renderer.get_plot(element)
    fig = plot.state
    fig.set_size_inches(fig_w, fig_h)
    fig.set_dpi(dpi)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError(
            "Rendered mesh plot is empty. The file may be empty or contain no "
            "plottable geometry."
        )
    return png_bytes


def render_mesh_geo(
    grid: Any,
    width: int = 1200,
    height: int = 800,
    lon_bounds: tuple[float, float] | None = None,
    lat_bounds: tuple[float, float] | None = None,
    coastlines: bool = True,
    borders: bool = True,
    rivers: bool = False,
    lakes: bool = True,
    show_mesh_boundary: bool = False,
    basemap: bool = False,
    mesh_alpha: float = 0.35,
    mesh_edgecolor: str = "#333333",
    mesh_linewidth: float = 0.25,
) -> tuple[bytes, dict]:
    """Render a mesh with geographic context using Cartopy.

    Returns
    -------
    tuple[bytes, dict]
        ``(png_bytes, render_info)`` where ``render_info`` is a dict describing
        what was actually drawn — used by the tool layer to build a human-readable
        note for the user. Keys:

        ``n_faces_rendered``
            Number of mesh faces included in the plot.
        ``n_faces_total``
            Total faces in the grid.
        ``boundary_drawn``
            True if mesh boundary edges were drawn in red.
        ``n_boundary_edges``
            Number of boundary edge segments drawn.
        ``boundary_status``
            One of ``"drawn"``, ``"closed_mesh"``, ``"all_filtered"``,
            ``"disabled"``.
        ``seam_faces_skipped``
            Number of faces skipped due to antimeridian crossing (will be 0
            once UXarray PR #1519 lands).
        ``basemap_used``
            ``"contextily"``, ``"stock_img"``, or ``"none"``.
        ``features_drawn``
            List of geographic features added (e.g. ``["coastlines","borders"]``).
        ``region``
            ``"global"`` or ``"regional"``.


    Parameters
    ----------
    grid : ux.Grid
        Loaded UXarray grid (any format — MPAS, UGRID, SCRIP, ICON, HEALPix).
    width, height : int
        Image dimensions in pixels.
    lon_bounds, lat_bounds : tuple[float, float] | None
        If provided, subset the mesh to this region before rendering.
    coastlines : bool, default True
        Add Cartopy 50m Natural Earth coastlines.
    borders : bool, default True
        Add country borders.
    rivers : bool, default False
        Add major rivers.
    lakes : bool, default True
        Add lakes with blue fill.
    show_mesh_boundary : bool, default False
        Trace the actual mesh boundary edges in red using
        ``boundary_edge_indices`` and ``edge_node_connectivity``.
        Format-agnostic — works for all formats; silently skipped when the
        mesh has no boundary (ICON, HEALPix). Disabled by default because
        boundary construction can be slow for large meshes.
    basemap : bool, default False
        Fetch terrain tiles via contextily (requires ``pip install contextily``
        and internet access). Falls back to ``ax.stock_img()`` if not installed.
    mesh_alpha : float, default 0.35
        Opacity of mesh cell fill. 0 = invisible, 1 = opaque.
    mesh_edgecolor : str, default "#333333"
        Colour of mesh cell edges.
    mesh_linewidth : float, default 0.25
        Width of mesh cell edges in points.

    """
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    import numpy as np
    from matplotlib.collections import LineCollection, PolyCollection

    proj = ccrs.PlateCarree()
    dpi = 120
    fig, ax = plt.subplots(
        figsize=(width / dpi, height / dpi),
        dpi=dpi,
        subplot_kw={"projection": proj},
        facecolor="white",
    )

    # ── Region ────────────────────────────────────────────────────────────────
    is_regional = lon_bounds is not None and lat_bounds is not None
    if is_regional and lon_bounds is not None and lat_bounds is not None:
        ax.set_extent(
            [lon_bounds[0], lon_bounds[1], lat_bounds[0], lat_bounds[1]], crs=proj
        )
        g = grid.subset.bounding_box(
            lon_bounds=list(lon_bounds), lat_bounds=list(lat_bounds)
        )
    else:
        ax.set_global()
        g = grid

    n_faces_total = int(grid.n_face)

    # ── Basemap ───────────────────────────────────────────────────────────────
    basemap_used = "none"
    if basemap:
        try:
            import contextily as ctx

            ctx.add_basemap(
                ax,
                crs=proj,
                source=ctx.providers.OpenTopoMap,
                zoom="auto",
                attribution=False,
            )
            basemap_used = "contextily"
        except ImportError:
            ax.stock_img()
            basemap_used = "stock_img"
    else:
        ax.add_feature(cfeature.LAND.with_scale("110m"), facecolor="#e8dcc8", zorder=1)
        ax.add_feature(cfeature.OCEAN.with_scale("110m"), facecolor="#d4e8f5", zorder=1)

    # ── Mesh cells ────────────────────────────────────────────────────────────
    node_lon = g.node_lon.values
    node_lat = g.node_lat.values
    conn = g.face_node_connectivity.values
    fill = np.iinfo(conn.dtype).min if np.issubdtype(conn.dtype, np.integer) else -1

    polys = []
    seam_skipped = 0
    for row in conn:
        idx = row[row != fill]
        if len(idx) < 3:
            continue
        lons = node_lon[idx]
        lats = node_lat[idx]
        if lons.max() - lons.min() > 180:
            seam_skipped += 1
            continue  # antimeridian-crossing — PR #1519 will split properly
        polys.append(np.column_stack([lons, lats]))

    if polys:
        col = PolyCollection(
            polys,
            facecolors="white",
            edgecolors=mesh_edgecolor,
            linewidths=mesh_linewidth,
            alpha=mesh_alpha,
            transform=proj,
            zorder=2,
        )
        ax.add_collection(col)

    # ── Mesh-derived boundary edges (opt-in) ──────────────────────────────────
    boundary_drawn = False
    n_boundary_drawn = 0
    boundary_status = "disabled"

    if show_mesh_boundary:
        try:
            b_idx = g.boundary_edge_indices
            n_raw = len(b_idx)
            if n_raw == 0:
                boundary_status = "closed_mesh"
            else:
                enc = g.edge_node_connectivity
                lines = []
                for ei in b_idx:
                    n0, n1 = int(enc[ei, 0].values), int(enc[ei, 1].values)
                    if n0 < 0 or n1 < 0:
                        continue
                    lon0, lat0 = node_lon[n0], node_lat[n0]
                    lon1, lat1 = node_lon[n1], node_lat[n1]
                    dlon = abs(lon1 - lon0)
                    if dlon > 10.0:
                        continue  # antimeridian-crossing edge
                    if dlon < 0.1 and abs(round(lon0) % 180) < 1:
                        continue  # prime meridian / antimeridian seam artefact
                    lines.append([[lon0, lat0], [lon1, lat1]])

                if lines:
                    lc = LineCollection(
                        lines,
                        colors="#cc2200",
                        linewidths=1.8,
                        transform=proj,
                        zorder=5,
                    )
                    ax.add_collection(lc)
                    boundary_drawn = True
                    n_boundary_drawn = len(lines)
                    boundary_status = "drawn"
                else:
                    boundary_status = "all_filtered"
        except Exception:
            boundary_status = "error"

    # ── Cartopy geographic features ───────────────────────────────────────────
    scale = "50m"
    features_drawn = []
    if coastlines:
        ax.add_feature(
            cfeature.COASTLINE.with_scale(scale),
            linewidth=0.9,
            edgecolor="#222222",
            zorder=4,
        )
        features_drawn.append("coastlines")
    if borders:
        ax.add_feature(
            cfeature.BORDERS.with_scale(scale),
            linewidth=0.4,
            edgecolor="#555555",
            linestyle="--",
            zorder=4,
        )
        features_drawn.append("borders")
    if lakes:
        ax.add_feature(
            cfeature.LAKES.with_scale(scale),
            facecolor="#aad4f5",
            edgecolor="#3399ff",
            linewidth=0.4,
            zorder=3,
        )
        features_drawn.append("lakes")
    if rivers:
        ax.add_feature(
            cfeature.RIVERS.with_scale(scale),
            edgecolor="#3399ff",
            linewidth=0.6,
            zorder=3,
        )
        features_drawn.append("rivers")

    ax.gridlines(linewidth=0.2, color="gray", alpha=0.4)
    fig.tight_layout(pad=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError("Rendered geographic mesh plot is empty.")

    render_info = {
        "n_faces_rendered": len(polys),
        "n_faces_total": n_faces_total,
        "boundary_drawn": boundary_drawn,
        "n_boundary_edges": n_boundary_drawn,
        "boundary_status": boundary_status,
        "seam_faces_skipped": seam_skipped,
        "basemap_used": basemap_used,
        "features_drawn": features_drawn,
        "region": "regional" if is_regional else "global",
    }
    return png_bytes, render_info


_FACE_DIMS = {"n_face", "nCells"}


def _reduce_to_face(uxda: Any, time_index: int = 0) -> Any:
    """Squeeze or isel any non-face extra dims so uxda is 1-D face-centered."""
    extra = [d for d in uxda.dims if d not in _FACE_DIMS]
    if not extra:
        return uxda
    return uxda.isel(**{d: 0 if uxda.sizes[d] == 1 else time_index for d in extra})


def render_variable(
    uxda: Any,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    title: str | None = None,
    time_index: int = 0,
) -> bytes:
    """Render a face-centered variable as a filled polygon plot to PNG bytes.

    Parameters
    ----------
    uxda : ux.UxDataArray
        Face-centered UXarray data array.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    cmap : str
        Matplotlib colormap name (e.g. "viridis", "plasma", "RdBu_r", "coolwarm").
    vmin : float | None
        Minimum value for the colormap. Defaults to data minimum.
    vmax : float | None
        Maximum value for the colormap. Defaults to data maximum.
    title : str | None
        Plot title. Defaults to the variable name.

    Returns
    -------
    bytes
        PNG image data.
    """
    import holoviews as hv

    hv.extension("matplotlib")

    dpi = 100
    fig_w = width / dpi
    fig_h = height / dpi

    kwargs: dict[str, Any] = {"backend": "matplotlib", "cmap": cmap}
    if vmin is not None:
        kwargs["clim"] = (vmin, vmax if vmax is not None else uxda.values.max())
    elif vmax is not None:
        kwargs["clim"] = (uxda.values.min(), vmax)

    uxda = _reduce_to_face(uxda, time_index)
    element = uxda.plot.polygons(**kwargs)

    renderer = hv.Store.renderers["matplotlib"]
    plot = renderer.get_plot(element)
    fig = plot.state
    fig.set_size_inches(fig_w, fig_h)
    fig.set_dpi(dpi)

    if title is not None:
        fig.axes[0].set_title(title)

    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError(
            "Rendered variable plot is empty. The file may be empty or contain "
            "no plottable data."
        )
    return png_bytes


def render_zonal_mean(
    latitudes: list[float],
    values: list[float],
    variable_name: str,
    width: int = 800,
    height: int = 400,
    line_color: str = "#1f77b4",
    title: str | None = None,
) -> bytes:
    """Render a zonal mean profile (latitude vs value) to PNG bytes.

    Parameters
    ----------
    latitudes : list[float]
        Latitude values.
    values : list[float]
        Zonal mean values at each latitude.
    variable_name : str
        Variable name for the axis label.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    line_color : str
        Matplotlib color string for the profile line (e.g. "red", "#e74c3c",
        "steelblue"). Defaults to "#1f77b4" (matplotlib blue).
    title : str | None
        Plot title. Defaults to "Zonal Mean — <variable_name>".

    Returns
    -------
    bytes
        PNG image data.
    """
    dpi = 100
    fig_w = width / dpi
    fig_h = height / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    ax.plot(latitudes, values, linewidth=1.5, color=line_color)
    ax.set_xlabel("Latitude (°)")
    ax.set_ylabel(variable_name)
    ax.set_title(title if title is not None else f"Zonal Mean — {variable_name}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError(
            "Rendered zonal mean plot is empty. The data may be empty or contain "
            "no plottable values."
        )
    return png_bytes
