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
    lon_bounds: list[float] | None = None,
    lat_bounds: list[float] | None = None,
    force_raster: bool = False,
) -> dict[str, Any]:
    _, uxda, name = load_face_variable(grid_path, data_path, variable_name)
    n_total = int(uxda.uxgrid.n_face)
    if lon_bounds is not None and lat_bounds is not None:
        uxda = uxda.subset.bounding_box(
            (float(lon_bounds[0]), float(lon_bounds[1])),
            (float(lat_bounds[0]), float(lat_bounds[1])),
        )
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
    return {
        "png": png,
        "variable_name": name,
        **info,
        "n_faces_in_region": int(uxda.uxgrid.n_face),
        "n_faces_total": n_total,
    }


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


def _plot_temporal_mean(
    grid_path: str,
    data_paths: list[str],
    variable_name: str,
    lon_bounds: list[float] | None = None,
    lat_bounds: list[float] | None = None,
    level_index: int = 0,
    scale_factor: float = 1.0,
    units_label: str | None = None,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    title: str | None = None,
    force_raster: bool = False,
) -> dict[str, Any]:
    """Time-mean of ``variable_name`` over every step in ``data_paths``, drawn on the mesh."""
    import numpy as np
    import uxarray as ux
    import xarray as xr

    from uxarray_mcp.core.coverage import compute_temporal_coverage
    from uxarray_mcp.core.dims import face_slice_selection

    grid = load_grid(grid_path)
    with xr.open_mfdataset(
        data_paths,
        combine="by_coords",
        data_vars="minimal",
        coords="minimal",
        compat="override",
    ) as ds:
        var = ds[variable_name]
        n_steps = int(var.sizes.get("time", 1))
        time_min = (
            str(var["time"].values[0])[:19]
            if "time" in var.coords and n_steps
            else None
        )
        time_max = (
            str(var["time"].values[-1])[:19]
            if "time" in var.coords and n_steps
            else None
        )
        mean = var.mean(dim="time") if "time" in var.dims else var
        selection, reduced = face_slice_selection(mean.sizes, level_index=level_index)
        mean = mean.isel(**selection)
        values = np.asarray(mean.values, dtype=float) * float(scale_factor)
        coverage = compute_temporal_coverage(var, mean) if "time" in var.dims else None
    if values.ndim != 1 or values.size != grid.n_face:
        raise ValueError(
            f"{variable_name} is not face-centered on this grid after the time mean "
            f"(shape {values.shape}, n_face {grid.n_face})."
        )
    uxda = ux.UxDataArray(values, dims=["n_face"], uxgrid=grid, name=variable_name)
    uxda.attrs["units"] = units_label or var.attrs.get("units", "")
    n_total = int(grid.n_face)
    if lon_bounds is not None and lat_bounds is not None:
        uxda = uxda.subset.bounding_box(
            (float(lon_bounds[0]), float(lon_bounds[1])),
            (float(lat_bounds[0]), float(lat_bounds[1])),
        )
    label = title or f"{variable_name} time mean ({n_steps} steps)"
    png, info = render_variable(
        uxda,
        width=width,
        height=height,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        title=label,
        force_raster=force_raster,
    )
    finite = np.asarray(uxda.values, dtype=float)
    finite = finite[np.isfinite(finite)]
    stats = {
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "mean": float(finite.mean()) if finite.size else None,
    }
    return {
        "png": png,
        **info,
        "variable_name": variable_name,
        "n_files": len(data_paths),
        "n_time_steps": n_steps,
        "time_min": time_min,
        "time_max": time_max,
        "n_faces_in_region": int(uxda.uxgrid.n_face),
        "n_faces_total": n_total,
        "scale_factor": scale_factor,
        "units": uxda.attrs["units"],
        "value_stats": stats,
        "reduced_dims": reduced,
        "temporal_coverage": coverage,
    }


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
    "yac_smoke": remap.yac_smoke,
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
    "plot_temporal_mean": _plot_temporal_mean,
}


def call(name: str, **kwargs: Any) -> dict[str, Any]:
    """Run operation ``name`` with ``kwargs``; unknown names list the table."""
    try:
        fn = OPS[name]
    except KeyError:
        raise ValueError(f"Unknown operation {name!r}. Known: {', '.join(sorted(OPS))}")
    return fn(**kwargs)
