"""Named operations: the one table both the local server and the worker call.

``call(name, **kwargs)`` is what :mod:`uxarray_mcp.remote.shim` runs on a
Globus Compute worker, so every operation here must take plain JSON kwargs
and return a dict (plot ops include ``png: bytes``; ops that build a data
object include ``_payload``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from uxarray_mcp.core import catalog, compare, facts, inspect, remap, subset, temporal
from uxarray_mcp.core import vector_calc as vc
from uxarray_mcp.core.fields import load_face_variable
from uxarray_mcp.core.mesh import load_dataset, load_grid
from uxarray_mcp.core.plotting import (
    render_mesh,
    render_mesh_geo,
    render_variable,
    render_zonal_mean,
)


def _plot_mesh(
    grid_path: str,
    width: int = 800,
    height: int = 400,
    title: str | None = None,
    lon_bounds: list[float] | None = None,
    lat_bounds: list[float] | None = None,
    coastlines: bool = False,
    force_raster: bool = False,
) -> dict[str, Any]:
    grid = load_grid(grid_path)
    lon = (float(lon_bounds[0]), float(lon_bounds[1])) if lon_bounds else None
    lat = (float(lat_bounds[0]), float(lat_bounds[1])) if lat_bounds else None
    if coastlines:
        png, info = render_mesh_geo(
            grid,
            width=width,
            height=height,
            lon_bounds=lon,
            lat_bounds=lat,
        )
    else:
        png, info = render_mesh(
            grid,
            width=width,
            height=height,
            title=title,
            lon_bounds=lon,
            lat_bounds=lat,
            force_raster=force_raster,
        )
    return {"png": png, **info}


def _plot_field(
    grid_path: str,
    data_path: str,
    variable_name: str,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    title: str | None = None,
    time_index: int = 0,
    level_index: int = 0,
    force_raster: bool = False,
) -> dict[str, Any]:
    _, uxda, name = load_face_variable(grid_path, data_path, variable_name)
    png, info = render_variable(
        uxda,
        width=width,
        height=height,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        title=title or name,
        time_index=time_index,
        level_index=level_index,
        force_raster=force_raster,
    )
    return {"png": png, "variable_name": name, **info}


def _plot_profile(
    grid_path: str,
    data_path: str,
    variable_name: str,
    width: int = 800,
    height: int = 400,
    lat_spec: Any = None,
    conservative: bool = False,
    time_index: int = 0,
    level_index: int = 0,
    title: str | None = None,
    line_color: str = "#1f77b4",
) -> dict[str, Any]:
    stats = inspect.calculate_zonal_mean(
        grid_path,
        data_path,
        variable_name,
        lat_spec=lat_spec,
        conservative=conservative,
        time_index=time_index,
        level_index=level_index,
    )
    png, info = render_zonal_mean(
        stats["latitudes"],
        stats["zonal_mean_values"],
        variable_name,
        width=width,
        height=height,
        line_color=line_color,
        title=title,
    )
    return {"png": png, **info, "zonal_mean": stats}


def _with_dataset(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Adapt a core function taking a loaded ``uxds`` to take file paths."""

    def wrapped(grid_path: str, data_path: str, **kwargs: Any) -> dict[str, Any]:
        return fn(load_dataset(grid_path, data_path), **kwargs)

    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


OPS: dict[str, Callable[..., dict[str, Any]]] = {
    # discovery / inspection
    "scan_directory": catalog.scan,
    "header_facts": facts.header_facts,
    "inspect_mesh": inspect.inspect_mesh,
    "grid_facts": inspect.grid_facts,
    "inspect_variable": inspect.inspect_variable,
    "validate_dataset": inspect.validate_dataset,
    # statistics
    "area": inspect.calculate_area,
    "zonal_mean": inspect.calculate_zonal_mean,
    "zonal_anomaly": inspect.zonal_anomaly,
    "azimuthal_mean": _with_dataset(vc.compute_azimuthal_mean),
    "temporal_mean": temporal.temporal_mean,
    "anomaly": temporal.anomaly,
    "ensemble_mean": temporal.ensemble_mean,
    "ensemble_spread": temporal.ensemble_spread,
    # vector calculus
    "gradient": _with_dataset(vc.compute_gradient),
    "curl": _with_dataset(vc.compute_curl),
    "divergence": _with_dataset(vc.compute_divergence),
    # comparison
    "compare_fields": compare.compare_fields,
    # remap
    "remap_variable": remap.remap_variable,
    "regrid_dataset": remap.regrid_dataset,
    "remap_to_rectilinear": remap.remap_to_rectilinear,
    # subset
    "subset_bbox": subset.subset_bbox,
    "subset_polygon": subset.subset_polygon,
    "cross_section": subset.cross_section,
    "subset_near_point": subset.subset_near_point,
    "regrid_elements": subset.regrid_elements,
    # plots
    "plot_mesh": _plot_mesh,
    "plot_field": _plot_field,
    "plot_profile": _plot_profile,
}


def call(name: str, **kwargs: Any) -> dict[str, Any]:
    """Run operation ``name`` with ``kwargs``; unknown names list the table."""
    try:
        fn = OPS[name]
    except KeyError:
        raise ValueError(f"Unknown operation {name!r}. Known: {', '.join(sorted(OPS))}")
    return fn(**kwargs)
