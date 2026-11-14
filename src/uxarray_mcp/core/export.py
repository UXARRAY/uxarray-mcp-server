"""Write a grid, DataArray or Dataset to disk and report what reached the file.

``export_fidelity`` is measured on the written file, not on the plan: CSV has
nowhere to put an attribute or a missing-value sentinel, and a one-variable
NetCDF can leave a CF ``grid_mapping`` pointing at nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from uxarray_mcp.core.coverage import (
    count_dropped_attributes,
    dangling_grid_mappings,
    export_fidelity,
    export_fidelity_warning_codes,
    measure_written_csv,
)

_UGRID_CONNECTIVITY_NAMES = (
    "face_node_connectivity",
    "face_edge_connectivity",
    "face_face_connectivity",
    "edge_node_connectivity",
    "edge_face_connectivity",
    "node_edge_connectivity",
    "node_face_connectivity",
)


# --- NetCDF repairs ----------------------------------------------------------


def widen_narrow_fill_values(ds: xr.Dataset) -> xr.Dataset:
    """Widen integer arrays whose ``_FillValue`` does not fit their dtype.

    uxarray's ICON reader pairs int32 connectivity with the int64 UGRID
    sentinel, which netCDF4 rejects at ``createVariable``.
    """
    for name, var in ds.variables.items():
        fill = var.attrs.get("_FillValue")
        if fill is None or not np.issubdtype(var.dtype, np.integer):
            continue
        info = np.iinfo(var.dtype)
        if info.min <= int(fill) <= info.max:
            continue
        ds[name] = var.astype(np.int64)
        ds[name].attrs = dict(var.attrs)
    return ds


def drop_phantom_topology_attrs(ds: xr.Dataset) -> xr.Dataset:
    """Strip ``grid_topology`` attributes naming variables absent from the file.

    uxarray's encoder mutates a shared attribute template, so a grid exported
    after a richer one inherits connectivity names it does not have and cannot
    be read back.
    """
    topology = ds.variables.get("grid_topology")
    if topology is None:
        return ds
    present = set(ds.variables)
    kept: dict[str, Any] = {}
    for key, value in topology.attrs.items():
        if not isinstance(value, str):
            kept[key] = value
            continue
        if key in _UGRID_CONNECTIVITY_NAMES and value not in present:
            continue
        if key.endswith("_coordinates") and not set(value.split()) <= present:
            continue
        if key.endswith("_dimension") and value not in ds.dims:
            continue
        kept[key] = value
    ds["grid_topology"].attrs = kept
    return ds


def _sanitize_attr_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (str, int, float)):
        return value
    if value is None:
        return ""
    return str(value)


def sanitize_netcdf_attrs(data: Any) -> Any:
    """Copy with attributes netCDF4 can store (bools to int, None to '')."""
    cleaned = data.copy(deep=False)
    cleaned.attrs = {
        str(key): _sanitize_attr_value(value)
        for key, value in getattr(data, "attrs", {}).items()
    }
    for name in getattr(cleaned, "data_vars", {}):
        cleaned[name].attrs = {
            str(key): _sanitize_attr_value(value)
            for key, value in cleaned[name].attrs.items()
        }
    return cleaned


def write_grid_artifact(grid: Any, path: str | Path) -> str:
    """Write a uxarray Grid as UGRID NetCDF with both upstream repairs applied."""
    encoded = drop_phantom_topology_attrs(widen_narrow_fill_values(grid.to_xarray()))
    encoded.to_netcdf(path)
    return str(path)


def write_dataarray_artifact(data: Any, path: str | Path) -> str:
    """Write a (Ux)DataArray to NetCDF."""
    sanitize_netcdf_attrs(_as_xarray(data)).to_netcdf(path)
    return str(path)


def write_dataset_artifact(data: Any, path: str | Path) -> str:
    """Write a (Ux)Dataset to NetCDF."""
    sanitize_netcdf_attrs(_as_xarray(data)).to_netcdf(path)
    return str(path)


def _as_xarray(obj: Any) -> Any:
    to_xarray = getattr(obj, "to_xarray", None)
    if callable(to_xarray) and not isinstance(obj, (xr.DataArray, xr.Dataset)):
        return to_xarray()
    return obj


# --- export ops --------------------------------------------------------------


def _finish(result: dict[str, Any], fidelity: dict[str, Any]) -> dict[str, Any]:
    result["export_fidelity"] = fidelity
    result["coverage"] = fidelity
    result["warning_codes"] = export_fidelity_warning_codes(fidelity)
    return result


def export_dataarray(
    obj: Any, output_path: str, format: str = "netcdf"
) -> dict[str, Any]:
    """Write one in-memory array to ``netcdf`` or ``csv`` and measure the file."""
    data = _as_xarray(obj)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized = format.lower()
    if normalized == "netcdf":
        write_dataarray_artifact(data, destination)
        fidelity = export_fidelity(
            format="netcdf", destination=destination, n_variables_written=1
        )
        return _finish({"output_path": str(destination), "format": "netcdf"}, fidelity)
    if normalized == "csv":
        frame = data.to_dataframe(name=data.name or "value").reset_index()
        frame.to_csv(destination, index=False)
        _, rows_written = measure_written_csv(destination)
        fidelity = export_fidelity(
            format="csv",
            destination=destination,
            rows_expected=len(frame),
            rows_written=rows_written,
            n_variables_written=1,
            attributes_dropped=len(data.attrs or {}),
            missing_values=int(frame.isna().sum().sum()),
            missing_written_as="empty field",
        )
        return _finish(
            {
                "output_path": str(destination),
                "format": "csv",
                "summary": {"rows_written": rows_written},
            },
            fidelity,
        )
    raise ValueError("Unsupported format. Choose 'netcdf' or 'csv'.")


def export_dataset(
    obj: Any,
    output_path: str,
    format: str = "netcdf",
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Write an in-memory dataset, or one variable of it, and measure the file.

    Exporting one variable is a request, not a mistake; the reply names the
    siblings left behind and any CF container they still point at.
    """
    dataset = _as_xarray(obj)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if variable_name is not None and variable_name not in dataset:
        raise ValueError(f"Variable '{variable_name}' not found in dataset.")
    export_ds = dataset if variable_name is None else dataset[[variable_name]]
    kept = set(export_ds.variables)
    dropped = sorted(set(dataset.variables) - kept)
    n_written = len(export_ds.data_vars)

    normalized = format.lower()
    if normalized == "netcdf":
        write_dataset_artifact(export_ds, destination)
        fidelity = export_fidelity(
            format="netcdf",
            destination=destination,
            n_variables_written=n_written,
            variables_dropped=dropped,
            dangling_grid_mapping=dangling_grid_mappings(dataset, kept),
        )
        return _finish({"output_path": str(destination), "format": "netcdf"}, fidelity)
    if normalized == "csv":
        frame = export_ds.to_dataframe().reset_index()
        frame.to_csv(destination, index=False)
        _, rows_written = measure_written_csv(destination)
        fidelity = export_fidelity(
            format="csv",
            destination=destination,
            rows_expected=len(frame),
            rows_written=rows_written,
            n_variables_written=n_written,
            variables_dropped=dropped,
            attributes_dropped=count_dropped_attributes(export_ds),
            missing_values=int(frame.isna().sum().sum()),
            missing_written_as="empty field",
        )
        return _finish(
            {
                "output_path": str(destination),
                "format": "csv",
                "summary": {"rows_written": rows_written},
            },
            fidelity,
        )
    raise ValueError("Unsupported format. Choose 'netcdf' or 'csv'.")
