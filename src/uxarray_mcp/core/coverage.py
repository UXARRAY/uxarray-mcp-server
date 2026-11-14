"""Coverage measurements and their stable warning codes.

Every operation that returns an array shaped like an answer gets a block here
saying how much of that array is backed by data, so an extrapolated remap, an
empty subset or a mean over NaN is never indistinguishable from a real result.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

# --- mesh --------------------------------------------------------------------

#: Slack on ``sphere_fraction`` for a mesh that is global but has polar pinholes.
GLOBAL_COVERAGE_TOLERANCE = 1e-3

#: Above this face count the edge-incidence loop (seconds on HEALPix zoom 8)
#: is skipped and ``closed`` is reported as unknown.
TOPOLOGY_MAX_FACES = 250_000

#: Above this even ``face_areas`` is skipped; on a 300M-face grid it kills the
#: process.
AREA_MAX_FACES = 50_000_000

_COORD_DECIMALS = 6
_REPORT_DECIMALS = 6


def _canonical_node_ids(grid: Any) -> list[int]:
    """Merge nodes at the same position (all pole nodes collapse to one) so the
    0/360 seam of a structured grid does not count as a boundary."""
    lon = np.asarray(grid.node_lon, dtype=float) % 360.0
    lat = np.asarray(grid.node_lat, dtype=float)
    seen: dict[str, int] = {}
    ids: list[int] = []
    for x, y in zip(lon, lat):
        if abs(abs(y) - 90.0) < 1e-9:
            key = f"pole{y:+.1f}"
        else:
            key = (
                f"{round(x, _COORD_DECIMALS) % 360:.6f}_{round(y, _COORD_DECIMALS):.6f}"
            )
        ids.append(seen.setdefault(key, len(seen)))
    return ids


def mesh_is_closed(grid: Any) -> bool:
    """True when every edge is shared by exactly two faces.

    Counts edge incidences directly; the Euler-formula shortcut is wrong on
    meshes with holes.
    """
    try:
        connectivity = np.asarray(grid.face_node_connectivity)
        node_ids = _canonical_node_ids(grid)
    except Exception:  # pragma: no cover - mocked grids in unit tests
        return False

    n_node = len(node_ids)
    incidence: dict[tuple[int, int], int] = {}
    for face in connectivity:
        nodes: list[int] = []
        for raw in face:
            index = int(raw)
            if not 0 <= index < n_node:
                continue
            node = node_ids[index]
            if not nodes or nodes[-1] != node:
                nodes.append(node)
        if len(nodes) > 1 and nodes[0] == nodes[-1]:
            nodes.pop()
        if len(nodes) < 3:
            continue
        for index, node in enumerate(nodes):
            other = nodes[(index + 1) % len(nodes)]
            key = (min(node, other), max(node, other))
            incidence[key] = incidence.get(key, 0) + 1
    if not incidence:
        return False
    return all(count == 2 for count in incidence.values())


def compute_mesh_coverage(
    grid: Any,
    *,
    steradians: float | None = None,
) -> dict[str, Any]:
    """How much of the sphere ``grid`` covers and whether it is closed.

    ``sphere_fraction`` is geometric and ``closed``/``euler_characteristic``
    topological; a 1-degree structured grid is 0.99996 of the sphere and open,
    so both are reported. ``steradians`` may be passed to avoid a second sum.
    """
    coverage: dict[str, Any] = {
        "sphere_fraction": None,
        "closed": None,
        "euler_characteristic": None,
        "lon_extent": None,
        "lat_extent": None,
    }

    try:
        face_count = int(getattr(grid, "n_face", 0))
    except Exception:
        face_count = 0
    if steradians is None and face_count > AREA_MAX_FACES:
        coverage["sphere_fraction_skipped"] = (
            f"{face_count} faces exceeds the {AREA_MAX_FACES}-face "
            "limit for summing face areas; sphere_fraction not computed. "
            "Subset the mesh first if you need it."
        )
    elif steradians is None:
        try:
            steradians = float(np.asarray(grid.face_areas).sum())
        except Exception:  # pragma: no cover - mocked grids in unit tests
            steradians = None
    if steradians is not None and math.isfinite(steradians):
        coverage["sphere_fraction"] = round(
            float(steradians) / (4.0 * math.pi), _REPORT_DECIMALS
        )

    try:
        lon = np.asarray(grid.node_lon, dtype=float)
        lat = np.asarray(grid.node_lat, dtype=float)
        if lon.size and lat.size:
            coverage["lon_extent"] = [
                round(float(lon.min()), _REPORT_DECIMALS),
                round(float(lon.max()), _REPORT_DECIMALS),
            ]
            coverage["lat_extent"] = [
                round(float(lat.min()), _REPORT_DECIMALS),
                round(float(lat.max()), _REPORT_DECIMALS),
            ]
    except Exception:  # pragma: no cover - mocked grids in unit tests
        pass

    try:
        n_face = int(grid.n_face)
    except Exception:  # pragma: no cover - mocked grids in unit tests
        return coverage

    if n_face > TOPOLOGY_MAX_FACES:
        coverage["topology_skipped"] = (
            f"{n_face} faces exceeds the {TOPOLOGY_MAX_FACES}-face limit for "
            "counting edge incidences; closure was not checked."
        )
        return coverage

    try:
        coverage["euler_characteristic"] = int(grid.n_node) - int(grid.n_edge) + n_face
    except Exception:  # pragma: no cover - mocked grids in unit tests
        pass
    coverage["closed"] = mesh_is_closed(grid)
    return coverage


def mesh_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """Codes for a mesh that is not the whole sphere; silent when unknown."""
    fraction = coverage.get("sphere_fraction")
    if fraction is None:
        return []
    if fraction < 1.0 - GLOBAL_COVERAGE_TOLERANCE:
        return ["MESH_NOT_GLOBAL"]
    if fraction > 1.0 + GLOBAL_COVERAGE_TOLERANCE:
        return ["MESH_COVERAGE_EXCEEDS_SPHERE"]
    return []


# --- profile -----------------------------------------------------------------


def compute_profile_coverage(
    values: Sequence[float],
    *,
    source: Any = None,
) -> dict[str, Any]:
    """How many bins of a binned profile carry a value.

    A NaN bin is an empty bin only when the source field is wholly finite;
    otherwise the cause is reported as ambiguous rather than guessed.
    """
    profile = np.asarray(values, dtype=float)
    n_bins = int(profile.size)
    n_filled = int(np.isfinite(profile).sum())

    source_has_missing: bool | None = None
    if source is not None:
        source_values = np.asarray(getattr(source, "values", source), dtype=float)
        source_has_missing = bool(source_values.size) and bool(
            (~np.isfinite(source_values)).any()
        )

    if n_filled == n_bins:
        cause = "none"
    elif source_has_missing is False:
        cause = "bins_miss_mesh"
    else:
        cause = "ambiguous"

    return {
        "n_bins": n_bins,
        "n_bins_filled": n_filled,
        "source_has_missing": source_has_missing,
        "cause": cause,
    }


def profile_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """Codes for a partly or wholly unfilled profile."""
    n_bins = coverage.get("n_bins", 0)
    if not n_bins:
        return []
    filled = coverage.get("n_bins_filled", 0)
    if filled == 0:
        return ["PROFILE_COVERAGE_ZERO"]
    if filled < n_bins:
        return ["PROFILE_COVERAGE_PARTIAL"]
    return []


# --- anomaly -----------------------------------------------------------------


def compute_anomaly_coverage(
    values: Sequence[float],
    *,
    source: Any = None,
) -> dict[str, Any]:
    """How many faces received a zonal anomaly, and how many lost one.

    A finite source value with a non-finite anomaly means the band mean was
    undefined; faces that never had data are counted but not treated as loss.
    """
    anomaly = np.asarray(values, dtype=float)
    anomaly_finite = np.isfinite(anomaly)
    n_face = int(anomaly.size)
    n_with_anomaly = int(anomaly_finite.sum())

    n_with_data: int | None = None
    n_lost: int | None = None
    comparable = False
    if source is not None:
        source_values = np.asarray(getattr(source, "values", source), dtype=float)
        if source_values.shape == anomaly.shape:
            source_finite = np.isfinite(source_values)
            n_with_data = int(source_finite.sum())
            n_lost = int((source_finite & ~anomaly_finite).sum())
            comparable = not bool((~source_finite & anomaly_finite).any())

    if n_with_data is None:
        cause = "none" if n_with_anomaly == n_face else "ambiguous"
    elif not comparable:
        cause = "ambiguous"
    elif n_lost:
        cause = "band_mean_undefined"
    elif n_with_anomaly == n_face:
        cause = "none"
    else:
        cause = "missing_input"

    return {
        "n_face": n_face,
        "n_face_with_data": n_with_data,
        "n_face_with_anomaly": n_with_anomaly,
        "n_face_data_lost": n_lost,
        "cause": cause,
    }


def anomaly_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """Codes for an anomaly field that is empty or lost measured data.

    Partial fires only on lost data, not on masked faces, or every ocean field
    would warn.
    """
    if not coverage.get("n_face", 0):
        return []
    if not coverage.get("n_face_with_anomaly", 0):
        return ["ANOMALY_COVERAGE_ZERO"]
    if coverage.get("n_face_data_lost"):
        return ["ANOMALY_COVERAGE_PARTIAL"]
    return []


# --- subset ------------------------------------------------------------------


def mesh_extent(grid: Any) -> dict[str, float] | None:
    """Lon/lat box of the face centres, or None when it cannot be measured."""
    try:
        lon = np.asarray(grid.face_lon, dtype=float)
        lat = np.asarray(grid.face_lat, dtype=float)
    except (AttributeError, TypeError, ValueError):
        return None
    if lon.size == 0 or lat.size == 0:
        return None
    finite_lon = lon[np.isfinite(lon)]
    finite_lat = lat[np.isfinite(lat)]
    if finite_lon.size == 0 or finite_lat.size == 0:
        return None
    return {
        "lon_min": float(finite_lon.min()),
        "lon_max": float(finite_lon.max()),
        "lat_min": float(finite_lat.min()),
        "lat_max": float(finite_lat.max()),
    }


def count_face_centers_in_bounds(
    grid: Any,
    lon_bounds: Sequence[float],
    lat_bounds: Sequence[float],
) -> int | None:
    """Face centres inside a lon/lat box (inclusive), or None if unmeasurable.

    ``subset_bbox`` keeps only faces whose whole footprint fits, so this is
    the number a caller expects next to the number they get.
    """
    try:
        lon = np.asarray(grid.face_lon, dtype=float)
        lat = np.asarray(grid.face_lat, dtype=float)
        lon_lo, lon_hi = float(lon_bounds[0]), float(lon_bounds[1])
        lat_lo, lat_hi = float(lat_bounds[0]), float(lat_bounds[1])
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    if lon.size == 0 or lat.size == 0 or lon.shape != lat.shape:
        return None
    inside = (lon >= lon_lo) & (lon <= lon_hi) & (lat >= lat_lo) & (lat <= lat_hi)
    return int(inside.sum())


def compute_subset_coverage(
    n_face_source: int,
    n_face_retained: int,
    *,
    extent: dict[str, float] | None = None,
    selection_rule: str | None = None,
    n_face_centers_in_bounds: int | None = None,
) -> dict[str, Any]:
    """How much of the source mesh a selection kept, and by which rule."""
    coverage: dict[str, Any] = {
        "n_face_source": int(n_face_source),
        "n_face_retained": int(n_face_retained),
    }
    if selection_rule is not None:
        coverage["selection_rule"] = selection_rule
    if n_face_centers_in_bounds is not None:
        coverage["n_face_centers_in_bounds"] = int(n_face_centers_in_bounds)
    if extent is not None:
        coverage["source_extent"] = extent
    return coverage


def subset_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """A code for a selection that kept nothing; no partial code by design."""
    if not coverage.get("n_face_source", 0):
        return []
    if not coverage.get("n_face_retained", 0):
        return ["SUBSET_COVERAGE_ZERO"]
    return []


# --- remap -------------------------------------------------------------------

#: Above this many target points only the bounding-box screen runs.
EXACT_TEST_POINT_LIMIT = 20000

_CONSERVATIVE_METHODS = {
    "conservative",
    "conservative_normed",
    "first_order_conservative",
}


def _wrap_lon(values: Any) -> np.ndarray:
    """Map longitudes onto [-180, 180)."""
    return (np.asarray(values, dtype=float) + 180.0) % 360.0 - 180.0


def method_is_conservative(method: str | None) -> bool:
    """Whether a named remap method conserves the field integral."""
    if method is None:
        return False
    return method.strip().lower() in _CONSERVATIVE_METHODS


def source_bbox(grid: Any) -> dict[str, float]:
    """Node bounding box of the source mesh, longitudes wrapped to [-180, 180)."""
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
    target_lon: Sequence[float] | np.ndarray,
    target_lat: Sequence[float] | np.ndarray,
    *,
    method: str | None = None,
) -> dict[str, Any]:
    """Coverage of a rectilinear target: the cartesian product of 1-D axes."""
    lon = _wrap_lon(np.asarray(list(target_lon), dtype=float))
    lat = np.asarray(list(target_lat), dtype=float)
    mesh_lon, mesh_lat = np.meshgrid(lon, lat)
    return _coverage_of_points(
        grid, mesh_lon.ravel(), mesh_lat.ravel(), method=method, wrap=False
    )


def compute_scattered_coverage(
    grid: Any,
    target_lon: Sequence[float] | np.ndarray,
    target_lat: Sequence[float] | np.ndarray,
    *,
    method: str | None = None,
) -> dict[str, Any]:
    """Coverage of an unstructured target whose lon/lat pair off point by point."""
    return _coverage_of_points(grid, target_lon, target_lat, method=method)


def grid_target_coverage(
    source_grid: Any,
    target_grid: Any,
    *,
    remap_to: str,
    method: str,
) -> dict[str, Any] | None:
    """Coverage of a target mesh's faces or nodes, or None if it has no coordinates."""
    lon_attr, lat_attr = (
        ("node_lon", "node_lat") if remap_to == "nodes" else ("face_lon", "face_lat")
    )
    try:
        lon = np.asarray(getattr(target_grid, lon_attr), dtype=float)
        lat = np.asarray(getattr(target_grid, lat_attr), dtype=float)
    except (AttributeError, ValueError, TypeError):
        return None
    if lon.size == 0 or lon.shape != lat.shape:
        return None
    return compute_scattered_coverage(source_grid, lon, lat, method=method)


def _coverage_of_points(
    grid: Any,
    target_lon: Sequence[float] | np.ndarray,
    target_lat: Sequence[float] | np.ndarray,
    *,
    method: str | None = None,
    wrap: bool = True,
) -> dict[str, Any]:
    lon = np.asarray(list(target_lon), dtype=float)
    if wrap:
        lon = _wrap_lon(lon)
    lat = np.asarray(list(target_lat), dtype=float)
    if lon.shape != lat.shape:
        raise ValueError(
            "target_lon and target_lat must have the same shape when the "
            f"points are paired; got {lon.shape} and {lat.shape}."
        )
    points = np.column_stack([lon, lat])
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
        except Exception:  # pragma: no cover - older/partial UXarray builds
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
        "method": method,
        "method_is_conservative": conservative,
        "warning_codes": warning_codes,
    }


def remap_coverage_warnings(coverage: dict[str, Any] | None) -> list[str]:
    """Turn remap coverage codes into caller-readable sentences."""
    if not coverage:
        return []
    codes = coverage.get("warning_codes", [])
    n_in = coverage.get("points_in_source")
    n_total = coverage.get("n_target_points")
    messages: list[str] = []
    if "REMAP_COVERAGE_ZERO" in codes:
        messages.append(
            f"REMAP_COVERAGE_ZERO: none of the {n_total} target points fall "
            "inside the source mesh; every returned value is extrapolated and "
            "should not be interpreted physically."
        )
    elif "REMAP_COVERAGE_PARTIAL" in codes:
        messages.append(
            f"REMAP_COVERAGE_PARTIAL: only {n_in} of {n_total} target points "
            "fall inside the source mesh; values outside are extrapolated."
        )
    if "REMAP_METHOD_NOT_CONSERVATIVE" in codes:
        method = coverage.get("method") or "this"
        messages.append(
            f"REMAP_METHOD_NOT_CONSERVATIVE: {method} remapping does not "
            "conserve the field integral and is unsuitable for fluxes. "
            "Use method='conservative' (YAC backend) when the integral matters."
        )
    return messages


# --- temporal ----------------------------------------------------------------


def compute_temporal_coverage(
    source: Any,
    result: Any,
    *,
    groupby: str | None = None,
) -> dict[str, Any]:
    """What a reduction along ``time`` had to work with.

    Reports the source step count, the per-series usable-sample range (masked
    series excluded) and, when grouped, the bin occupancy. Unknown is None,
    never a full count.
    """
    coverage: dict[str, Any] = {
        "n_time": None,
        "samples_min": None,
        "samples_max": None,
        "n_elements": 0,
        "n_elements_with_value": 0,
        "n_series": None,
        "n_series_with_data": None,
        "groupby": groupby,
    }

    result_values = _as_float(result)
    if result_values is not None:
        coverage["n_elements"] = int(result_values.size)
        coverage["n_elements_with_value"] = int(np.isfinite(result_values).sum())

    source_values = _as_float(source)
    axis = _time_axis(source)
    if source_values is not None and axis is not None:
        coverage["n_time"] = int(source_values.shape[axis])
        per_series = np.isfinite(source_values).sum(axis=axis)
        with_data = per_series > 0
        coverage["n_series"] = int(per_series.size)
        coverage["n_series_with_data"] = int(with_data.sum())
        coverage["samples_max"] = int(per_series.max()) if per_series.size else None
        coverage["samples_min"] = (
            int(per_series[with_data].min()) if bool(with_data.any()) else None
        )

    if groupby is not None:
        occupancy = _bin_occupancy(source, groupby)
        if occupancy is not None:
            coverage["n_bins"] = len(occupancy)
            coverage["bin_occupancy_min"] = min(occupancy) if occupancy else None
            coverage["bin_occupancy_max"] = max(occupancy) if occupancy else None

    return coverage


def temporal_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """Codes for a temporal reduction, worst first."""
    if not coverage.get("n_elements", 0):
        return []
    if not coverage.get("n_elements_with_value", 0):
        return ["TEMPORAL_COVERAGE_ZERO"]

    codes: list[str] = []
    n_time = coverage.get("n_time")
    if n_time == 1:
        codes.append("TEMPORAL_SINGLE_SAMPLE")

    samples_min = coverage.get("samples_min")
    samples_max = coverage.get("samples_max")
    if (
        samples_min is not None
        and samples_max is not None
        and samples_min != samples_max
    ):
        codes.append("TEMPORAL_SAMPLES_RAGGED")

    if coverage.get("bin_occupancy_min") == 1 and n_time != 1:
        codes.append("TEMPORAL_BINS_SINGLE_SAMPLE")
    return codes


def _as_float(data: Any) -> np.ndarray | None:
    if data is None:
        return None
    try:
        return np.asarray(getattr(data, "values", data), dtype=float)
    except (AttributeError, TypeError, ValueError):
        return None


def _time_axis(data: Any) -> int | None:
    dims = getattr(data, "dims", None)
    if dims is None:
        return None
    try:
        return list(dims).index("time")
    except ValueError:
        return None


def _bin_occupancy(source: Any, groupby: str) -> list[int] | None:
    """Time steps per group, counted from the time coordinate, not the result."""
    try:
        counts = source["time"].groupby(f"time.{groupby}").count()
        return [int(value) for value in np.asarray(counts.values).ravel()]
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


# --- export fidelity ---------------------------------------------------------


def measure_written_csv(destination: Path) -> tuple[int, int | None]:
    """Bytes on disk and data rows parsed back out of the file."""
    size = destination.stat().st_size
    if size == 0:
        return 0, 0
    try:
        with destination.open("r", newline="") as handle:
            rows = sum(1 for _ in csv.reader(handle))
    except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
        return size, None
    return size, max(rows - 1, 0)


def count_dropped_attributes(dataset: Any) -> int:
    """Global plus per-variable attributes, all of which a CSV writer loses."""
    total = len(getattr(dataset, "attrs", {}) or {})
    for name in getattr(dataset, "variables", {}):
        total += len(dataset[name].attrs or {})
    return total


def dangling_grid_mappings(dataset: Any, written: set[str]) -> list[str]:
    """CF ``grid_mapping`` containers a written variable names but the file lacks."""
    dangling: list[str] = []
    for name in written:
        try:
            target = dataset[name].attrs.get("grid_mapping")
        except (KeyError, AttributeError):  # pragma: no cover - defensive
            continue
        if isinstance(target, str):
            container = target.split(":")[0].strip()
            if container and container not in written and container not in dangling:
                dangling.append(container)
    return dangling


def export_fidelity(
    *,
    format: str,
    destination: Path,
    rows_expected: int | None = None,
    rows_written: int | None = None,
    n_variables_written: int | None = None,
    variables_dropped: list[str] | None = None,
    attributes_dropped: int = 0,
    missing_values: int = 0,
    missing_written_as: str | None = None,
    dangling_grid_mapping: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the fidelity block, measuring ``bytes_written`` off the file."""
    block: dict[str, Any] = {
        "format": format,
        "bytes_written": destination.stat().st_size if destination.exists() else 0,
        "variables_dropped": variables_dropped or [],
        "attributes_dropped": int(attributes_dropped),
        "missing_values": int(missing_values),
        "dangling_grid_mapping": dangling_grid_mapping or [],
    }
    if n_variables_written is not None:
        block["n_variables_written"] = int(n_variables_written)
    if rows_written is not None:
        block["rows_written"] = int(rows_written)
    if rows_expected is not None:
        block["rows_expected"] = int(rows_expected)
    if missing_values and missing_written_as is not None:
        block["missing_written_as"] = missing_written_as
    return block


def export_fidelity_warning_codes(fidelity: dict[str, Any]) -> list[str]:
    """Codes for the ways an export can be lossy; an empty block yields none."""
    if not fidelity:
        return []

    codes: list[str] = []
    if fidelity.get("bytes_written") == 0:
        codes.append("EXPORT_EMPTY_FILE")

    written = fidelity.get("rows_written")
    expected = fidelity.get("rows_expected")
    if written is not None and expected is not None and written != expected:
        codes.append("EXPORT_ROW_COUNT_MISMATCH")

    if fidelity.get("variables_dropped"):
        codes.append("EXPORT_VARIABLES_DROPPED")
    if fidelity.get("attributes_dropped"):
        codes.append("EXPORT_ATTRIBUTES_DROPPED")
    if fidelity.get("missing_values"):
        codes.append("EXPORT_MISSING_VALUES_UNMARKED")
    if fidelity.get("dangling_grid_mapping"):
        codes.append("EXPORT_DANGLING_GRID_MAPPING")
    return codes
