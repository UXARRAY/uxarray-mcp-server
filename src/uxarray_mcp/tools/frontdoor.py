"""High-level MCP front-door tools.

These functions intentionally group many implementation capabilities behind a
small public tool surface. The lower-level functions remain available as the
Python API, but MCP clients get fewer, intent-shaped choices.
"""

from __future__ import annotations

from functools import wraps
from typing import Any

from uxarray_mcp.postconditions import (
    evaluate_area_postconditions,
    postcondition_block,
    resolve_verdict_policy,
)
from uxarray_mcp.preconditions import (
    RESULT_TYPE_COMPLETE,
    PreconditionRefusal,
    enforce,
    evaluate_remap_preconditions,
    evaluate_validation_preconditions,
    evaluate_vector_preconditions,
)


def _require(value: Any, name: str, operation: str) -> Any:
    if value is None:
        raise ValueError(f"{operation!r} requires {name}.")
    return value


def _reject_unsupported_remote(use_remote: bool, operation: str) -> None:
    """Fail loudly when `use_remote=True` is requested for an operation that
    has no remote implementation, instead of silently running locally.

    Without this, a caller who asks for HPC execution on a facility-only
    path (the file does not exist on their machine) got a confusing local
    ``FileNotFoundError`` with no indication that ``use_remote`` was ever
    honored -- exactly the "silent failure" this server's provenance and
    guardrail mechanisms otherwise exist to prevent.
    """
    if use_remote:
        raise ValueError(
            f"{operation!r} does not support use_remote=True yet -- it always "
            "runs locally. Pass a locally-readable path, or omit use_remote/"
            "endpoint for this operation."
        )


def _grid_loader(result: dict[str, Any]) -> Any:
    """Reopen the grid a result was computed from, or None if unknowable.

    Postconditions need the mesh itself (is it closed? what radius does it
    declare?), and the front door only has the result. The path is read
    back out of provenance rather than threaded through every dispatch
    branch, which keeps #89's parameter list from growing again.
    """
    inputs = result.get("_provenance", {}).get("inputs", {}) or {}
    path = inputs.get("file_path") or inputs.get("grid_path")
    if not path:
        return None

    def load() -> Any:
        import uxarray as ux

        return ux.open_grid(path)

    return load


def _finalize_analysis_result(
    operation: str,
    result: dict[str, Any],
    acknowledge: str | None = None,
    verdict_policy: str | None = None,
) -> dict[str, Any]:
    """Attach front-door semantics without changing low-level operation results."""
    status = "complete"
    physically_interpretable: bool | None = None
    warning_codes: list[str] = []
    preconditions: list[dict[str, Any]] | None = None

    if operation == "validate_dataset":
        passed = result.get("passed", result.get("is_valid"))
        physically_interpretable = None
        if passed is False:
            status = "invalid"
            warning_codes.append("DATASET_VALIDATION_FAILED")
        preconditions = evaluate_validation_preconditions(result)
    elif operation in {"curl", "divergence"}:
        evidence = result.get("component_evidence", {})
        metadata_supported = bool(
            evidence.get("units_supported")
            and evidence.get("component_identity_supported")
        )
        scaling_supported = operation != "curl" or bool(result.get("scale_by_radius"))
        physically_interpretable = bool(
            metadata_supported
            and scaling_supported
            and not result.get("component_warnings")
        )
        preconditions = evaluate_vector_preconditions(
            operation,
            str(result.get("u_variable", "")),
            str(result.get("v_variable", "")),
            evidence,
            result.get("scale_by_radius"),
        )
        if not physically_interpretable:
            status = "warning"
            if not metadata_supported:
                warning_codes.append("VECTOR_COMPONENTS_UNVERIFIED")
            if metadata_supported and not scaling_supported:
                warning_codes.append("PHYSICAL_SCALING_UNVERIFIED")
    elif operation == "remap_to_rectilinear" and "source_coverage" in result:
        # Absent coverage stays unknown rather than becoming a claim of
        # interpretability: a remote worker on an older build may not send it.
        codes = list(result["source_coverage"].get("warning_codes", []))
        physically_interpretable = not codes
        if codes:
            status = "warning"
            warning_codes.extend(codes)
        # #85 shipped these as warnings, and #86 measured that a warning
        # beside a number changes nothing. Zero coverage means every
        # returned value is extrapolated, which is exactly the case that
        # should refuse rather than advise.
        preconditions = evaluate_remap_preconditions(result["source_coverage"])

    # Refuses by default when a declared precondition fails: raises
    # PreconditionRefusal unless the caller passed the override token.
    # `validate_dataset` is exempt from refusal -- reporting that a dataset
    # is invalid IS its answer, so refusing to report it would be circular.
    if preconditions is not None and operation != "validate_dataset":
        precondition_block = enforce(operation, preconditions, acknowledge)
    elif preconditions is not None:
        precondition_block = {
            "status": "satisfied"
            if all(c["passed"] for c in preconditions)
            else "failed",
            "checks": preconditions,
            "failed_checks": [c["id"] for c in preconditions if not c["passed"]],
            "override_used": False,
        }
    else:
        # Distinct from "failed": #84's `not_evaluated` means we did not
        # check, not that a check came back negative.
        precondition_block = {
            "status": "not_evaluated",
            "checks": [],
            "failed_checks": [],
            "override_used": False,
        }

    if precondition_block["override_used"]:
        # An overridden result is never allowed to claim interpretability,
        # whatever the individual warning heuristics concluded.
        status = "unverified"
        physically_interpretable = False
        for check in precondition_block["failed_checks"]:
            code = f"PRECONDITION_FAILED_{check.upper()}"
            if code not in warning_codes:
                warning_codes.append(code)

    result["result_type"] = RESULT_TYPE_COMPLETE
    result["preconditions"] = precondition_block
    result["scientific_status"] = {
        "status": status,
        "physically_interpretable": physically_interpretable,
        "warning_codes": warning_codes,
    }
    # #84: an explicit "we did not check" is cheap and stops a caller
    # implying more confidence than the computation supports. #90: when a
    # check does run, whether the verdict comes with it is a policy.
    policy = resolve_verdict_policy(verdict_policy)
    post_checks: list[dict[str, Any]] = []
    if operation == "calculate_area" and policy != "off":
        post_checks = evaluate_area_postconditions(
            result, _grid_loader(result), policy=policy
        )
    result["postconditions"] = postcondition_block(post_checks, policy)
    return result


def _with_analysis_contract(func: Any) -> Any:
    """Preserve the MCP schema signature while finalizing successful results.

    A refused precondition comes back as a structured ``input_required``
    result rather than an exception, so an MCP client sees a payload it can
    act on instead of an error string it has to parse.
    """

    @wraps(func)
    def wrapped(operation: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        acknowledge = kwargs.get("acknowledge")
        verdict_policy = kwargs.get("verdict_policy")
        # Validated before the computation runs: a rejected policy should
        # cost nothing, and finding out afterwards would waste the work.
        resolve_verdict_policy(verdict_policy)
        result = func(operation, *args, **kwargs)
        normalized = operation.strip().lower().replace("-", "_")
        try:
            return _finalize_analysis_result(
                normalized, result, acknowledge, verdict_policy
            )
        except PreconditionRefusal as refusal:
            # The computation already ran to produce the metadata evidence the
            # checks read, but the number is deliberately dropped: the point of
            # #86 is that the caller does not get an unphysical value without
            # asking for it. Only the reason and the repairs come back.
            payload = dict(refusal.payload)
            payload["_provenance"] = result.get("_provenance", {})
            return payload

    return wrapped


def _resolve_optional_session(
    session_id: str | None, dataset_handle: str | None
) -> str | None:
    """Ignore a nonexistent optional session when explicit paths are sufficient."""
    if session_id is None or dataset_handle is not None:
        return session_id
    from uxarray_mcp.state import get_session

    try:
        get_session(session_id)
    except FileNotFoundError:
        return None
    return session_id


@_with_analysis_contract
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
    scale_by_radius: bool = True,
    time_index: int = 0,
    level_index: int = 0,
    lat_spec: tuple | float | list[Any] | None = None,
    conservative: bool = False,
    target_lon: list[float] | None = None,
    target_lat: list[float] | None = None,
    use_remote: bool = False,
    endpoint: str | None = None,
    acknowledge: str | None = None,
    verdict_policy: str | None = None,
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

    ``gradient`` and ``curl`` accept ``scale_by_radius`` (default True matches
    UXarray and returns physical units when sphere-radius metadata exists).
    ``gradient``, ``curl``, and ``divergence``
    also accept ``time_index``/``level_index`` to select a single time/level
    slice when the input variable(s) carry those extra dimensions (e.g. real
    model output shaped ``(time, lev, n_face)``); both default to 0 and are
    ignored for variables that are already face-centered only.
    ``zonal_anomaly`` accepts ``lat_spec`` and
    ``conservative``. ``remap_to_rectilinear`` accepts ``target_lon`` and
    ``target_lat`` (1-D coordinate arrays).

    ``curl`` and ``divergence`` declare preconditions and refuse rather than
    return an unphysical number: if the components are not verifiably a
    vector field, the call returns ``result_type='input_required'`` with the
    failed checks and the repairs that would fix them. Pass ``acknowledge``
    with the token named in that response to run it anyway; the result is
    then marked ``unverified``.

    ``verdict_policy`` controls the ``postconditions`` block: ``"full"``
    (default) returns reference, residual, tolerance, and verdict;
    ``"reference_only"`` returns reference and tolerance and requires the
    caller to compute the comparison itself; ``"off"`` evaluates nothing.
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
    from uxarray_mcp.tools.inspection import calculate_zonal_anomaly
    from uxarray_mcp.tools.remote_tools import (
        calculate_area,
        calculate_zonal_mean,
        inspect_mesh,
        inspect_variable,
        validate_dataset,
    )
    from uxarray_mcp.tools.vector_calc import (
        calculate_azimuthal_mean,
        calculate_curl,
        calculate_divergence,
        calculate_gradient,
    )

    op = operation.strip().lower().replace("-", "_")
    session_id = _resolve_optional_session(session_id, dataset_handle)

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
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
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
            time_index=time_index,
            level_index=level_index,
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
            time_index=time_index,
            level_index=level_index,
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
            time_index=time_index,
            level_index=level_index,
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
        _reject_unsupported_remote(use_remote, op)
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
        _reject_unsupported_remote(use_remote, op)
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
        _reject_unsupported_remote(use_remote, op)
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
        _reject_unsupported_remote(use_remote, op)
        return compare_fields(
            variable_name=_require(variable_name, "variable_name", op),
            data_path_a=_require(data_path_a, "data_path_a", op),
            data_path_b=_require(data_path_b, "data_path_b", op),
            grid_path=grid_path,
            session_id=session_id,
            result_name=result_name,
        )
    if op == "bias":
        _reject_unsupported_remote(use_remote, op)
        return calculate_bias(
            variable_name=_require(variable_name, "variable_name", op),
            data_path_a=_require(data_path_a, "data_path_a", op),
            data_path_b=_require(data_path_b, "data_path_b", op),
            grid_path=grid_path,
        )
    if op == "rmse":
        _reject_unsupported_remote(use_remote, op)
        return calculate_rmse(
            variable_name=_require(variable_name, "variable_name", op),
            data_path_a=_require(data_path_a, "data_path_a", op),
            data_path_b=_require(data_path_b, "data_path_b", op),
            grid_path=grid_path,
        )
    if op == "pattern_correlation":
        _reject_unsupported_remote(use_remote, op)
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
        _reject_unsupported_remote(use_remote, op)
        return calculate_temporal_mean(
            data_path=_require(data_path, "data_path", op),
            variable_name=_require(variable_name, "variable_name", op),
            groupby=groupby,
            session_id=session_id,
            result_name=result_name,
        )
    if op == "anomaly":
        _reject_unsupported_remote(use_remote, op)
        return calculate_anomaly(
            data_path=_require(data_path, "data_path", op),
            variable_name=_require(variable_name, "variable_name", op),
            baseline=baseline,
            session_id=session_id,
            result_name=result_name,
        )
    if op == "ensemble_mean":
        _reject_unsupported_remote(use_remote, op)
        return calculate_ensemble_mean(
            variable_name=_require(variable_name, "variable_name", op),
            data_paths=_require(data_paths, "data_paths", op),
            session_id=session_id,
            result_name=result_name,
        )
    if op == "ensemble_spread":
        _reject_unsupported_remote(use_remote, op)
        return calculate_ensemble_spread(
            variable_name=_require(variable_name, "variable_name", op),
            data_paths=_require(data_paths, "data_paths", op),
            session_id=session_id,
            result_name=result_name,
        )
    if op == "export":
        _reject_unsupported_remote(use_remote, op)
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
        _reject_unsupported_remote(use_remote, f"plot_dataset(plot_type={kind!r})")
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
