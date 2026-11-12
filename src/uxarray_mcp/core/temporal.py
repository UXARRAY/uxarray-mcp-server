"""Reductions along ``time`` and across ensemble members.

Every result carries a coverage block, because ``mean(dim="time")`` returns a
full-length array whether it averaged twelve steps or none.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import numpy as np
import xarray as xr

from uxarray_mcp.core.compare import normalize_units
from uxarray_mcp.core.coverage import (
    compute_temporal_coverage,
    temporal_coverage_warning_codes,
)
from uxarray_mcp.core.fields import summarize_array
from uxarray_mcp.core.mesh import is_remote_uri, open_remote_store

#: Coordinates that pin down which mesh a member file's values live on.
_MESH_COORD_NAMES: tuple[str, ...] = (
    "node_lon",
    "node_lat",
    "face_lon",
    "face_lat",
    "lon",
    "lat",
    "longitude",
    "latitude",
)


def _open(data_path: str) -> xr.Dataset:
    if is_remote_uri(data_path):
        return open_remote_store(data_path)
    return xr.open_dataset(data_path)


def _time_variable(data_path: str, variable_name: str, what: str) -> xr.DataArray:
    ds = _open(data_path)
    if variable_name not in ds:
        raise ValueError(f"Variable '{variable_name}' not found in {data_path}.")
    data = ds[variable_name]
    if "time" not in data.dims:
        raise ValueError(f"{what} requires a variable with a 'time' dimension.")
    return data


def _finish(result: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    result["coverage"] = coverage
    result["temporal_coverage"] = coverage
    result["warning_codes"] = temporal_coverage_warning_codes(coverage)
    return result


def temporal_mean(
    data_path: str,
    variable_name: str,
    groupby: str | None = None,
    time_min: str | None = None,
    time_max: str | None = None,
) -> dict[str, Any]:
    """Mean over ``time``, optionally grouped (``"month"``, ``"season"``) and
    restricted to a closed ISO-8601 label range first."""
    data = _time_variable(data_path, variable_name, "Temporal mean")
    full_time = data["time"]
    if time_min is not None or time_max is not None:
        data = data.sel(time=slice(time_min, time_max))
        if data.sizes.get("time", 0) == 0:
            raise ValueError(
                f"No time steps fall in [{time_min}, {time_max}]. The file covers "
                f"{full_time.min().values} to {full_time.max().values}."
            )
    if groupby is None:
        result_data = data.mean(dim="time")
    else:
        result_data = data.groupby(f"time.{groupby}").mean()
    result: dict[str, Any] = {
        "variable_name": variable_name,
        "groupby": groupby,
        "summary": summarize_array(result_data),
        "_payload": result_data,
    }
    return _finish(
        result, compute_temporal_coverage(data, result_data, groupby=groupby)
    )


def anomaly(
    data_path: str,
    variable_name: str,
    baseline: str = "temporal_mean",
) -> dict[str, Any]:
    """``value - mean(time)``; coverage is measured against the source because
    the loss sits in the baseline, one reduction down."""
    if baseline != "temporal_mean":
        raise ValueError("Only baseline='temporal_mean' is supported.")
    data = _time_variable(data_path, variable_name, "Anomaly calculation")
    anomaly_data = data - data.mean(dim="time")
    result: dict[str, Any] = {
        "variable_name": variable_name,
        "baseline": baseline,
        "summary": summarize_array(anomaly_data),
        "_payload": anomaly_data,
    }
    return _finish(result, compute_temporal_coverage(data, anomaly_data))


def _member_grid_fingerprint(ds: xr.Dataset, member: xr.DataArray) -> str | None:
    """Hash the member's mesh coordinates, or None when it carries none."""
    digest = hashlib.sha256()
    digest.update(repr(tuple(zip(member.dims, member.shape))).encode())
    found = False
    for name in _MESH_COORD_NAMES:
        source = ds.coords.get(name)
        if source is None:
            source = ds.variables.get(name)
        if source is None:
            continue
        found = True
        digest.update(name.encode())
        digest.update(np.ascontiguousarray(np.asarray(source)).tobytes())
    return digest.hexdigest() if found else None


def load_ensemble(
    variable_name: str, data_paths: Sequence[str]
) -> tuple[xr.DataArray, dict[str, Any]]:
    """Concatenate members along ``ensemble_member`` with evidence about
    whether their units and meshes agree (None when unverifiable)."""
    if not data_paths:
        raise ValueError("At least one ensemble member path is required.")
    members: list[xr.DataArray] = []
    units: list[str | None] = []
    fingerprints: list[str | None] = []
    for data_path in data_paths:
        ds = xr.open_dataset(data_path)
        if variable_name not in ds:
            raise ValueError(f"Variable '{variable_name}' not found in {data_path}.")
        member = ds[variable_name]
        members.append(member)
        units.append(str((member.attrs or {}).get("units", "")).strip() or None)
        fingerprints.append(_member_grid_fingerprint(ds, member))
    reference = members[0]
    for member in members[1:]:
        if member.shape != reference.shape or member.dims != reference.dims:
            raise ValueError("All ensemble members must share dims and shape.")

    normalized = [normalize_units(u) for u in units]
    units_consistent: bool | None
    if any(u is None for u in normalized):
        units_consistent = None
    else:
        units_consistent = len(set(normalized)) == 1
    grids_consistent: bool | None
    if any(f is None for f in fingerprints):
        grids_consistent = None
    else:
        grids_consistent = len(set(fingerprints)) == 1

    evidence = {
        "member_count": len(members),
        "member_units": units,
        "units_consistent": units_consistent,
        "grids_consistent": grids_consistent,
        "grid_evidence": (
            "coordinates" if grids_consistent is not None else "dims_and_shape_only"
        ),
    }
    return xr.concat(members, dim="ensemble_member"), evidence


def _ensemble_reduce(
    variable_name: str, data_paths: Sequence[str], reduction: str
) -> dict[str, Any]:
    ensemble, evidence = load_ensemble(variable_name, data_paths)
    result_data = getattr(ensemble, reduction)(dim="ensemble_member")
    values = np.asarray(result_data.values, dtype=float)
    coverage = {
        "member_count": len(data_paths),
        "n_elements": int(values.size),
        "n_elements_with_value": int(np.isfinite(values).sum()),
    }
    warning_codes: list[str] = []
    if coverage["n_elements"] and not coverage["n_elements_with_value"]:
        warning_codes.append("ENSEMBLE_COVERAGE_ZERO")
    if evidence["units_consistent"] is None:
        warning_codes.append("ENSEMBLE_UNITS_UNDECLARED")
    elif evidence["units_consistent"] is False:
        warning_codes.append("ENSEMBLE_UNITS_MISMATCHED")
    if evidence["grids_consistent"] is None:
        warning_codes.append("ENSEMBLE_GRID_UNVERIFIED")
    return {
        "variable_name": variable_name,
        "member_count": len(data_paths),
        "summary": summarize_array(result_data),
        "member_evidence": evidence,
        "coverage": coverage,
        "warning_codes": warning_codes,
        "_payload": result_data,
    }


def ensemble_mean(variable_name: str, data_paths: list[str]) -> dict[str, Any]:
    """Mean across members, one file per member."""
    return _ensemble_reduce(variable_name, data_paths, "mean")


def ensemble_spread(variable_name: str, data_paths: list[str]) -> dict[str, Any]:
    """Standard deviation across members, one file per member."""
    return _ensemble_reduce(variable_name, data_paths, "std")
