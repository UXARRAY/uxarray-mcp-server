"""Spatial selection: bounding box, polygon, cross-section, near-point, and
moving a field between mesh elements.

Each op returns ``subset_coverage`` with the rule it selected by, because the
rules differ: a bbox keeps a face only when its whole footprint fits, a polygon
tests face centres, a cross-section tests edge intersection.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from matplotlib.path import Path as MplPath

from uxarray_mcp.core.coverage import (
    compute_subset_coverage,
    count_face_centers_in_bounds,
    mesh_extent,
    subset_coverage_warning_codes,
)
from uxarray_mcp.core.fields import load_face_variable, summarize_array, summarize_grid
from uxarray_mcp.core.mesh import load_grid

TOPOLOGICAL_STATISTICS: tuple[str, ...] = (
    "mean",
    "min",
    "max",
    "sum",
    "std",
    "var",
    "median",
)
ELEMENTS: tuple[str, ...] = ("node", "edge", "face")


def _finish(result: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    result["coverage"] = coverage
    result["subset_coverage"] = coverage
    result["n_face_source"] = coverage["n_face_source"]
    result["n_face_retained"] = coverage["n_face_retained"]
    result["warning_codes"] = subset_coverage_warning_codes(coverage)
    return result


def _apply_to_field(
    grid_path: str,
    data_path: str | None,
    variable_name: str | None,
    apply: Callable[[Any], Any],
) -> tuple[Any | None, dict[str, Any] | None, str | None]:
    """Run ``apply`` on the chosen variable, if a data file was given."""
    if data_path is None:
        return None, None, None
    _, uxda, selected = load_face_variable(grid_path, data_path, variable_name)
    subset_data = apply(uxda)
    return subset_data, summarize_array(subset_data.to_xarray()), selected


def subset_bbox(
    grid_path: str,
    lon_bounds: list[float],
    lat_bounds: list[float],
    data_path: str | None = None,
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Keep faces whose whole spherical footprint lies inside a lon/lat box."""
    grid = load_grid(grid_path)
    bounds = (tuple(lon_bounds), tuple(lat_bounds))
    subset_grid = grid.subset.bounding_box(*bounds)
    subset_data, variable_summary, selected = _apply_to_field(
        grid_path,
        data_path,
        variable_name,
        lambda uxda: uxda.subset.bounding_box(*bounds),
    )
    coverage = compute_subset_coverage(
        grid.n_face,
        subset_grid.n_face,
        extent=mesh_extent(grid),
        selection_rule="face_bounds_within",
        n_face_centers_in_bounds=count_face_centers_in_bounds(
            grid, lon_bounds, lat_bounds
        ),
    )
    result: dict[str, Any] = {
        "selection_type": "bbox",
        "lon_bounds": [float(v) for v in lon_bounds],
        "lat_bounds": [float(v) for v in lat_bounds],
        "original_grid": summarize_grid(grid),
        "subset_grid": summarize_grid(subset_grid),
        "variable_name": selected,
        "variable_summary": variable_summary,
        "_payload": subset_data if subset_data is not None else subset_grid,
    }
    return _finish(result, coverage)


def subset_polygon(
    grid_path: str,
    polygon_lon_lat: list[list[float]],
    data_path: str | None = None,
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Keep faces whose centres fall inside a lon/lat polygon."""
    if len(polygon_lon_lat) < 3:
        raise ValueError("polygon_lon_lat must contain at least three points.")
    grid = load_grid(grid_path)
    face_points = np.column_stack(
        (np.asarray(grid.face_lon), np.asarray(grid.face_lat))
    )
    polygon = MplPath(np.asarray(polygon_lon_lat, dtype=float))
    indices = np.flatnonzero(polygon.contains_points(face_points))

    def _select(uxda: Any) -> Any:
        face_dim = "n_face" if "n_face" in uxda.dims else "nCells"
        return uxda.isel({face_dim: indices})

    subset_data, variable_summary, selected = _apply_to_field(
        grid_path, data_path, variable_name, _select
    )
    coverage = compute_subset_coverage(
        grid.n_face,
        int(indices.size),
        extent=mesh_extent(grid),
        selection_rule="face_center_inside",
    )
    result: dict[str, Any] = {
        "selection_type": "polygon",
        "selected_face_count": int(indices.size),
        "selected_face_indices_preview": indices[:25].tolist(),
        "variable_name": selected,
        "variable_summary": variable_summary,
        "_payload": (
            subset_data
            if subset_data is not None
            else {
                "selection_type": "polygon",
                "polygon_lon_lat": polygon_lon_lat,
                "selected_face_indices": indices.tolist(),
            }
        ),
    }
    return _finish(result, coverage)


def cross_section(
    grid_path: str,
    latitude: float | None = None,
    longitude: float | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Faces crossed by a constant-latitude or constant-longitude line.

    UXarray raises when the line misses the mesh; that is returned as an empty
    selection so the caller gets the mesh extent instead of a bare error.
    """
    if (latitude is None) == (longitude is None):
        raise ValueError("Provide exactly one of latitude or longitude.")
    grid = load_grid(grid_path)
    selection_type = (
        "constant_latitude" if latitude is not None else "constant_longitude"
    )

    def _select(obj: Any) -> Any:
        if latitude is not None:
            return obj.subset.constant_latitude(latitude)
        return obj.subset.constant_longitude(longitude)

    result: dict[str, Any] = {
        "selection_type": selection_type,
        "latitude": latitude,
        "longitude": longitude,
    }
    try:
        subset_grid = _select(grid)
    except ValueError as exc:
        if "No intersections found" not in str(exc):
            raise
        result.update(
            {
                "subset_grid": None,
                "variable_name": None,
                "variable_summary": None,
                "_payload": None,
            }
        )
        coverage = compute_subset_coverage(
            grid.n_face,
            0,
            extent=mesh_extent(grid),
            selection_rule="face_intersects_line",
        )
        return _finish(result, coverage)

    subset_data, variable_summary, selected = _apply_to_field(
        grid_path, data_path, variable_name, _select
    )
    coverage = compute_subset_coverage(
        grid.n_face,
        subset_grid.n_face,
        extent=mesh_extent(grid),
        selection_rule="face_intersects_line",
    )
    result.update(
        {
            "subset_grid": summarize_grid(subset_grid),
            "variable_name": selected,
            "variable_summary": variable_summary,
            "_payload": subset_data if subset_data is not None else subset_grid,
        }
    )
    return _finish(result, coverage)


def subset_near_point(
    grid_path: str,
    selection: str,
    center_lon: float,
    center_lat: float,
    radius: float | None = None,
    k: int | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Faces within ``radius`` degrees of a point (``"circle"``) or the ``k``
    nearest faces (``"nearest"``)."""
    if selection not in ("circle", "nearest"):
        raise ValueError(
            f"Unknown selection {selection!r}; expected 'circle' or 'nearest'."
        )
    if selection == "circle":
        if radius is None:
            raise ValueError("selection='circle' requires radius (in degrees).")
        if radius <= 0:
            raise ValueError(f"radius must be positive, got {radius}.")
    else:
        if k is None:
            raise ValueError("selection='nearest' requires k (number of faces).")
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}.")

    grid = load_grid(grid_path)
    center = (center_lon, center_lat)
    rule = "face_center_within_radius" if selection == "circle" else "k_nearest_faces"

    def _select(obj: Any) -> Any:
        if selection == "circle":
            return obj.subset.bounding_circle(center_coord=center, r=radius)
        return obj.subset.nearest_neighbor(center_coord=center, k=k)

    try:
        subset_grid = _select(grid)
    except ValueError as exc:
        if "No elements found" not in str(exc) and "not enough" not in str(exc).lower():
            raise
        raise ValueError(
            f"Selection kept no faces: {selection} centred at "
            f"({center_lon}, {center_lat})"
            + (f" with radius {radius} degrees" if radius is not None else "")
            + f". The mesh covers {mesh_extent(grid)}. Move the centre inside "
            "that extent, or widen the radius."
        ) from exc

    subset_data, variable_summary, selected = _apply_to_field(
        grid_path, data_path, variable_name, _select
    )
    coverage = compute_subset_coverage(
        grid.n_face,
        subset_grid.n_face,
        extent=mesh_extent(grid),
        selection_rule=rule,
    )
    result: dict[str, Any] = {
        "selection": selection,
        "center": {"lon": float(center_lon), "lat": float(center_lat)},
        "radius_deg": radius,
        "k": k,
        "subset_grid": summarize_grid(subset_grid),
        "variable_name": selected,
        "variable_summary": variable_summary,
        "_payload": subset_data if subset_data is not None else subset_grid,
    }
    return _finish(result, coverage)


def regrid_elements(
    grid_path: str,
    data_path: str,
    destination: str,
    variable_name: str | None = None,
    statistic: str = "mean",
) -> dict[str, Any]:
    """Carry a field between nodes, edges and faces with a topological statistic.

    This moves where the values live, not what they mean; it is the step that
    makes node-centred output usable by the face-centred operations.
    """
    if destination not in ELEMENTS:
        raise ValueError(
            f"Unknown destination {destination!r}; expected one of "
            f"{', '.join(ELEMENTS)}."
        )
    if statistic not in TOPOLOGICAL_STATISTICS:
        raise ValueError(
            f"Unknown statistic {statistic!r}; expected one of "
            f"{', '.join(TOPOLOGICAL_STATISTICS)}."
        )
    uxds, uxda, selected = load_face_variable(grid_path, data_path, variable_name)
    source_dims = [str(d) for d in uxda.dims]
    if f"n_{destination}" in source_dims:
        raise ValueError(
            f"Variable {selected!r} is already on {destination} elements "
            f"(dims {source_dims}); nothing to move."
        )
    moved = getattr(uxda, f"topological_{statistic}")(destination)
    return {
        "variable_name": selected,
        "destination": destination,
        "statistic": statistic,
        "source_dims": source_dims,
        "result_dims": [str(d) for d in moved.dims],
        "variable_summary": summarize_array(moved.to_xarray()),
        "n_face": int(uxds.uxgrid.n_face),
        "_payload": moved,
    }
