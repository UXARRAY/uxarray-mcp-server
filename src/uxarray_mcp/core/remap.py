"""Remap face-centred fields onto another mesh or a rectilinear grid.

Coverage is measured before the remap because the remap fills every target
point regardless, so afterwards an interpolated value and an extrapolated one
look the same.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from uxarray_mcp.core.coverage import (
    compute_target_coverage,
    grid_target_coverage,
    remap_coverage_warnings,
)
from uxarray_mcp.core.fields import (
    load_face_variable,
    summarize_array,
    summarize_dataset,
    summarize_grid,
)
from uxarray_mcp.core.mesh import load_dataset, load_grid
from uxarray_mcp.core.remap_backend import (
    RemapPlan,
    resolve_remap_plan,
    yac_unavailable_message,
)


def _run_remap(uxda: Any, target_grid: Any, plan: RemapPlan, remap_to: str) -> Any:
    """Dispatch one remap; a missing YAC install is re-raised with the repair."""
    if plan.backend == "yac":
        try:
            return uxda.remap.nearest_neighbor(
                target_grid,
                remap_to=remap_to,
                backend="yac",
                yac_method=plan.yac_method,
            )
        except Exception as exc:
            if "yac" in type(exc).__name__.lower() or "yac.core" in str(exc):
                raise RuntimeError(yac_unavailable_message("local machine")) from exc
            raise
    return getattr(uxda.remap, plan.method)(target_grid, remap_to=remap_to)


def _finish(
    result: dict[str, Any], plan: RemapPlan, coverage: dict[str, Any] | None
) -> dict[str, Any]:
    result.update(
        {
            "method": plan.label,
            "backend": plan.backend,
            "yac_method": plan.yac_method,
            "coverage": coverage,
            "warning_codes": list(coverage.get("warning_codes", []))
            if coverage
            else [],
            "warnings": remap_coverage_warnings(coverage),
        }
    )
    if coverage is not None:
        result["source_coverage"] = coverage
    return result


def remap_variable(
    grid_path: str,
    data_path: str,
    variable_name: str | None,
    target_grid_path: str,
    method: str = "nearest_neighbor",
    remap_to: str = "faces",
    backend: str = "uxarray",
    yac_method: str | None = None,
) -> dict[str, Any]:
    """Remap one variable onto a target mesh. ``method`` may name a UXarray
    method or a YAC one (``conservative`` etc.), which selects the YAC backend."""
    plan = resolve_remap_plan(method=method, backend=backend, yac_method=yac_method)
    source_grid = load_grid(grid_path)
    target_grid = load_grid(target_grid_path)
    _, uxda, selected = load_face_variable(grid_path, data_path, variable_name)
    coverage = grid_target_coverage(
        uxda.uxgrid, target_grid, remap_to=remap_to, method=plan.coverage_method
    )
    remapped = _run_remap(uxda, target_grid, plan, remap_to)
    result: dict[str, Any] = {
        "variable_name": selected,
        "remap_to": remap_to,
        "source_grid": summarize_grid(source_grid),
        "target_grid": summarize_grid(target_grid),
        "variable_summary": summarize_array(remapped.to_xarray()),
        "_payload": remapped,
    }
    return _finish(result, plan, coverage)


def regrid_dataset(
    grid_path: str,
    data_path: str,
    target_grid_path: str,
    variable_names: list[str] | None = None,
    method: str = "nearest_neighbor",
    remap_to: str = "faces",
    backend: str = "uxarray",
    yac_method: str | None = None,
) -> dict[str, Any]:
    """Remap every face-centred variable (or the named ones) onto a target mesh."""
    plan = resolve_remap_plan(method=method, backend=backend, yac_method=yac_method)
    uxds = load_dataset(grid_path, data_path)
    target_grid = load_grid(target_grid_path)
    variables = variable_names or [
        name
        for name, var in uxds.data_vars.items()
        if "n_face" in var.dims or "nCells" in var.dims
    ]
    if not variables:
        raise ValueError("No face-centered variables available for remapping.")
    coverage = grid_target_coverage(
        uxds.uxgrid, target_grid, remap_to=remap_to, method=plan.coverage_method
    )
    parts = [
        _run_remap(uxds[name], target_grid, plan, remap_to)
        .to_dataset(name=name)
        .to_xarray()
        for name in variables
    ]
    remapped = xr.merge(parts)
    result: dict[str, Any] = {
        "variables": variables,
        "remap_to": remap_to,
        "target_grid": summarize_grid(target_grid),
        "dataset_summary": summarize_dataset(remapped),
        "_payload": remapped,
    }
    return _finish(result, plan, coverage)


def remap_to_rectilinear(
    grid_path: str,
    data_path: str,
    variable_name: str | None,
    target_lon: list[float],
    target_lat: list[float],
    backend: str = "uxarray",
    yac_method: str | None = None,
) -> dict[str, Any]:
    """Remap onto 1-D lon/lat cell-centre axes. ``_payload`` is a Dataset with
    the variable on (..., lat, lon)."""
    plan = resolve_remap_plan(
        method=yac_method or "nearest_neighbor", backend=backend, yac_method=yac_method
    )
    _, uxda, selected = load_face_variable(grid_path, data_path, variable_name)
    if not hasattr(uxda.remap, "to_rectilinear"):
        raise NotImplementedError(
            "remap_to_rectilinear requires a UXarray release that provides "
            "remap.to_rectilinear. Upgrade uxarray to use this operation."
        )
    lon = [float(v) for v in target_lon]
    lat = [float(v) for v in target_lat]
    coverage = compute_target_coverage(
        uxda.uxgrid, lon, lat, method=plan.coverage_method
    )
    try:
        remapped = uxda.remap.to_rectilinear(
            lon, lat, backend=plan.backend, yac_method=plan.yac_method
        )
    except Exception as exc:
        if plan.backend == "yac" and (
            "yac" in type(exc).__name__.lower() or "yac.core" in str(exc)
        ):
            raise RuntimeError(yac_unavailable_message("local machine")) from exc
        if plan.backend == "yac" and "Cannot reshape remapped data" in str(exc):
            raise RuntimeError(
                f"{exc} This is a known UXarray limitation of backend='yac' "
                "when target_lon spans the full 360 degrees. Use a regional "
                "target_lon, or backend='uxarray' for a global one."
            ) from exc
        raise

    vals = np.asarray(remapped.values, dtype=float)
    finite = vals[np.isfinite(vals)]
    stats: dict[str, float | None] = (
        {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
        }
        if finite.size
        else {"min": None, "max": None, "mean": None}
    )
    result: dict[str, Any] = {
        "variable_name": selected,
        "target_shape": [len(lat), len(lon)],
        "result_dims": [str(d) for d in remapped.dims],
        "stats": stats,
        "_payload": remapped.to_dataset(name=selected),
    }
    return _finish(result, plan, coverage)
