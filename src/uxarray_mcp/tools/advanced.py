"""Advanced analysis, remapping, export, and subsetting tools."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import uxarray as ux
import xarray as xr
from matplotlib.path import Path as MplPath

from uxarray_mcp.domain.mesh import load_dataset, load_grid
from uxarray_mcp.provenance import attach_provenance
from uxarray_mcp.state import (
    OperationTracker,
    copy_artifact,
    get_result,
    get_session,
    persist_result,
    save_result,
    summarize_array,
    summarize_dataset,
    summarize_grid,
    write_dataarray_artifact,
    write_dataset_artifact,
    write_grid_artifact,
    write_json_artifact,
)


def _resolve_paths(
    *,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    grid_path: str | None = None,
    data_path: str | None = None,
) -> tuple[str, str | None]:
    if dataset_handle is not None:
        if session_id is None:
            raise ValueError("session_id is required when dataset_handle is provided.")
        session = get_session(session_id)
        dataset = session["datasets"].get(dataset_handle)
        if dataset is None:
            raise FileNotFoundError(
                f"Dataset handle {dataset_handle!r} not found in session {session_id!r}"
            )
        return dataset["grid_path"], dataset.get("data_path")
    if grid_path is None:
        raise ValueError("grid_path is required when dataset_handle is not provided.")
    return grid_path, data_path


def _load_dataarray(
    grid_path: str,
    data_path: str,
    variable_name: str | None,
) -> tuple[ux.UxDataset, ux.UxDataArray, str]:
    uxds = load_dataset(grid_path, data_path)
    selected = variable_name
    if selected is None:
        for name, var in uxds.data_vars.items():
            if "n_face" in var.dims or "nCells" in var.dims:
                selected = name
                break
    if selected is None:
        raise ValueError("No face-centered variable found in dataset.")
    if selected not in uxds.data_vars:
        raise ValueError(
            f"Variable '{selected}' not found. Available variables: {list(uxds.data_vars)}"
        )
    return uxds, uxds[selected], selected


def _persist_grid_result(
    *,
    grid: Any,
    session_id: str | None,
    name: str,
    kind: str,
    summary: dict[str, Any],
) -> str:
    result = persist_result(
        kind=kind,
        name=name,
        summary=summary,
        session_id=session_id,
    )
    artifact_path = write_grid_artifact(grid, result["result_handle"])
    result["artifact_path"] = artifact_path
    save_result(result)
    return result["result_handle"]


def _persist_dataarray_result(
    *,
    data: Any,
    session_id: str | None,
    name: str,
    kind: str,
    summary: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    result = persist_result(
        kind=kind,
        name=name,
        summary=summary,
        session_id=session_id,
        metadata=metadata,
    )
    artifact_path = write_dataarray_artifact(data, result["result_handle"])
    result["artifact_path"] = artifact_path
    save_result(result)
    return result["result_handle"]


def _persist_dataset_result(
    *,
    dataset: Any,
    session_id: str | None,
    name: str,
    kind: str,
    summary: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    result = persist_result(
        kind=kind,
        name=name,
        summary=summary,
        session_id=session_id,
        metadata=metadata,
    )
    artifact_path = write_dataset_artifact(dataset, result["result_handle"])
    result["artifact_path"] = artifact_path
    save_result(result)
    return result["result_handle"]


def subset_bbox(
    lon_bounds: list[float],
    lat_bounds: list[float],
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Subset a mesh or face-centered variable by longitude/latitude bounds."""
    tracker = OperationTracker("subset_bbox", session_id=session_id)
    tracker.stage("loading", "Loading grid and optional dataset.")
    resolved_grid, resolved_data = _resolve_paths(
        session_id=session_id,
        dataset_handle=dataset_handle,
        grid_path=grid_path,
        data_path=data_path,
    )
    grid = load_grid(resolved_grid)
    subset_grid = grid.subset.bounding_box(tuple(lon_bounds), tuple(lat_bounds))
    result_handle = None
    variable_summary = None

    if resolved_data is not None:
        tracker.stage("subsetting", "Applying bbox to variable data.")
        _, uxda, selected = _load_dataarray(resolved_grid, resolved_data, variable_name)
        subset_data = uxda.subset.bounding_box(tuple(lon_bounds), tuple(lat_bounds))
        variable_summary = summarize_array(subset_data.to_xarray())
        result_handle = _persist_dataarray_result(
            data=subset_data,
            session_id=session_id,
            name=result_name or f"bbox:{selected}",
            kind="subset_bbox",
            summary=variable_summary,
            metadata={
                "selection_type": "bbox",
                "lon_bounds": lon_bounds,
                "lat_bounds": lat_bounds,
                "variable_name": selected,
            },
        )
    else:
        tracker.stage("subsetting", "Applying bbox to grid only.")
        result_handle = _persist_grid_result(
            grid=subset_grid,
            session_id=session_id,
            name=result_name or "bbox_grid_subset",
            kind="subset_bbox_grid",
            summary=summarize_grid(subset_grid),
        )

    result: dict[str, Any] = {
        "selection_type": "bbox",
        "lon_bounds": lon_bounds,
        "lat_bounds": lat_bounds,
        "original_grid": summarize_grid(grid),
        "subset_grid": summarize_grid(subset_grid),
        "variable_summary": variable_summary,
        "result_handle": result_handle,
    }
    next_steps = [
        f'plot_mesh(grid_path="{resolved_grid}")',
        f'export_to_netcdf("<output.nc>", result_handle="{result_handle}")',
    ]
    if resolved_data is not None:
        next_steps.insert(
            0,
            f'plot_variable("{resolved_grid}", "{resolved_data}", "<variable_name>")',
        )
    result["recommended_next_steps"] = next_steps
    tracker.succeed("Bounding-box subset complete.")
    result = attach_provenance(
        result,
        tool="subset_bbox",
        inputs={
            "lon_bounds": lon_bounds,
            "lat_bounds": lat_bounds,
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def subset_polygon(
    polygon_lon_lat: list[list[float]],
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Select faces whose centers fall within a polygon."""
    if len(polygon_lon_lat) < 3:
        raise ValueError("polygon_lon_lat must contain at least three points.")

    tracker = OperationTracker("subset_polygon", session_id=session_id)
    resolved_grid, resolved_data = _resolve_paths(
        session_id=session_id,
        dataset_handle=dataset_handle,
        grid_path=grid_path,
        data_path=data_path,
    )
    grid = load_grid(resolved_grid)
    face_points = np.column_stack(
        (np.asarray(grid.face_lon), np.asarray(grid.face_lat))
    )
    polygon = MplPath(np.asarray(polygon_lon_lat))
    selected_indices = np.flatnonzero(polygon.contains_points(face_points))

    variable_summary = None
    result_handle = None
    if resolved_data is not None:
        tracker.stage("subsetting", "Selecting polygon faces from variable data.")
        _, uxda, selected = _load_dataarray(resolved_grid, resolved_data, variable_name)
        face_dim = "n_face" if "n_face" in uxda.dims else "nCells"
        subset_data = uxda.isel({face_dim: selected_indices})
        variable_summary = summarize_array(subset_data.to_xarray())
        result_handle = _persist_dataarray_result(
            data=subset_data,
            session_id=session_id,
            name=result_name or f"polygon:{selected}",
            kind="subset_polygon",
            summary=variable_summary,
            metadata={
                "selection_type": "polygon",
                "polygon_lon_lat": polygon_lon_lat,
                "variable_name": selected,
                "selected_face_indices": selected_indices.tolist(),
            },
        )
    else:
        payload = {
            "selection_type": "polygon",
            "polygon_lon_lat": polygon_lon_lat,
            "selected_face_indices": selected_indices.tolist(),
        }
        selection_record = persist_result(
            kind="subset_polygon_indices",
            name=result_name or "polygon_face_selection",
            summary={
                "selected_face_count": int(selected_indices.size),
                "selected_face_indices_preview": selected_indices[:25].tolist(),
            },
            session_id=session_id,
        )
        artifact_path = write_json_artifact(payload, selection_record["result_handle"])
        selection_record["artifact_path"] = artifact_path
        save_result(selection_record)
        result_handle = selection_record["result_handle"]

    tracker.succeed("Polygon selection complete.")
    result: dict[str, Any] = {
        "selection_type": "polygon",
        "selected_face_count": int(selected_indices.size),
        "selected_face_indices_preview": selected_indices[:25].tolist(),
        "variable_summary": variable_summary,
        "result_handle": result_handle,
    }
    next_steps = [
        f'plot_mesh(grid_path="{resolved_grid}")',
        f'export_to_netcdf("<output.nc>", result_handle="{result_handle}")',
    ]
    if resolved_data is not None:
        next_steps.insert(
            0,
            f'plot_variable("{resolved_grid}", "{resolved_data}", "<variable_name>")',
        )
    result["recommended_next_steps"] = next_steps
    result = attach_provenance(
        result,
        tool="subset_polygon",
        inputs={
            "polygon_lon_lat": polygon_lon_lat,
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def extract_cross_section(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Extract a constant-latitude or constant-longitude cross-section."""
    if (latitude is None) == (longitude is None):
        raise ValueError("Provide exactly one of latitude or longitude.")

    tracker = OperationTracker("extract_cross_section", session_id=session_id)
    resolved_grid, resolved_data = _resolve_paths(
        session_id=session_id,
        dataset_handle=dataset_handle,
        grid_path=grid_path,
        data_path=data_path,
    )
    grid = load_grid(resolved_grid)
    if latitude is not None:
        subset_grid = grid.subset.constant_latitude(latitude)
        selection_type = "constant_latitude"
    else:
        subset_grid = grid.subset.constant_longitude(longitude)
        selection_type = "constant_longitude"

    result_handle = None
    variable_summary = None
    if resolved_data is not None:
        _, uxda, selected = _load_dataarray(resolved_grid, resolved_data, variable_name)
        if latitude is not None:
            subset_data = uxda.subset.constant_latitude(latitude)
        else:
            subset_data = uxda.subset.constant_longitude(longitude)
        variable_summary = summarize_array(subset_data.to_xarray())
        result_handle = _persist_dataarray_result(
            data=subset_data,
            session_id=session_id,
            name=result_name or f"{selection_type}:{selected}",
            kind="cross_section",
            summary=variable_summary,
            metadata={
                "selection_type": selection_type,
                "latitude": latitude,
                "longitude": longitude,
                "variable_name": selected,
            },
        )
    else:
        result_handle = _persist_grid_result(
            grid=subset_grid,
            session_id=session_id,
            name=result_name or selection_type,
            kind="cross_section_grid",
            summary=summarize_grid(subset_grid),
        )

    tracker.succeed("Cross-section extraction complete.")
    result: dict[str, Any] = {
        "selection_type": selection_type,
        "latitude": latitude,
        "longitude": longitude,
        "subset_grid": summarize_grid(subset_grid),
        "variable_summary": variable_summary,
        "result_handle": result_handle,
    }
    next_steps = [
        f'plot_mesh(grid_path="{resolved_grid}")',
        f'export_to_netcdf("<output.nc>", result_handle="{result_handle}")',
    ]
    if resolved_data is not None:
        next_steps.insert(
            0,
            f'calculate_zonal_mean("{resolved_grid}", "{resolved_data}", "<variable_name>")',
        )
    result["recommended_next_steps"] = next_steps
    result = attach_provenance(
        result,
        tool="extract_cross_section",
        inputs={
            "latitude": latitude,
            "longitude": longitude,
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def _load_comparison_arrays(
    *,
    grid_path: str | None,
    data_path_a: str,
    data_path_b: str,
    variable_name: str,
) -> tuple[xr.DataArray, xr.DataArray]:
    if grid_path:
        first = load_dataset(grid_path, data_path_a)[variable_name].to_xarray()
        second = load_dataset(grid_path, data_path_b)[variable_name].to_xarray()
    else:
        first = xr.open_dataset(data_path_a)[variable_name]
        second = xr.open_dataset(data_path_b)[variable_name]
    if first.shape != second.shape or first.dims != second.dims:
        raise ValueError(
            "Comparison requires same-grid, same-shape variables in v1. "
            f"Got dims {first.dims}/{second.dims} and shapes {first.shape}/{second.shape}."
        )
    return first, second


def _pattern_correlation(first: xr.DataArray, second: xr.DataArray) -> float:
    a = np.asarray(first.values).ravel()
    b = np.asarray(second.values).ravel()
    mask = np.isfinite(a) & np.isfinite(b)
    if not mask.any():
        raise ValueError("No finite overlapping values available for correlation.")
    a = a[mask] - np.mean(a[mask])
    b = b[mask] - np.mean(b[mask])
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def compare_fields(
    variable_name: str,
    data_path_a: str,
    data_path_b: str,
    grid_path: str | None = None,
    session_id: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Compare two same-grid fields and compute core difference metrics."""
    tracker = OperationTracker("compare_fields", session_id=session_id)
    tracker.stage("loading", "Loading comparison fields.")
    first, second = _load_comparison_arrays(
        grid_path=grid_path,
        data_path_a=data_path_a,
        data_path_b=data_path_b,
        variable_name=variable_name,
    )
    tracker.stage("comparing", "Computing field-to-field metrics.")
    diff = first - second
    bias = float(diff.mean(skipna=True).item())
    rmse = float(np.sqrt((diff**2).mean(skipna=True)).item())
    pattern = _pattern_correlation(first, second)
    result_handle = _persist_dataarray_result(
        data=diff,
        session_id=session_id,
        name=result_name or f"diff:{variable_name}",
        kind="comparison_difference",
        summary=summarize_array(diff),
        metadata={
            "variable_name": variable_name,
            "data_path_a": data_path_a,
            "data_path_b": data_path_b,
        },
    )
    tracker.succeed("Field comparison complete.")
    result: dict[str, Any] = {
        "variable_name": variable_name,
        "alignment_summary": {
            "same_dims": True,
            "dims": list(first.dims),
            "shape": list(first.shape),
            "grid_path": grid_path,
        },
        "metrics": {
            "bias": bias,
            "rmse": rmse,
            "pattern_correlation": pattern,
            "max_abs_difference": float(np.nanmax(np.abs(diff.values))),
        },
        "difference_field_handle": result_handle,
    }
    result = attach_provenance(
        result,
        tool="compare_fields",
        inputs={
            "variable_name": variable_name,
            "data_path_a": data_path_a,
            "data_path_b": data_path_b,
            "grid_path": grid_path,
            "session_id": session_id,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def calculate_bias(
    variable_name: str,
    data_path_a: str,
    data_path_b: str,
    grid_path: str | None = None,
) -> dict[str, Any]:
    """Calculate the mean bias between two same-grid fields."""
    comparison = compare_fields(
        variable_name=variable_name,
        data_path_a=data_path_a,
        data_path_b=data_path_b,
        grid_path=grid_path,
    )
    return attach_provenance(
        {"variable_name": variable_name, "bias": comparison["metrics"]["bias"]},
        tool="calculate_bias",
        inputs={
            "variable_name": variable_name,
            "data_path_a": data_path_a,
            "data_path_b": data_path_b,
            "grid_path": grid_path,
        },
    )


def calculate_rmse(
    variable_name: str,
    data_path_a: str,
    data_path_b: str,
    grid_path: str | None = None,
) -> dict[str, Any]:
    """Calculate RMSE between two same-grid fields."""
    comparison = compare_fields(
        variable_name=variable_name,
        data_path_a=data_path_a,
        data_path_b=data_path_b,
        grid_path=grid_path,
    )
    return attach_provenance(
        {"variable_name": variable_name, "rmse": comparison["metrics"]["rmse"]},
        tool="calculate_rmse",
        inputs={
            "variable_name": variable_name,
            "data_path_a": data_path_a,
            "data_path_b": data_path_b,
            "grid_path": grid_path,
        },
    )


def calculate_pattern_correlation(
    variable_name: str,
    data_path_a: str,
    data_path_b: str,
    grid_path: str | None = None,
) -> dict[str, Any]:
    """Calculate pattern correlation between two same-grid fields."""
    comparison = compare_fields(
        variable_name=variable_name,
        data_path_a=data_path_a,
        data_path_b=data_path_b,
        grid_path=grid_path,
    )
    return attach_provenance(
        {
            "variable_name": variable_name,
            "pattern_correlation": comparison["metrics"]["pattern_correlation"],
        },
        tool="calculate_pattern_correlation",
        inputs={
            "variable_name": variable_name,
            "data_path_a": data_path_a,
            "data_path_b": data_path_b,
            "grid_path": grid_path,
        },
    )


def remap_variable(
    target_grid_path: str,
    variable_name: str,
    grid_path: str | None = None,
    data_path: str | None = None,
    method: str = "nearest_neighbor",
    remap_to: str = "faces",
    session_id: str | None = None,
    dataset_handle: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Remap a face-centered variable onto a target grid."""
    tracker = OperationTracker("remap_variable", session_id=session_id)
    resolved_grid, resolved_data = _resolve_paths(
        session_id=session_id,
        dataset_handle=dataset_handle,
        grid_path=grid_path,
        data_path=data_path,
    )
    if resolved_data is None:
        raise ValueError("data_path is required for remapping.")

    source_grid = load_grid(resolved_grid)
    target_grid = load_grid(target_grid_path)
    _, uxda, selected = _load_dataarray(resolved_grid, resolved_data, variable_name)

    if not hasattr(uxda.remap, method):
        raise ValueError(
            f"Unsupported remap method {method!r}. Choose from "
            "'nearest_neighbor', 'inverse_distance_weighted', or 'bilinear'."
        )
    tracker.stage("remapping", f"Running {method} remap.")
    remapped = getattr(uxda.remap, method)(target_grid, remap_to=remap_to)
    result_handle = _persist_dataarray_result(
        data=remapped,
        session_id=session_id,
        name=result_name or f"remap:{selected}",
        kind="remapped_variable",
        summary=summarize_array(remapped.to_xarray()),
        metadata={
            "source_grid": resolved_grid,
            "target_grid": target_grid_path,
            "method": method,
            "remap_to": remap_to,
            "variable_name": selected,
        },
    )
    tracker.succeed("Variable remap complete.")
    result: dict[str, Any] = {
        "variable_name": selected,
        "method": method,
        "remap_to": remap_to,
        "source_grid": summarize_grid(source_grid),
        "target_grid": summarize_grid(target_grid),
        "result_handle": result_handle,
    }
    result = attach_provenance(
        result,
        tool="remap_variable",
        inputs={
            "target_grid_path": target_grid_path,
            "variable_name": variable_name,
            "grid_path": grid_path,
            "data_path": data_path,
            "method": method,
            "remap_to": remap_to,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
        selected_variable=selected,
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def regrid_dataset(
    target_grid_path: str,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_names: list[str] | None = None,
    method: str = "nearest_neighbor",
    remap_to: str = "faces",
    session_id: str | None = None,
    dataset_handle: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Remap all selected face-centered variables in a dataset onto a target grid."""
    tracker = OperationTracker("regrid_dataset", session_id=session_id)
    resolved_grid, resolved_data = _resolve_paths(
        session_id=session_id,
        dataset_handle=dataset_handle,
        grid_path=grid_path,
        data_path=data_path,
    )
    if resolved_data is None:
        raise ValueError("data_path is required to regrid a dataset.")

    uxds = load_dataset(resolved_grid, resolved_data)
    target_grid = load_grid(target_grid_path)
    if not hasattr(uxds[next(iter(uxds.data_vars))].remap, method):
        raise ValueError(
            f"Unsupported remap method {method!r}. Choose from "
            "'nearest_neighbor', 'inverse_distance_weighted', or 'bilinear'."
        )
    variables = variable_names or [
        name
        for name, var in uxds.data_vars.items()
        if "n_face" in var.dims or "nCells" in var.dims
    ]
    if not variables:
        raise ValueError("No face-centered variables available for remapping.")
    dataset_parts = []
    for name in variables:
        tracker.stage("remapping", f"Remapping variable {name}")
        remapped = getattr(uxds[name].remap, method)(target_grid, remap_to=remap_to)
        dataset_parts.append(remapped.to_dataset(name=name).to_xarray())
    remapped_dataset = xr.merge(dataset_parts)
    result_handle = _persist_dataset_result(
        dataset=remapped_dataset,
        session_id=session_id,
        name=result_name or "regridded_dataset",
        kind="regridded_dataset",
        summary=summarize_dataset(remapped_dataset),
        metadata={
            "source_grid": resolved_grid,
            "target_grid": target_grid_path,
            "method": method,
            "variables": variables,
        },
    )
    tracker.succeed("Dataset regridding complete.")
    result: dict[str, Any] = {
        "method": method,
        "variables": variables,
        "target_grid": summarize_grid(target_grid),
        "result_handle": result_handle,
    }
    result = attach_provenance(
        result,
        tool="regrid_dataset",
        inputs={
            "target_grid_path": target_grid_path,
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_names": variable_names,
            "method": method,
            "remap_to": remap_to,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def calculate_temporal_mean(
    data_path: str,
    variable_name: str,
    groupby: str | None = None,
    session_id: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Take the time average of a variable over the time dimension (temporal mean / time-mean climatology, optionally grouped by month or season)."""
    tracker = OperationTracker("calculate_temporal_mean", session_id=session_id)
    ds = xr.open_dataset(data_path)
    if variable_name not in ds:
        raise ValueError(f"Variable '{variable_name}' not found in {data_path}.")
    data = ds[variable_name]
    if "time" not in data.dims:
        raise ValueError("Temporal mean requires a variable with a 'time' dimension.")
    tracker.stage("aggregating", "Computing temporal mean.")
    if groupby is None:
        result_data = data.mean(dim="time")
    else:
        result_data = data.groupby(f"time.{groupby}").mean()
    result_handle = _persist_dataarray_result(
        data=result_data,
        session_id=session_id,
        name=result_name or f"temporal_mean:{variable_name}",
        kind="temporal_mean",
        summary=summarize_array(result_data),
        metadata={"groupby": groupby, "variable_name": variable_name},
    )
    tracker.succeed("Temporal mean complete.")
    result: dict[str, Any] = {
        "variable_name": variable_name,
        "groupby": groupby,
        "summary": summarize_array(result_data),
        "result_handle": result_handle,
    }
    result = attach_provenance(
        result,
        tool="calculate_temporal_mean",
        inputs={
            "data_path": data_path,
            "variable_name": variable_name,
            "groupby": groupby,
            "session_id": session_id,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def calculate_anomaly(
    data_path: str,
    variable_name: str,
    baseline: str = "temporal_mean",
    session_id: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Calculate anomalies relative to the temporal mean baseline."""
    if baseline != "temporal_mean":
        raise ValueError("v1 supports only baseline='temporal_mean'.")
    tracker = OperationTracker("calculate_anomaly", session_id=session_id)
    ds = xr.open_dataset(data_path)
    if variable_name not in ds:
        raise ValueError(f"Variable '{variable_name}' not found in {data_path}.")
    data = ds[variable_name]
    if "time" not in data.dims:
        raise ValueError("Anomaly calculation requires a 'time' dimension.")
    tracker.stage("aggregating", "Computing temporal baseline and anomalies.")
    anomaly = data - data.mean(dim="time")
    result_handle = _persist_dataarray_result(
        data=anomaly,
        session_id=session_id,
        name=result_name or f"anomaly:{variable_name}",
        kind="anomaly",
        summary=summarize_array(anomaly),
        metadata={"baseline": baseline, "variable_name": variable_name},
    )
    tracker.succeed("Anomaly calculation complete.")
    result: dict[str, Any] = {
        "variable_name": variable_name,
        "baseline": baseline,
        "summary": summarize_array(anomaly),
        "result_handle": result_handle,
    }
    result = attach_provenance(
        result,
        tool="calculate_anomaly",
        inputs={
            "data_path": data_path,
            "variable_name": variable_name,
            "baseline": baseline,
            "session_id": session_id,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def _load_ensemble(variable_name: str, data_paths: Sequence[str]) -> xr.DataArray:
    datasets = []
    for data_path in data_paths:
        ds = xr.open_dataset(data_path)
        if variable_name not in ds:
            raise ValueError(f"Variable '{variable_name}' not found in {data_path}.")
        datasets.append(ds[variable_name])
    reference = datasets[0]
    for dataset in datasets[1:]:
        if dataset.shape != reference.shape or dataset.dims != reference.dims:
            raise ValueError("All ensemble members must share dims and shape in v1.")
    return xr.concat(datasets, dim="ensemble_member")


def calculate_ensemble_mean(
    variable_name: str,
    data_paths: list[str],
    session_id: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Average a variable across multiple ensemble members (one file per member) — the ensemble mean / multi-model mean."""
    tracker = OperationTracker("calculate_ensemble_mean", session_id=session_id)
    ensemble = _load_ensemble(variable_name, data_paths)
    result_data = ensemble.mean(dim="ensemble_member")
    result_handle = _persist_dataarray_result(
        data=result_data,
        session_id=session_id,
        name=result_name or f"ensemble_mean:{variable_name}",
        kind="ensemble_mean",
        summary=summarize_array(result_data),
        metadata={"member_count": len(data_paths), "variable_name": variable_name},
    )
    tracker.succeed("Ensemble mean complete.")
    result: dict[str, Any] = {
        "variable_name": variable_name,
        "member_count": len(data_paths),
        "summary": summarize_array(result_data),
        "result_handle": result_handle,
    }
    result = attach_provenance(
        result,
        tool="calculate_ensemble_mean",
        inputs={
            "variable_name": variable_name,
            "data_paths": data_paths,
            "session_id": session_id,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def calculate_ensemble_spread(
    variable_name: str,
    data_paths: list[str],
    session_id: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Calculate ensemble spread as standard deviation across members."""
    tracker = OperationTracker("calculate_ensemble_spread", session_id=session_id)
    ensemble = _load_ensemble(variable_name, data_paths)
    result_data = ensemble.std(dim="ensemble_member")
    result_handle = _persist_dataarray_result(
        data=result_data,
        session_id=session_id,
        name=result_name or f"ensemble_spread:{variable_name}",
        kind="ensemble_spread",
        summary=summarize_array(result_data),
        metadata={"member_count": len(data_paths), "variable_name": variable_name},
    )
    tracker.succeed("Ensemble spread complete.")
    result: dict[str, Any] = {
        "variable_name": variable_name,
        "member_count": len(data_paths),
        "summary": summarize_array(result_data),
        "result_handle": result_handle,
    }
    result = attach_provenance(
        result,
        tool="calculate_ensemble_spread",
        inputs={
            "variable_name": variable_name,
            "data_paths": data_paths,
            "session_id": session_id,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def export_to_netcdf(
    output_path: str,
    result_handle: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Export a persisted result or registered dataset to NetCDF."""
    tracker = OperationTracker("export_to_netcdf", session_id=session_id)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if result_handle is not None:
        stored_result = get_result(result_handle)
        artifact_path = stored_result.get("artifact_path")
        if artifact_path is None:
            raise ValueError("Result handle has no exportable artifact.")
        written = copy_artifact(artifact_path, output_path)
        summary = stored_result["summary"]
    elif dataset_handle is not None:
        if session_id is None:
            raise ValueError("session_id is required when exporting a dataset_handle.")
        dataset = get_session(session_id)["datasets"].get(dataset_handle)
        if dataset is None:
            raise FileNotFoundError(
                f"Dataset handle {dataset_handle!r} not found in session {session_id!r}"
            )
        if dataset.get("data_path") is None:
            raise ValueError("Dataset handle does not include a data file to export.")
        if variable_name is None:
            written = copy_artifact(dataset["data_path"], output_path)
            summary = {"copied_source": dataset["data_path"]}
        else:
            ds = xr.open_dataset(dataset["data_path"])
            if variable_name not in ds:
                raise ValueError(
                    f"Variable '{variable_name}' not found in {dataset['data_path']}."
                )
            ds[[variable_name]].to_netcdf(output_path)
            written = str(destination)
            summary = summarize_dataset(ds[[variable_name]])
    else:
        raise ValueError("Provide either result_handle or dataset_handle.")

    tracker.succeed("NetCDF export complete.")
    response: dict[str, Any] = {"output_path": written, "summary": summary}
    response = attach_provenance(
        response,
        tool="export_to_netcdf",
        inputs={
            "output_path": output_path,
            "result_handle": result_handle,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
            "variable_name": variable_name,
        },
    )
    response["_provenance"]["operation_id"] = tracker.operation_id
    return response


def export_to_csv(
    output_path: str,
    result_handle: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Export a persisted result or registered dataset to CSV."""
    tracker = OperationTracker("export_to_csv", session_id=session_id)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if result_handle is not None:
        stored_result = get_result(result_handle)
        artifact_path = stored_result.get("artifact_path")
        if artifact_path is None:
            raise ValueError("Result handle has no exportable artifact.")
        artifact = Path(artifact_path)
        if artifact.suffix == ".json":
            payload = json.loads(artifact.read_text())
            with destination.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=sorted(payload))
                writer.writeheader()
                writer.writerow(payload)
            summary = {"rows_written": 1}
        else:
            try:
                data = xr.open_dataarray(artifact)
                frame = data.to_dataframe(name=data.name or "value").reset_index()
            except ValueError:
                dataset_artifact = xr.open_dataset(artifact)
                frame = dataset_artifact.to_dataframe().reset_index()
            frame.to_csv(destination, index=False)
            summary = {"rows_written": int(len(frame))}
    elif dataset_handle is not None:
        if session_id is None:
            raise ValueError("session_id is required when exporting a dataset_handle.")
        dataset = get_session(session_id)["datasets"].get(dataset_handle)
        if dataset is None:
            raise FileNotFoundError(
                f"Dataset handle {dataset_handle!r} not found in session {session_id!r}"
            )
        if dataset.get("data_path") is None:
            raise ValueError("Dataset handle does not include a data file to export.")
        ds = xr.open_dataset(dataset["data_path"])
        if variable_name is not None and variable_name not in ds:
            raise ValueError(
                f"Variable '{variable_name}' not found in {dataset['data_path']}."
            )
        export_ds = ds if variable_name is None else ds[[variable_name]]
        frame = export_ds.to_dataframe().reset_index()
        frame.to_csv(destination, index=False)
        summary = {"rows_written": int(len(frame))}
    else:
        raise ValueError("Provide either result_handle or dataset_handle.")

    tracker.succeed("CSV export complete.")
    response: dict[str, Any] = {"output_path": str(destination), "summary": summary}
    response = attach_provenance(
        response,
        tool="export_to_csv",
        inputs={
            "output_path": output_path,
            "result_handle": result_handle,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
            "variable_name": variable_name,
        },
    )
    response["_provenance"]["operation_id"] = tracker.operation_id
    return response


def write_result(
    output_path: str,
    format: str,
    result_handle: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Write a result or dataset using the requested output format."""
    normalized = format.lower()
    if normalized == "netcdf":
        return export_to_netcdf(
            output_path=output_path,
            result_handle=result_handle,
            session_id=session_id,
            dataset_handle=dataset_handle,
            variable_name=variable_name,
        )
    if normalized == "csv":
        return export_to_csv(
            output_path=output_path,
            result_handle=result_handle,
            session_id=session_id,
            dataset_handle=dataset_handle,
            variable_name=variable_name,
        )
    raise ValueError("Unsupported format. Choose 'netcdf' or 'csv'.")
