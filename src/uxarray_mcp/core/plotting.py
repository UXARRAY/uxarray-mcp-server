"""Pure rendering: loaded UXarray objects in, PNG bytes plus render metadata out.

Meshes above ``RASTERIZE_ABOVE_FACES`` are rasterized with datashader at the
requested pixel size instead of drawing one matplotlib polygon per face; when
datashader is missing, face centres are drawn as a scatter and the
``render_mode`` says so.
"""

from __future__ import annotations

import io
from typing import Any

import matplotlib

from uxarray_mcp.core.dims import face_slice_selection, reduce_to_face

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RASTERIZE_ABOVE_FACES = 200_000
DPI = 100
ANTIMERIDIAN_SPAN_DEG = 180.0

try:
    from holoviews.operation.datashader import rasterize as _hv_rasterize

    DATASHADER_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the environment
    _hv_rasterize = None
    DATASHADER_AVAILABLE = False


def _save_png(fig: Any, dpi: int = DPI, what: str = "plot") -> bytes:
    """Serialize ``fig`` to PNG bytes and close it."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    png = buf.getvalue()
    if not png:
        raise ValueError(f"Rendered {what} is empty: nothing plottable was found.")
    return png


def _figure_from_element(element: Any, width: int, height: int) -> Any:
    """Render a HoloViews element with the matplotlib backend at the given pixel size."""
    import holoviews as hv

    hv.extension("matplotlib")
    plot = hv.Store.renderers["matplotlib"].get_plot(element)
    fig = plot.state
    fig.set_size_inches(width / DPI, height / DPI)
    fig.set_dpi(DPI)
    return fig


def _wants_raster(n_face: int, force_raster: bool) -> bool:
    return force_raster or n_face > RASTERIZE_ABOVE_FACES


def _crop(grid: Any, lon_bounds: Any, lat_bounds: Any) -> Any:
    if lon_bounds is None or lat_bounds is None:
        return grid
    return grid.subset.bounding_box(
        lon_bounds=list(lon_bounds), lat_bounds=list(lat_bounds)
    )


def _render_centers(
    lon: Any,
    lat: Any,
    values: Any,
    width: int,
    height: int,
    cmap: str,
    title: str | None,
) -> Any:
    """Fallback when datashader is absent: face centres as 1-pixel points."""
    fig, ax = plt.subplots(figsize=(width / DPI, height / DPI), dpi=DPI)
    if values is None:
        ax.scatter(lon, lat, s=1, c="#333333", marker=".", linewidths=0)
    else:
        sc = ax.scatter(lon, lat, s=1, c=values, cmap=cmap, marker=".", linewidths=0)
        fig.colorbar(sc, ax=ax)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    if title:
        ax.set_title(title)
    return fig


def _render_rasterized(element: Any, width: int, height: int, title: str | None) -> Any:
    assert _hv_rasterize is not None
    raster = _hv_rasterize(element, width=width, height=height, dynamic=False)
    fig = _figure_from_element(raster, width, height)
    if title:
        fig.axes[0].set_title(title)
    return fig


def _info(
    mode: str, n_total: int, n_rendered: int, width: int, height: int
) -> dict[str, Any]:
    return {
        "render_mode": mode,
        "n_faces_total": int(n_total),
        "n_faces_rendered": int(n_rendered),
        "width": int(width),
        "height": int(height),
        "datashader_available": DATASHADER_AVAILABLE,
    }


def render_mesh(
    grid: Any,
    width: int = 800,
    height: int = 400,
    title: str | None = None,
    lon_bounds: tuple[float, float] | None = None,
    lat_bounds: tuple[float, float] | None = None,
    force_raster: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    """Render a mesh wireframe; returns ``(png_bytes, render_info)``."""
    n_total = int(grid.n_face)
    g = _crop(grid, lon_bounds, lat_bounds)
    n_rendered = int(g.n_face)

    if _wants_raster(n_rendered, force_raster):
        if DATASHADER_AVAILABLE:
            fig = _render_rasterized(
                g.plot.mesh(backend="matplotlib"), width, height, title
            )
            mode = "rasterized"
        else:
            fig = _render_centers(
                g.face_lon.values,
                g.face_lat.values,
                None,
                width,
                height,
                "viridis",
                title,
            )
            mode = "centers"
    else:
        fig = _figure_from_element(g.plot.mesh(backend="matplotlib"), width, height)
        if title:
            fig.axes[0].set_title(title)
        fig.tight_layout()
        mode = "polygons"

    info = _info(mode, n_total, n_rendered, width, height)
    info["region"] = (
        "regional" if lon_bounds is not None and lat_bounds is not None else "global"
    )
    return _save_png(fig, what="mesh plot"), info


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
) -> tuple[bytes, dict[str, Any]]:
    """Render a mesh over Cartopy land/ocean/coastlines; returns ``(png_bytes, render_info)``.

    Faces crossing the antimeridian are skipped and counted in ``seam_faces_skipped``.
    Boundary edges (opt-in) are traced from ``boundary_edge_indices``.
    """
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
    import numpy as np
    from matplotlib.collections import LineCollection, PolyCollection

    proj = ccrs.PlateCarree()
    dpi = 120
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor="white")
    ax: Any = fig.add_subplot(projection=proj)

    is_regional = lon_bounds is not None and lat_bounds is not None
    if is_regional and lon_bounds is not None and lat_bounds is not None:
        ax.set_extent(
            [lon_bounds[0], lon_bounds[1], lat_bounds[0], lat_bounds[1]], crs=proj
        )
    else:
        ax.set_global()
    g = _crop(grid, lon_bounds, lat_bounds)
    n_faces_total = int(grid.n_face)

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
        if lons.max() - lons.min() > ANTIMERIDIAN_SPAN_DEG:
            seam_skipped += 1
            continue
        polys.append(np.column_stack([lons, lats]))
    if polys:
        ax.add_collection(
            PolyCollection(
                polys,
                facecolors="white",
                edgecolors=mesh_edgecolor,
                linewidths=mesh_linewidth,
                alpha=mesh_alpha,
                transform=proj,
                zorder=2,
            )
        )

    boundary_drawn = False
    n_boundary_drawn = 0
    boundary_status = "disabled"
    if show_mesh_boundary:
        try:
            b_idx = g.boundary_edge_indices
            if len(b_idx) == 0:
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
                        continue
                    if dlon < 0.1 and abs(round(lon0) % 180) < 1:
                        continue
                    lines.append([[lon0, lat0], [lon1, lat1]])
                if lines:
                    ax.add_collection(
                        LineCollection(
                            lines,
                            colors="#cc2200",
                            linewidths=1.8,
                            transform=proj,
                            zorder=5,
                        )
                    )
                    boundary_drawn = True
                    n_boundary_drawn = len(lines)
                    boundary_status = "drawn"
                else:
                    boundary_status = "all_filtered"
        except Exception:  # noqa: BLE001
            boundary_status = "error"

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
    png_bytes = _save_png(fig, dpi=dpi, what="geographic mesh plot")

    info = _info("polygons", n_faces_total, len(polys), width, height)
    info.update(
        {
            "boundary_drawn": boundary_drawn,
            "n_boundary_edges": n_boundary_drawn,
            "boundary_status": boundary_status,
            "seam_faces_skipped": seam_skipped,
            "basemap_used": basemap_used,
            "features_drawn": features_drawn,
            "region": "regional" if is_regional else "global",
        }
    )
    return png_bytes, info


def describe_reduction(
    uxda: Any, time_index: int = 0, level_index: int = 0
) -> dict[str, dict[str, Any]]:
    """Report which time/level slice ``render_variable`` would take, without rendering."""
    _, reduced = face_slice_selection(
        uxda.sizes, time_index=time_index, level_index=level_index
    )
    return reduced


def render_variable(
    uxda: Any,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    title: str | None = None,
    time_index: int = 0,
    level_index: int = 0,
    force_raster: bool = False,
) -> tuple[bytes, dict[str, Any]]:
    """Render a face-centered variable as filled polygons; returns ``(png_bytes, render_info)``.

    The slice is taken first so a one-sided ``vmin``/``vmax`` is completed from
    the data actually drawn.
    """
    uxda, reduced = reduce_to_face(uxda, time_index=time_index, level_index=level_index)
    n_face = int(uxda.uxgrid.n_face)

    clim: tuple[float, float] | None = None
    if vmin is not None:
        clim = (vmin, vmax if vmax is not None else float(uxda.values.max()))
    elif vmax is not None:
        clim = (float(uxda.values.min()), vmax)

    if _wants_raster(n_face, force_raster):
        if DATASHADER_AVAILABLE:
            element = uxda.plot.polygons(backend="matplotlib", cmap=cmap)
            raster = _hv_rasterize(element, width=width, height=height, dynamic=False)
            opts: dict[str, Any] = {"cmap": cmap, "colorbar": True}
            if clim is not None:
                opts["clim"] = clim
            fig = _figure_from_element(raster.opts(**opts), width, height)
            mode = "rasterized"
        else:
            grid = uxda.uxgrid
            fig = _render_centers(
                grid.face_lon.values,
                grid.face_lat.values,
                uxda.values,
                width,
                height,
                cmap,
                title,
            )
            if clim is not None:
                fig.axes[0].collections[0].set_clim(*clim)
            mode = "centers"
    else:
        kwargs: dict[str, Any] = {"backend": "matplotlib", "cmap": cmap}
        if clim is not None:
            kwargs["clim"] = clim
        fig = _figure_from_element(uxda.plot.polygons(**kwargs), width, height)
        mode = "polygons"

    if title is not None and mode != "centers":
        fig.axes[0].set_title(title)
    if mode != "centers":
        _layout_with_colorbar(fig)

    info = _info(mode, n_face, n_face, width, height)
    info["reduced_dims"] = reduced
    info["cmap"] = cmap
    return _save_png(fig, what="variable plot"), info


def _layout_with_colorbar(fig: Any) -> None:
    """Place map and colorbar side by side; HoloViews' positions do not survive a resize."""
    axes = list(fig.axes)
    if len(axes) < 2:
        fig.tight_layout()
        return
    main, *colorbars = axes
    main.set_position([0.08, 0.12, 0.76, 0.80])
    for cax in colorbars:
        cax.set_position([0.87, 0.12, 0.025, 0.80])


def render_zonal_mean(
    latitudes: list[float],
    values: list[float],
    variable_name: str,
    width: int = 800,
    height: int = 400,
    line_color: str = "#1f77b4",
    title: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Render a latitude-vs-value profile; returns ``(png_bytes, render_info)``."""
    fig, ax = plt.subplots(figsize=(width / DPI, height / DPI), dpi=DPI)
    ax.plot(latitudes, values, linewidth=1.5, color=line_color)
    ax.set_xlabel("Latitude (deg)")
    ax.set_ylabel(variable_name)
    ax.set_title(title if title is not None else f"Zonal Mean: {variable_name}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    info = {
        "render_mode": "line",
        "n_points": len(values),
        "width": int(width),
        "height": int(height),
    }
    return _save_png(fig, what="zonal mean plot"), info
