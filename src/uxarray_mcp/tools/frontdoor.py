"""High-level MCP front-door tools.

These functions intentionally group many implementation capabilities behind a
small public tool surface. The lower-level functions remain available as the
Python API, but MCP clients get fewer, intent-shaped choices.
"""

from __future__ import annotations

from typing import Any


def _require(value: Any, name: str, operation: str) -> Any:
    if value is None:
        raise ValueError(f"{operation!r} requires {name}.")
    return value


def run_analysis(
    operation: str,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    target_grid_path: str | None = None,
    data_path_a: str | None = None,
    data_path_b: str | None = None,
    data_paths: list[str] | None = None,
    u_variable: str | None = None,
    v_variable: str | None = None,
    lon_bounds: list[float] | None = None,
    lat_bounds: list[float] | None = None,
    polygon_lon_lat: list[list[float]] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    center_lon: float | None = None,
    center_lat: float | None = None,
    outer_radius: float | None = None,
    radius_step: float | None = None,
    method: str = "nearest_neighbor",
    remap_to: str = "faces",
    groupby: str | None = None,
    baseline: str = "temporal_mean",
    output_path: str | None = None,
    output_format: str = "netcdf",
    result_handle: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    result_name: str | None = None,
    scale_by_radius: bool = False,
    lat_spec: tuple | float | list[Any] | None = None,
    conservative: bool = False,
    target_lon: list[float] | None = None,
    target_lat: list[float] | None = None,
    use_remote: bool = False,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Run one analysis operation by intent instead of exposing many tools.

    Supported operations:
    ``inspect_mesh``, ``inspect_variable``, ``validate_dataset``,
    ``calculate_area``, ``calculate_zonal_mean``, ``zonal_anomaly``,
    ``gradient``, ``curl``, ``divergence``, ``azimuthal_mean``,
    ``subset_bbox``, ``subset_polygon``, ``cross_section``, ``compare_fields``,
    ``bias``, ``rmse``, ``pattern_correlation``, ``remap_variable``,
    ``regrid_dataset``, ``remap_to_rectilinear``, ``temporal_mean``,
    ``anomaly``, ``ensemble_mean``, ``ensemble_spread``, and ``export``.

    ``gradient`` and ``curl`` accept ``scale_by_radius`` (default False keeps the
    historical unit-sphere result). ``zonal_anomaly`` accepts ``lat_spec`` and
    ``conservative``. ``remap_to_rectilinear`` accepts ``target_lon`` and
    ``target_lat`` (1-D coordinate arrays).
    """
    from uxarray_mcp.tools.advanced import (
        calculate_anomaly,
        calculate_bias,
        calculate_ensemble_mean,
        calculate_ensemble_spread,
        calculate_pattern_correlation,
        calculate_rmse,
        calculate_temporal_mean,
        compare_fields,
        extract_cross_section,
        regrid_dataset,
        remap_to_rectilinear,
        remap_variable,
        subset_bbox,
        subset_polygon,
        write_result,
    )
    from uxarray_mcp.tools.inspection import calculate_zonal_anomaly, validate_dataset
    from uxarray_mcp.tools.remote_tools import (
        calculate_area,
        calculate_zonal_mean,
        inspect_mesh,
        inspect_variable,
    )
    from uxarray_mcp.tools.vector_calc import (
        calculate_azimuthal_mean,
        calculate_curl,
        calculate_divergence,
        calculate_gradient,
    )

    op = operation.strip().lower().replace("-", "_")

    if op == "inspect_mesh":
        return inspect_mesh(
            _require(grid_path, "grid_path", op),
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "inspect_variable":
        return inspect_variable(
            _require(grid_path, "grid_path", op),
            _require(data_path, "data_path", op),
            variable_name,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "validate_dataset":
        return validate_dataset(
            _require(grid_path, "grid_path", op),
            _require(data_path, "data_path", op),
        )
    if op == "calculate_area":
        return calculate_area(
            _require(grid_path, "grid_path", op),
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "calculate_zonal_mean":
        return calculate_zonal_mean(
            _require(grid_path, "grid_path", op),
            _require(data_path, "data_path", op),
            _require(variable_name, "variable_name", op),
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "zonal_anomaly":
        return calculate_zonal_anomaly(
            _require(grid_path, "grid_path", op),
            _require(data_path, "data_path", op),
            _require(variable_name, "variable_name", op),
            lat_spec=lat_spec,
            conservative=conservative,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "gradient":
        return calculate_gradient(
            _require(grid_path, "grid_path", op),
            _require(data_path, "data_path", op),
            _require(variable_name, "variable_name", op),
            scale_by_radius=scale_by_radius,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "curl":
        return calculate_curl(
            _require(grid_path, "grid_path", op),
            _require(data_path, "data_path", op),
            _require(u_variable, "u_variable", op),
            _require(v_variable, "v_variable", op),
            scale_by_radius=scale_by_radius,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "divergence":
        return calculate_divergence(
            _require(grid_path, "grid_path", op),
            _require(data_path, "data_path", op),
            _require(u_variable, "u_variable", op),
            _require(v_variable, "v_variable", op),
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "azimuthal_mean":
        return calculate_azimuthal_mean(
            _require(grid_path, "grid_path", op),
            _require(data_path, "data_path", op),
            _require(variable_name, "variable_name", op),
            _require(center_lon, "center_lon", op),
            _require(center_lat, "center_lat", op),
            _require(outer_radius, "outer_radius", op),
            _require(radius_step, "radius_step", op),
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        )
    if op == "subset_bbox":
        return subset_bbox(
            lon_bounds=_require(lon_bounds, "lon_bounds", op),
            lat_bounds=_require(lat_bounds, "lat_bounds", op),
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            session_id=session_id,
            dataset_handle=dataset_handle,
            result_name=result_name,
        )
    if op == "subset_polygon":
        return subset_polygon(
            polygon_lon_lat=_require(polygon_lon_lat, "polygon_lon_lat", op),
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            session_id=session_id,
            dataset_handle=dataset_handle,
            result_name=result_name,
        )
    if op == "cross_section":
        return extract_cross_section(
            latitude=latitude,
            longitude=longitude,
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            session_id=session_id,
            dataset_handle=dataset_handle,
            result_name=result_name,
        )
    if op == "compare_fields":
        return compare_fields(
            variable_name=_require(variable_name, "variable_name", op),
            data_path_a=_require(data_path_a, "data_path_a", op),
            data_path_b=_require(data_path_b, "data_path_b", op),
            grid_path=grid_path,
            session_id=session_id,
            result_name=result_name,
        )
    if op == "bias":
        return calculate_bias(
            variable_name=_require(variable_name, "variable_name", op),
            data_path_a=_require(data_path_a, "data_path_a", op),
            data_path_b=_require(data_path_b, "data_path_b", op),
            grid_path=grid_path,
        )
    if op == "rmse":
        return calculate_rmse(
            variable_name=_require(variable_name, "variable_name", op),
            data_path_a=_require(data_path_a, "data_path_a", op),
            data_path_b=_require(data_path_b, "data_path_b", op),
            grid_path=grid_path,
        )
    if op == "pattern_correlation":
        return calculate_pattern_correlation(
            variable_name=_require(variable_name, "variable_name", op),
            data_path_a=_require(data_path_a, "data_path_a", op),
            data_path_b=_require(data_path_b, "data_path_b", op),
            grid_path=grid_path,
        )
    if op == "remap_variable":
        return remap_variable(
            target_grid_path=_require(target_grid_path, "target_grid_path", op),
            variable_name=_require(variable_name, "variable_name", op),
            grid_path=grid_path,
            data_path=data_path,
            method=method,
            remap_to=remap_to,
            session_id=session_id,
            dataset_handle=dataset_handle,
            result_name=result_name,
            use_remote=use_remote,
            endpoint=endpoint,
        )
    if op == "regrid_dataset":
        return regrid_dataset(
            target_grid_path=_require(target_grid_path, "target_grid_path", op),
            grid_path=grid_path,
            data_path=data_path,
            variable_names=[variable_name] if variable_name else None,
            method=method,
            remap_to=remap_to,
            session_id=session_id,
            dataset_handle=dataset_handle,
            result_name=result_name,
            use_remote=use_remote,
            endpoint=endpoint,
        )
    if op == "remap_to_rectilinear":
        return remap_to_rectilinear(
            variable_name=_require(variable_name, "variable_name", op),
            target_lon=_require(target_lon, "target_lon", op),
            target_lat=_require(target_lat, "target_lat", op),
            grid_path=grid_path,
            data_path=data_path,
            session_id=session_id,
            dataset_handle=dataset_handle,
            result_name=result_name,
            use_remote=use_remote,
            endpoint=endpoint,
        )
    if op == "temporal_mean":
        return calculate_temporal_mean(
            data_path=_require(data_path, "data_path", op),
            variable_name=_require(variable_name, "variable_name", op),
            groupby=groupby,
            session_id=session_id,
            result_name=result_name,
        )
    if op == "anomaly":
        return calculate_anomaly(
            data_path=_require(data_path, "data_path", op),
            variable_name=_require(variable_name, "variable_name", op),
            baseline=baseline,
            session_id=session_id,
            result_name=result_name,
        )
    if op == "ensemble_mean":
        return calculate_ensemble_mean(
            variable_name=_require(variable_name, "variable_name", op),
            data_paths=_require(data_paths, "data_paths", op),
            session_id=session_id,
            result_name=result_name,
        )
    if op == "ensemble_spread":
        return calculate_ensemble_spread(
            variable_name=_require(variable_name, "variable_name", op),
            data_paths=_require(data_paths, "data_paths", op),
            session_id=session_id,
            result_name=result_name,
        )
    if op == "export":
        return write_result(
            output_path=_require(output_path, "output_path", op),
            format=output_format,
            result_handle=result_handle,
            session_id=session_id,
            dataset_handle=dataset_handle,
            variable_name=variable_name,
        )

    raise ValueError(f"Unsupported analysis operation {operation!r}.")


def plot_dataset(
    plot_type: str,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    title: str | None = None,
    time_index: int = 0,
    lat_spec: tuple | float | list[Any] | None = None,
    conservative: bool = False,
    line_color: str = "#1f77b4",
    lon_bounds: list[float] | None = None,
    lat_bounds: list[float] | None = None,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
) -> list[Any]:
    """Render mesh, geographic mesh, variable, or zonal-mean plots."""
    from uxarray_mcp.tools.plotting import plot_mesh_geo
    from uxarray_mcp.tools.remote_tools import plot_mesh, plot_variable, plot_zonal_mean

    kind = plot_type.strip().lower().replace("-", "_")
    if kind == "mesh":
        return plot_mesh(
            grid_path=grid_path,
            width=width,
            height=height,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
            dataset_handle=dataset_handle,
        )
    if kind == "mesh_geo":
        return plot_mesh_geo(
            grid_path=grid_path,
            width=width,
            height=height,
            lon_bounds=lon_bounds,
            lat_bounds=lat_bounds,
            session_id=session_id,
            dataset_handle=dataset_handle,
        )
    if kind == "variable":
        return plot_variable(
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            width=width,
            height=height,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            title=title,
            time_index=time_index,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
            dataset_handle=dataset_handle,
        )
    if kind == "zonal_mean":
        return plot_zonal_mean(
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            width=width,
            height=height,
            lat_spec=lat_spec,
            conservative=conservative,
            line_color=line_color,
            title=title,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
            dataset_handle=dataset_handle,
        )
    raise ValueError("plot_type must be one of: mesh, mesh_geo, variable, zonal_mean.")


def diagnose_endpoint(
    action: str = "status",
    endpoint: str | None = None,
    file_path: str | None = None,
    use_remote: bool = True,
    inspect_netcdf: bool = True,
    probe_timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Check whether the HPC Globus Compute endpoint is healthy, active, and reachable — endpoint status, worker setup validation, and remote file readability."""
    from uxarray_mcp.tools.execution_control import (
        endpoint_status,
        probe_path_access,
        validate_hpc_setup,
    )

    mode = action.strip().lower().replace("-", "_")
    if mode == "status":
        return endpoint_status(
            endpoint=endpoint,
            force=True,
            probe=True,
            probe_timeout_seconds=probe_timeout_seconds,
        )
    if mode == "validate":
        return validate_hpc_setup(
            run_remote_probe=True,
            probe_timeout_seconds=probe_timeout_seconds,
            sample_path=file_path,
            endpoint=endpoint,
        )
    if mode == "probe_path":
        return probe_path_access(
            _require(file_path, "file_path", mode),
            use_remote=use_remote,
            inspect_netcdf=inspect_netcdf,
            endpoint=endpoint,
        )
    raise ValueError("action must be one of: status, validate, probe_path.")


def manage_session(
    action: str,
    session_id: str | None = None,
    name: str | None = None,
    grid_path: str | None = None,
    data_path: str | None = None,
    dataset_handle: str | None = None,
    clear_artifacts: bool = False,
) -> dict[str, Any]:
    """Create, register, inspect, reset, or list session-scoped state."""
    from uxarray_mcp.tools.stateful import (
        create_session,
        get_session_state,
        list_operations,
        register_dataset,
        reset_session_state,
    )

    mode = action.strip().lower().replace("-", "_")
    if mode == "create":
        return create_session(name=name)
    if mode == "register_dataset":
        return register_dataset(
            session_id=_require(session_id, "session_id", mode),
            grid_path=_require(grid_path, "grid_path", mode),
            data_path=data_path,
            name=name,
        )
    if mode == "get":
        return get_session_state(_require(session_id, "session_id", mode))
    if mode == "reset":
        return reset_session_state(
            _require(session_id, "session_id", mode),
            clear_artifacts=clear_artifacts,
        )
    if mode == "list_operations":
        return list_operations(session_id=session_id)
    if mode == "dataset":
        state = get_session_state(_require(session_id, "session_id", mode))
        handle = _require(dataset_handle, "dataset_handle", mode)
        dataset = state.get("datasets", {}).get(handle)
        if dataset is None:
            raise FileNotFoundError(f"Dataset handle {handle!r} not found.")
        return {
            "dataset_handle": handle,
            "dataset": dataset,
            "_provenance": state["_provenance"],
        }
    raise ValueError(
        "action must be one of: create, register_dataset, get, reset, list_operations, dataset."
    )


def get_status(
    kind: str,
    workflow_id: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Return workflow or operation status."""
    from uxarray_mcp.tools.stateful import get_operation_status, get_workflow_status

    mode = kind.strip().lower()
    if mode == "workflow":
        return get_workflow_status(_require(workflow_id, "workflow_id", mode))
    if mode == "operation":
        return get_operation_status(_require(operation_id, "operation_id", mode))
    raise ValueError("kind must be one of: workflow, operation.")


def get_result(result_handle: str) -> dict[str, Any]:
    """Inspect a persisted result handle and artifact metadata."""
    from uxarray_mcp.tools.stateful import get_result_handle

    return get_result_handle(result_handle)
