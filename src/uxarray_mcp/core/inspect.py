"""Pure inspection operations: topology, variables, validation, area, zonal means.

Each function takes paths, loads with ``core.mesh``, and returns a JSON-safe
dict. No provenance, next steps or session handling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from uxarray_mcp.core.area import compute_area_stats
from uxarray_mcp.core.coverage import compute_mesh_coverage
from uxarray_mcp.core.mesh import (
    is_healpix_spec,
    is_remote_uri,
    load_dataset,
    load_grid,
)
from uxarray_mcp.core.variable import compute_variable_info
from uxarray_mcp.core.zonal import compute_zonal_anomaly_stats, compute_zonal_mean_stats

# Above this, ``n_edge`` builds the full edge connectivity and is reported as skipped.
N_EDGE_MAX_FACES = 250_000

_FILL_VALUE_CANDIDATES = [1e20, 9.96920996838687e36, -999.0, -9999.0]
_SUSPICIOUS_FILL_VALUES = [9999, -9999, 999999, -999999, 9.96921e36]

LatSpec = tuple | float | list | None


def _require_grid(grid_path: str, label: str = "Grid") -> None:
    if is_healpix_spec(grid_path) or is_remote_uri(grid_path):
        return
    if not Path(grid_path).exists():
        raise FileNotFoundError(f"{label} file not found: {grid_path}")


def _require_data(data_path: str) -> None:
    if not is_remote_uri(data_path) and not Path(data_path).exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")


def _load_grid(grid_path: str) -> Any:
    try:
        return load_grid(grid_path)
    except Exception as exc:
        if is_healpix_spec(grid_path) and isinstance(exc, ValueError):
            raise ValueError(
                "Invalid HEALPix format. Use 'healpix:<zoom_level>' (e.g., 'healpix:2')."
            ) from None
        raise RuntimeError(f"Failed to load mesh file: {exc}") from exc


def _load_dataset(grid_path: str, data_path: str) -> Any:
    _require_grid(grid_path)
    _require_data(data_path)
    try:
        return load_dataset(grid_path, data_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to load dataset: {exc}") from exc


def _edge_count(grid: Any, n_face: int) -> dict[str, Any]:
    """``n_edge`` when affordable; ``None`` plus a reason when it is not."""
    stored = "edge_node_connectivity" in getattr(grid, "_ds", {})
    if n_face <= N_EDGE_MAX_FACES or stored:
        return {"n_edge": int(grid.n_edge)}
    return {
        "n_edge": None,
        "n_edge_skipped": (
            f"{n_face} faces exceeds the {N_EDGE_MAX_FACES}-face limit for "
            "constructing edge connectivity, and the file does not store it; "
            "n_edge was not computed."
        ),
    }


def inspect_mesh(grid_path: str) -> dict[str, Any]:
    """Topology summary plus ``mesh_coverage``; expensive fields are skipped and named."""
    if is_healpix_spec(grid_path):
        file_size_mb: float | None = 0.0
        grid = _load_grid(grid_path)
        fmt = "HEALPix"
    else:
        _require_grid(grid_path, label="Mesh")
        file_size_mb = (
            None
            if is_remote_uri(grid_path)
            else round(Path(grid_path).stat().st_size / (1024 * 1024), 2)
        )
        grid = _load_grid(grid_path)
        fmt = str(grid.source_grid_spec)

    n_face = int(grid.n_face)
    result: dict[str, Any] = {
        "format": fmt,
        "n_face": n_face,
        "n_node": int(grid.n_node),
        **_edge_count(grid, n_face),
        "n_max_face_nodes": int(grid.n_max_face_nodes),
        "file_size_mb": file_size_mb,
        "mesh_coverage": compute_mesh_coverage(grid),
    }
    return result


def grid_facts(grid_path: str, data_path: str | None = None) -> dict[str, Any]:
    """Small facts block: format, counts, globality, and variable locations if data given."""
    _require_grid(grid_path)
    grid = _load_grid(grid_path)
    n_face = int(grid.n_face)
    coverage = compute_mesh_coverage(grid)
    fraction = coverage.get("sphere_fraction")
    facts: dict[str, Any] = {
        "grid_format": "HEALPix"
        if is_healpix_spec(grid_path)
        else str(getattr(grid, "source_grid_spec", "Unknown")),
        "n_face": n_face,
        "n_node": int(grid.n_node),
        **_edge_count(grid, n_face),
        "is_global": None if fraction is None else bool(abs(fraction - 1.0) < 1e-3),
    }
    if data_path is None:
        return facts
    uxds = _load_dataset(grid_path, data_path)
    facts["variables"] = [
        {
            "name": str(name),
            "location": _location(uxds[name].dims),
            "dims": [str(d) for d in uxds[name].dims],
            "units": uxds[name].attrs.get("units"),
            "standard_name": uxds[name].attrs.get("standard_name"),
            "long_name": uxds[name].attrs.get("long_name"),
        }
        for name in uxds.data_vars
    ]
    return facts


def _location(dims: Any) -> str:
    if any(d in dims for d in ("n_face", "nCells")):
        return "faces"
    if any(d in dims for d in ("n_node", "nVertices")):
        return "nodes"
    if any(d in dims for d in ("n_edge", "nEdges")):
        return "edges"
    return "other"


def inspect_variable(
    grid_path: str, data_path: str, variable_name: str | None = None
) -> dict[str, Any]:
    """Dims, dtype, location, attrs and statistics for one or all data variables."""
    uxds = _load_dataset(grid_path, data_path)
    return compute_variable_info(uxds, variable_name)


def calculate_area(
    grid_path: str, sphere_radius: float | None = None
) -> dict[str, Any]:
    """Face-area statistics with the ``area_basis`` block saying which radius applied."""
    _require_grid(grid_path, label="Mesh")
    grid = _load_grid(grid_path)
    try:
        return compute_area_stats(grid, sphere_radius=sphere_radius)
    except Exception as exc:
        raise RuntimeError(f"Failed to calculate face areas: {exc}") from exc


def calculate_zonal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: LatSpec = None,
    conservative: bool = False,
    time_index: int = 0,
    level_index: int = 0,
) -> dict[str, Any]:
    """Zonal mean of a face-centered variable along latitude lines or bands."""
    uxds = _load_dataset(grid_path, data_path)
    try:
        return compute_zonal_mean_stats(
            uxds,
            variable_name,
            lat_spec,
            conservative,
            time_index=time_index,
            level_index=level_index,
        )
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to compute zonal mean: {exc}") from exc


def zonal_anomaly(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: LatSpec = None,
    conservative: bool = False,
) -> dict[str, Any]:
    """Statistics of each face value minus its latitude-band zonal mean."""
    uxds = _load_dataset(grid_path, data_path)
    return compute_zonal_anomaly_stats(uxds, variable_name, lat_spec, conservative)


def _validate_variable(var_name: str, var: Any) -> tuple[dict[str, Any], list[str]]:
    """Per-variable checks; returns ``(record, issues)`` or ``({}, [])`` if non-numeric."""
    values = var.values
    if not np.issubdtype(values.dtype, np.number):
        return {}, []
    is_float = np.issubdtype(values.dtype, np.floating)

    n_nan = int(np.sum(np.isnan(values))) if is_float else 0
    n_inf = int(np.sum(np.isinf(values))) if is_float else 0
    total = int(values.size)
    nan_pct = (n_nan / total * 100) if total > 0 else 0.0

    fill_attr = var.attrs.get("_FillValue")
    fill_count = 0
    if fill_attr is not None and is_float:
        fill_count = int(np.sum(np.isclose(values, fill_attr, rtol=0, atol=0)))

    n_fill, detected_fill = 0, None
    suspicious = 0
    if is_float:
        for fv in _FILL_VALUE_CANDIDATES:
            count = int(np.sum(np.isclose(values, fv, rtol=1e-3)))
            if count > 0:
                n_fill, detected_fill = count, fv
                break
        for fv in _SUSPICIOUS_FILL_VALUES:
            suspicious += int(np.sum(np.isclose(values, fv, rtol=1e-5)))

    if is_float:
        valid = values[~np.isnan(values) & ~np.isinf(values)]
    else:
        valid = values
    value_range = [float(valid.min()), float(valid.max())] if valid.size else None

    lower = var_name.lower()
    coord_issues: list[str] = []
    is_lat = "lat" in lower or "latitude" in lower
    is_lon = "lon" in lower or "longitude" in lower
    if value_range and is_lat and (value_range[0] < -90 or value_range[1] > 90):
        coord_issues.append("latitude out of valid range [-90, 90]")
    if value_range and is_lon and (value_range[0] < -180 or value_range[1] > 360):
        coord_issues.append("longitude out of valid range [-180, 360]")

    passed = (
        n_nan == 0
        and n_inf == 0
        and n_fill == 0
        and fill_count == 0
        and not coord_issues
    )
    warnings: list[str] = []
    issues: list[str] = []
    if n_nan:
        msg = f"{var_name}: contains {n_nan} NaN values ({nan_pct:.2f}%)"
        warnings.append(msg)
        issues.append(msg)
    if n_inf:
        msg = f"{var_name}: contains {n_inf} Inf values"
        warnings.append(msg)
        issues.append(msg)
    if fill_count:
        msg = f"{var_name}: contains {fill_count} fill values ({fill_attr})"
        warnings.append(msg)
        issues.append(msg)
    if suspicious:
        msg = f"{var_name}: contains {suspicious} suspicious fill-like values"
        warnings.append(msg)
        issues.append(msg)
    elif n_fill and not fill_count:
        warnings.append(f"{var_name}: {n_fill} fill value(s) matching {detected_fill}")
    for ci in coord_issues:
        warnings.append(f"{var_name}: {ci}")
        issues.append(f"{var_name}: {ci}")

    record = {
        "name": var_name,
        "passed": passed,
        "n_nan": n_nan,
        "n_inf": n_inf,
        "n_fill_values": n_fill,
        "detected_fill_value": detected_fill,
        "shape": list(values.shape),
        "dtype": str(values.dtype),
        "warnings": warnings,
        "has_nan": n_nan > 0,
        "has_inf": n_inf > 0,
        "nan_count": n_nan,
        "inf_count": n_inf,
        "fill_value_count": fill_count,
        "suspicious_fill_count": suspicious,
        "total_values": total,
        "nan_percentage": round(nan_pct, 2),
        "value_range": value_range,
        "coordinate_issues": coord_issues or None,
    }
    return record, issues


def validate_dataset(grid_path: str, data_path: str) -> dict[str, Any]:
    """NaN/Inf/fill-value and lat-lon range checks per numeric variable, with ``passed``."""
    uxds = _load_dataset(grid_path, data_path)
    records: list[dict[str, Any]] = []
    issues: list[str] = []
    warnings: list[str] = []
    for var_name in uxds.data_vars:
        name = str(var_name)
        try:
            record, var_issues = _validate_variable(name, uxds[var_name])
        except Exception as exc:  # noqa: BLE001 - one bad variable must not hide the rest
            msg = f"Could not validate {name}: {exc}"
            issues.append(msg)
            warnings.append(msg)
            records.append(
                {"name": name, "passed": False, "error": str(exc), "warnings": [msg]}
            )
            continue
        if not record:
            continue
        records.append(record)
        issues.extend(var_issues)
        warnings.extend(record["warnings"])

    passed = all(r.get("passed", False) for r in records)
    return {
        "passed": passed,
        "n_variables_checked": len(records),
        "n_variables_failed": sum(1 for r in records if not r.get("passed", False)),
        "variables": records,
        "is_valid": passed,
        "issues": issues,
        "warnings": warnings,
    }
