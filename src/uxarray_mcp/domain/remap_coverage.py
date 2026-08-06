"""Source-coverage checks for remapping onto a target grid.

Remapping happily returns a value at every target point, including points
that lie nowhere near the source mesh.  Nothing about such a result looks
wrong: the statistics are plausible and the array is full.  These helpers
compute how much of the target actually falls inside the source mesh so a
caller can tell an interpolated number from an extrapolated one.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

#: Above this many target points the exact point-in-cell test is skipped and
#: only the bounding-box screen is reported, so coverage never dominates the
#: cost of the remap it is describing.
EXACT_TEST_POINT_LIMIT = 20000

#: Remap methods that conserve the integral of the field.  Nearest neighbour
#: and inverse-distance weighting do not, which makes them unsuitable for
#: fluxes even at full coverage.
_CONSERVATIVE_METHODS = {
    "conservative",
    "conservative_normed",
    "first_order_conservative",
}


def _wrap_lon(values: np.ndarray) -> np.ndarray:
    """Map longitudes onto [-180, 180) so source and target agree."""
    return (np.asarray(values, dtype=float) + 180.0) % 360.0 - 180.0


def method_is_conservative(method: str | None) -> bool:
    """Return whether a named remap method conserves the field integral."""
    if method is None:
        return False
    return method.strip().lower() in _CONSERVATIVE_METHODS


def source_bbox(grid: Any) -> dict[str, float]:
    """Return the source mesh node bounding box in degrees."""
    lon = _wrap_lon(np.asarray(grid.node_lon))
    lat = np.asarray(grid.node_lat, dtype=float)
    return {
        "lon_min": float(lon.min()),
        "lon_max": float(lon.max()),
        "lat_min": float(lat.min()),
        "lat_max": float(lat.max()),
    }


def compute_target_coverage(
    grid: Any,
    target_lon: Sequence[float],
    target_lat: Sequence[float],
    *,
    method: str | None = None,
) -> dict[str, Any]:
    """Report how many target points fall inside the source mesh.

    Parameters
    ----------
    grid : ux.Grid
        Source mesh the data lives on.
    target_lon, target_lat : sequence of float
        1-D target coordinate arrays in degrees; the target is their
        cartesian product, as for a rectilinear grid.
    method : str, optional
        Remap method name, used only to report its conservation property.

    Returns
    -------
    dict
        Keys: ``n_target_points``, ``points_in_source``, ``coverage_fraction``,
        ``source_bbox``, ``test`` (``"point_in_cell"`` or ``"bounding_box"``),
        ``method_is_conservative``, and ``warning_codes``.
    """
    lon = _wrap_lon(np.asarray(list(target_lon), dtype=float))
    lat = np.asarray(list(target_lat), dtype=float)
    mesh_lon, mesh_lat = np.meshgrid(lon, lat)
    points = np.column_stack([mesh_lon.ravel(), mesh_lat.ravel()])
    n_points = int(points.shape[0])

    bbox = source_bbox(grid)
    in_bbox = (
        (points[:, 0] >= bbox["lon_min"])
        & (points[:, 0] <= bbox["lon_max"])
        & (points[:, 1] >= bbox["lat_min"])
        & (points[:, 1] <= bbox["lat_max"])
    )
    n_in_bbox = int(in_bbox.sum())

    test = "bounding_box"
    n_inside = n_in_bbox
    if n_in_bbox and n_points <= EXACT_TEST_POINT_LIMIT:
        try:
            _faces, counts = grid.get_faces_containing_point(points[in_bbox])
            n_inside = int(np.count_nonzero(np.asarray(counts) > 0))
            test = "point_in_cell"
        except Exception:  # pragma: no cover - older//partial UXarray builds
            test = "bounding_box"

    fraction = float(n_inside) / n_points if n_points else 0.0
    conservative = method_is_conservative(method)

    warning_codes: list[str] = []
    if n_inside == 0:
        warning_codes.append("REMAP_COVERAGE_ZERO")
    elif n_inside < n_points:
        warning_codes.append("REMAP_COVERAGE_PARTIAL")
    if not conservative:
        warning_codes.append("REMAP_METHOD_NOT_CONSERVATIVE")

    return {
        "n_target_points": n_points,
        "points_in_source": n_inside,
        "coverage_fraction": fraction,
        "source_bbox": bbox,
        "test": test,
        "method_is_conservative": conservative,
        "warning_codes": warning_codes,
    }
