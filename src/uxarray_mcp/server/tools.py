"""The twelve MCP tools.

Each tool resolves its inputs (dataset handles -> paths), decides where to
run (locally, or on the Globus Compute endpoint that owns the path), calls
one named operation in :mod:`uxarray_mcp.core.ops`, persists any data
object it produced, evaluates the operation's preconditions and returns
the contract envelope. Docstrings are the tool descriptions clients see.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from uxarray_mcp.core import coverage as cov
from uxarray_mcp.core.mesh import is_healpix_spec, is_remote_uri
from uxarray_mcp.remote.config import load_config
from uxarray_mcp.server import state
from uxarray_mcp.server.contract import check, finish, guard, json_safe

# ----------------------------------------------------------------- plumbing


def _resolve(
    session_id: str | None,
    dataset_handle: str | None,
    grid_path: str | None,
    data_path: str | None,
) -> tuple[str | None, str | None]:
    """Explicit paths win; otherwise read them from the registered dataset."""
    if dataset_handle is None:
        return grid_path, data_path
    if session_id is None:
        raise ValueError(
            "dataset_handle needs session_id (from session(action='create'))."
        )
    dataset = state.get_session(session_id)["datasets"].get(dataset_handle)
    if dataset is None:
        raise FileNotFoundError(
            f"Dataset handle {dataset_handle!r} is not in session {session_id!r}."
        )
    return grid_path or dataset["grid_path"], data_path or dataset.get("data_path")


def _local_path(path: str | None) -> bool:
    return (
        path is None
        or is_healpix_spec(path)
        or is_remote_uri(path)
        or os.path.exists(path)
    )


def _run(
    op: str,
    kwargs: dict[str, Any],
    *,
    use_remote: bool,
    endpoint: str | None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Local by default; remote when asked, or when the path only exists on a cluster."""
    from uxarray_mcp.core import ops
    from uxarray_mcp.remote import executor

    paths = [v for k, v in kwargs.items() if k.endswith("path") and isinstance(v, str)]
    paths += [p for p in (kwargs.get("data_paths") or []) if isinstance(p, str)]
    route_path = paths[0] if paths else None
    if not use_remote and not endpoint:
        if all(_local_path(p) for p in paths):
            return ops.call(op, **kwargs)
        config = load_config()
        if not config.resolve_endpoint(path=route_path):
            missing = [p for p in paths if not _local_path(p)]
            raise FileNotFoundError(
                f"{missing[0]} does not exist locally and no endpoint claims that "
                "path prefix. Pass use_remote=True with endpoint=, or register one "
                "with `uxarray-mcp endpoints add`."
            )
    return executor.submit(
        op, kwargs, endpoint=endpoint, path=route_path, session_id=session_id
    )


def _persist(
    result: dict[str, Any], *, kind: str, name: str, session_id: str | None
) -> dict[str, Any]:
    """Store ``_payload`` as a result handle + NetCDF artifact; strip it from the reply."""
    payload = result.pop("_payload", None)
    if payload is None:
        return result
    record = state.persist_result(
        kind=kind,
        name=name,
        summary={k: v for k, v in result.items() if k not in ("warnings", "coverage")},
        session_id=session_id,
    )
    handle = record["result_handle"]
    try:
        if isinstance(payload, dict):
            path = state.write_json_artifact(json_safe(payload), handle)
        elif hasattr(payload, "data_vars"):
            path = state.write_dataset_artifact(payload, handle)
        elif hasattr(payload, "dims"):
            path = state.write_dataarray_artifact(payload, handle)
        else:  # a bare ux.Grid
            path = state.write_grid_artifact(payload, handle)
        record["artifact_path"] = path
        state.save_result(record)
        result["artifact_path"] = path
    except Exception as exc:
        result.setdefault("warnings", []).append(f"artifact not written: {exc}")
    result["result_handle"] = handle
    return result


def _codes(result: dict[str, Any]) -> list[str]:
    """Collect warning codes from every coverage block a core op may return."""
    codes = list(result.get("warning_codes") or [])
    for key, fn in (
        ("mesh_coverage", cov.mesh_coverage_warning_codes),
        ("profile_coverage", cov.profile_coverage_warning_codes),
        ("anomaly_coverage", cov.anomaly_coverage_warning_codes),
        ("temporal_coverage", cov.temporal_coverage_warning_codes),
    ):
        block = result.get(key)
        if isinstance(block, dict):
            codes += [c for c in fn(block) if c not in codes]
    for key in ("coverage", "source_coverage"):
        block = result.get(key)
        if isinstance(block, dict):
            codes += [c for c in block.get("warning_codes") or [] if c not in codes]
    result["warning_codes"] = codes
    return codes


def _zero_coverage_check(
    op: str, codes: list[str], repair: str
) -> list[dict[str, Any]]:
    zero = [c for c in codes if c.endswith("_ZERO")]
    return (
        [check(f"{op}_nonzero", not zero, ", ".join(zero) or "ok", repair)]
        if zero
        else []
    )


def _inputs(**kwargs: Any) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if k not in ("acknowledge",)}


def _emit(
    result: dict[str, Any],
    *,
    tool: str,
    inputs: dict[str, Any],
    checks: list[dict[str, Any]] | None = None,
    acknowledge: str | None = None,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if result.get("status") == "running":  # remote handle, not a result
        return json_safe(result)
    _codes(result)
    return finish(
        result,
        tool=tool,
        inputs=inputs,
        checks=checks,
        acknowledge=acknowledge,
        artifacts=artifacts,
    )


# ------------------------------------------------------------------- tools


@guard
def list_datasets(
    directory: str,
    recursive: bool = False,
    max_files: int = 200,
    use_remote: bool = False,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """List mesh and data files in a directory with header-only facts.

    Each file reports format (ugrid, mpas, scrip, exodus, esmf, icon), role
    (grid, data, grid+data), n_face, n_time, size_class and face-centered
    variable names, read from the file header without opening the mesh.
    Set use_remote=True for a directory on an HPC filesystem.
    """
    result = _run(
        "scan_directory",
        {"directory": directory, "recursive": recursive, "max_files": max_files},
        use_remote=use_remote,
        endpoint=endpoint,
    )
    return _emit(
        result,
        tool="list_datasets",
        inputs=_inputs(directory=directory, recursive=recursive),
    )


@guard
def inspect_dataset(
    grid_path: str,
    data_path: str | None = None,
    variable_name: str | None = None,
    validate: bool = True,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
) -> dict[str, Any]:
    """Describe a mesh and, when data_path is given, its variables and validity.

    Returns topology (n_face/n_node/n_edge, format), mesh_coverage
    (sphere_fraction, closed, euler_characteristic), header facts
    (size_class, n_time), the variables with their dims/units/stats, a
    NaN/Inf/fill validation summary, and a cost hint for plotting. grid_path
    may be a file, a remote URI, or healpix:<zoom>.
    """
    grid_path_r, data_path_r = _resolve(
        session_id, dataset_handle, grid_path, data_path
    )
    assert grid_path_r is not None
    facts = _run(
        "header_facts", {"path": grid_path_r}, use_remote=use_remote, endpoint=endpoint
    )
    if facts.get("status") == "running":
        return json_safe(facts)
    mesh = _run(
        "inspect_mesh",
        {"grid_path": grid_path_r},
        use_remote=use_remote,
        endpoint=endpoint,
    )
    if mesh.get("status") == "running":
        return json_safe(mesh)
    result: dict[str, Any] = {
        "grid_path": grid_path_r,
        "data_path": data_path_r,
        "format": facts.get("format"),
        "size_class": facts.get("size_class"),
        "size_bytes": facts.get("size_bytes"),
        **{k: v for k, v in mesh.items() if k not in ("_remote", "warnings")},
    }
    remote = mesh.get("_remote")
    n_face = result.get("n_face") or 0
    from uxarray_mcp.core.plotting import RASTERIZE_ABOVE_FACES

    result["plot_hint"] = (
        "rasterized" if n_face > RASTERIZE_ABOVE_FACES else "polygons"
    ) + f" ({n_face} faces; polygons above {RASTERIZE_ABOVE_FACES} are rasterized)"
    warnings: list[str] = list(mesh.get("warnings") or [])
    if data_path_r:
        variables = _run(
            "inspect_variable",
            {
                "grid_path": grid_path_r,
                "data_path": data_path_r,
                "variable_name": variable_name,
            },
            use_remote=use_remote,
            endpoint=endpoint,
        )
        result["variables"] = variables.get("variables", variables)
        warnings += variables.pop("warnings", []) or []
        if validate:
            validation = _run(
                "validate_dataset",
                {"grid_path": grid_path_r, "data_path": data_path_r},
                use_remote=use_remote,
                endpoint=endpoint,
            )
            validation.pop("_remote", None)
            result["validation"] = validation
            if validation.get("passed") is False:
                result.setdefault("warning_codes", []).append(
                    "DATASET_VALIDATION_FAILED"
                )
    if remote:
        result["_remote"] = remote
    if warnings:
        result["warnings"] = warnings
    return _emit(
        result,
        tool="inspect_dataset",
        inputs=_inputs(
            grid_path=grid_path, data_path=data_path, variable_name=variable_name
        ),
    )


@guard
def compute(
    statistic: str,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    data_paths: list[str] | None = None,
    sphere_radius: float | None = None,
    lat_spec: float | list[float] | None = None,
    lat_step: float | None = None,
    conservative: bool = False,
    center_lon: float | None = None,
    center_lat: float | None = None,
    outer_radius: float | None = None,
    radius_step: float | None = None,
    time_index: int = 0,
    level_index: int = 0,
    time_min: str | None = None,
    time_max: str | None = None,
    groupby: str | None = None,
    baseline: str = "temporal_mean",
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    acknowledge: str | None = None,
) -> dict[str, Any]:
    """Compute one statistic on a mesh or a face-centered variable.

    statistic: area (needs sphere_radius, e.g. 6371000 for Earth in metres,
    unless the grid declares one) | zonal_mean | zonal_anomaly |
    azimuthal_mean (center_lon/lat, outer_radius, radius_step in degrees) |
    temporal_mean (time_min/time_max as ISO labels, groupby) | anomaly |
    ensemble_mean | ensemble_spread (data_paths). lat_spec is one latitude
    or a list; with lat_step, [start, stop] becomes a regular range.
    A result whose bins miss the mesh, or an area in steradians, is refused
    with a repair; pass acknowledge to override.
    """
    grid_path, data_path = _resolve(session_id, dataset_handle, grid_path, data_path)
    if lat_step is not None:
        if lat_spec is None:
            start, stop = -90.0, 90.0
        elif isinstance(lat_spec, (int, float)):
            raise ValueError("lat_step needs lat_spec=[start, stop] or no lat_spec.")
        else:
            start, stop = float(lat_spec[0]), float(lat_spec[1])
        lat_spec = (start, stop, float(lat_step))  # type: ignore[assignment]
    args: dict[str, Any]
    stat = statistic.strip().lower()
    if stat == "area":
        args = {
            "grid_path": _need(grid_path, "grid_path"),
            "sphere_radius": sphere_radius,
        }
    elif stat in ("zonal_mean", "zonal_anomaly"):
        args = {
            "grid_path": _need(grid_path, "grid_path"),
            "data_path": _need(data_path, "data_path"),
            "variable_name": _need(variable_name, "variable_name"),
            "lat_spec": lat_spec,
            "conservative": conservative,
        }
        if stat == "zonal_mean":
            args.update(time_index=time_index, level_index=level_index)
    elif stat == "azimuthal_mean":
        args = {
            "grid_path": _need(grid_path, "grid_path"),
            "data_path": _need(data_path, "data_path"),
            "variable_name": _need(variable_name, "variable_name"),
            "center_lon": _need(center_lon, "center_lon"),
            "center_lat": _need(center_lat, "center_lat"),
            "outer_radius": _need(outer_radius, "outer_radius"),
            "radius_step": _need(radius_step, "radius_step"),
            "time_index": time_index,
            "level_index": level_index,
        }
    elif stat == "temporal_mean":
        args = {
            "data_path": _need(data_path, "data_path"),
            "variable_name": _need(variable_name, "variable_name"),
            "groupby": groupby,
            "time_min": time_min,
            "time_max": time_max,
        }
    elif stat == "anomaly":
        args = {
            "data_path": _need(data_path, "data_path"),
            "variable_name": _need(variable_name, "variable_name"),
            "baseline": baseline,
        }
    elif stat in ("ensemble_mean", "ensemble_spread"):
        args = {
            "variable_name": _need(variable_name, "variable_name"),
            "data_paths": _need(data_paths, "data_paths"),
        }
    else:
        raise ValueError(
            f"Unknown statistic {statistic!r}. One of: area, zonal_mean, zonal_anomaly, "
            "azimuthal_mean, temporal_mean, anomaly, ensemble_mean, ensemble_spread."
        )
    result = _run(
        stat, args, use_remote=use_remote, endpoint=endpoint, session_id=session_id
    )
    if result.get("status") == "running":
        return json_safe(result)
    result = _persist(
        result,
        kind=stat,
        name=f"{stat}:{variable_name or grid_path}",
        session_id=session_id,
    )
    codes = _codes(result)
    checks: list[dict[str, Any]] = []
    if stat == "area":
        basis = result.get("area_basis") or {}
        checks.append(
            check(
                "radius_known",
                bool(basis.get("scaled")),
                f"radius_source={basis.get('radius_source')}",
                "Pass sphere_radius (6371000 for Earth, metres); otherwise areas are steradians.",
            )
        )
    checks += _zero_coverage_check(
        stat,
        codes,
        "No bin or band intersects the data. Change lat_spec / center / radius / time range.",
    )
    if stat in ("ensemble_mean", "ensemble_spread"):
        ev = result.get("member_evidence") or {}
        if ev.get("units_consistent") is False:
            checks.append(
                check(
                    "ensemble_units",
                    False,
                    "members disagree on units",
                    "Use members with the same units.",
                )
            )
    return _emit(
        result,
        tool="compute",
        inputs=_inputs(
            statistic=stat,
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            data_paths=data_paths,
            sphere_radius=sphere_radius,
            lat_spec=lat_spec,
            time_min=time_min,
            time_max=time_max,
        ),
        checks=checks,
        acknowledge=acknowledge,
    )


@guard
def vector_calc(
    operation: str,
    grid_path: str,
    data_path: str,
    variable_name: str | None = None,
    u_variable: str | None = None,
    v_variable: str | None = None,
    sphere_radius: float | None = None,
    scale_by_radius: bool = True,
    time_index: int = 0,
    level_index: int = 0,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    acknowledge: str | None = None,
) -> dict[str, Any]:
    """Gradient of a scalar, or curl / divergence of a (u, v) vector field.

    operation: gradient (variable_name) | curl | divergence (u_variable,
    v_variable). Results are per metre / per second only when a sphere
    radius is known (grid attribute or sphere_radius=6371000); otherwise the
    call is refused rather than returning per-radian numbers. Curl and
    divergence also require the components to carry velocity units and a
    recognisable direction; pass acknowledge to override.
    """
    grid_path_r, data_path_r = _resolve(
        session_id, dataset_handle, grid_path, data_path
    )
    op = operation.strip().lower()
    args: dict[str, Any] = {
        "grid_path": grid_path_r,
        "data_path": data_path_r,
        "scale_by_radius": scale_by_radius,
        "time_index": time_index,
        "level_index": level_index,
        "sphere_radius": sphere_radius,
    }
    if op == "gradient":
        args["variable_name"] = _need(variable_name, "variable_name")
    elif op in ("curl", "divergence"):
        args["u_variable"] = _need(u_variable, "u_variable")
        args["v_variable"] = _need(v_variable, "v_variable")
    else:
        raise ValueError(
            f"Unknown operation {operation!r}. One of: gradient, curl, divergence."
        )
    result = _run(
        op, args, use_remote=use_remote, endpoint=endpoint, session_id=session_id
    )
    if result.get("status") == "running":
        return json_safe(result)
    status = result.get("scientific_status") or {}
    checks = [
        check(
            "radius_scaling",
            bool(status.get("physical_scaling_applied")),
            f"radius_source={(result.get('radius_basis') or {}).get('radius_source')}",
            "Pass sphere_radius=6371000 (metres) so the result has physical units.",
        )
    ]
    if op != "gradient":
        ev = result.get("component_evidence") or {}
        checks.append(
            check(
                "velocity_units",
                bool(ev.get("units_supported")),
                "component units",
                "Components need velocity-like units (m/s).",
            )
        )
        checks.append(
            check(
                "component_identity",
                bool(ev.get("component_identity_supported")),
                "direction from standard_name/long_name",
                "Name the eastward/northward components so u and v are identifiable.",
            )
        )
    for w in status.get("warnings") or []:
        result.setdefault("warnings", []).append(w)
    result["warning_codes"] = list(status.get("warning_codes") or [])
    result.pop("scientific_status", None)
    return _emit(
        result,
        tool="vector_calc",
        inputs=_inputs(
            operation=op,
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            u_variable=u_variable,
            v_variable=v_variable,
            sphere_radius=sphere_radius,
        ),
        checks=checks,
        acknowledge=acknowledge,
    )


@guard
def compare(
    variable_name: str,
    data_path_a: str,
    data_path_b: str,
    grid_path: str | None = None,
    metric: str | None = None,
    acknowledge: str | None = None,
) -> dict[str, Any]:
    """Compare one variable across two files on the same mesh.

    Returns area-weighted bias, rmse and pattern_correlation plus difference
    statistics (metric= narrows to one). Declared unit disagreement (K vs
    degC) is refused; undeclared units warn with UNITS_UNDECLARED. Runs
    locally.
    """
    result = _run(
        "compare_fields",
        {
            "variable_name": variable_name,
            "data_path_a": data_path_a,
            "data_path_b": data_path_b,
            "grid_path": grid_path,
            "metric": metric,
        },
        use_remote=False,
        endpoint=None,
    )
    result = _persist(
        result, kind="compare", name=f"compare:{variable_name}", session_id=None
    )
    units = result.get("units") or {}
    from uxarray_mcp.core.compare import normalize_units

    a, b = normalize_units(units.get("a")), normalize_units(units.get("b"))
    checks = [
        check(
            "units_comparable",
            not (a and b and a != b),
            f"a={units.get('a')!r} b={units.get('b')!r}",
            "Convert one file so both fields share units before differencing.",
        )
    ]
    return _emit(
        result,
        tool="compare",
        inputs=_inputs(
            variable_name=variable_name,
            data_path_a=data_path_a,
            data_path_b=data_path_b,
            grid_path=grid_path,
            metric=metric,
        ),
        checks=checks,
        acknowledge=acknowledge,
    )


@guard
def remap(
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    target_grid_path: str | None = None,
    target_lon: list[float] | None = None,
    target_lat: list[float] | None = None,
    method: str = "nearest_neighbor",
    remap_to: str = "faces",
    backend: str = "uxarray",
    yac_method: str | None = None,
    whole_dataset: bool = False,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    acknowledge: str | None = None,
) -> dict[str, Any]:
    """Remap a variable (or whole dataset) onto another mesh or a lon/lat grid.

    Give target_grid_path for mesh-to-mesh, or target_lon + target_lat (1-D
    lists) for a rectilinear target. method: nearest_neighbor,
    inverse_distance_weighted, bilinear (UXarray engine) or conservative,
    nnn, dnn, average (YAC, must be installed where the remap runs; only
    conservative preserves the integral). Reports source_coverage; a target
    the source does not reach at all is refused.
    """
    grid_path, data_path = _resolve(session_id, dataset_handle, grid_path, data_path)
    from uxarray_mcp.core.remap_backend import YAC_METHODS

    if yac_method is None and method.lower() in YAC_METHODS:
        yac_method, backend = method.lower(), "yac"
    base = {
        "grid_path": _need(grid_path, "grid_path"),
        "data_path": _need(data_path, "data_path"),
    }
    if target_lon is not None or target_lat is not None:
        op = "remap_to_rectilinear"
        args = {
            **base,
            "variable_name": _need(variable_name, "variable_name"),
            "target_lon": _need(target_lon, "target_lon"),
            "target_lat": _need(target_lat, "target_lat"),
            "backend": backend,
            "yac_method": yac_method,
        }
    elif whole_dataset:
        op = "regrid_dataset"
        args = {
            **base,
            "target_grid_path": _need(target_grid_path, "target_grid_path"),
            "variable_names": [variable_name] if variable_name else None,
            "method": method,
            "remap_to": remap_to,
            "backend": backend,
            "yac_method": yac_method,
        }
    else:
        op = "remap_variable"
        args = {
            **base,
            "variable_name": _need(variable_name, "variable_name"),
            "target_grid_path": _need(target_grid_path, "target_grid_path"),
            "method": method,
            "remap_to": remap_to,
            "backend": backend,
            "yac_method": yac_method,
        }
    result = _run(
        op, args, use_remote=use_remote, endpoint=endpoint, session_id=session_id
    )
    if result.get("status") == "running":
        return json_safe(result)
    result = _persist(
        result,
        kind=op,
        name=f"{op}:{variable_name or 'dataset'}",
        session_id=session_id,
    )
    codes = _codes(result)
    checks = _zero_coverage_check(
        op,
        codes,
        "No target point lies inside the source mesh; change target_grid_path or target_lon/target_lat.",
    )
    return _emit(
        result,
        tool="remap",
        inputs=_inputs(
            operation=op,
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            target_grid_path=target_grid_path,
            method=method,
            backend=backend,
        ),
        checks=checks,
        acknowledge=acknowledge,
    )


@guard
def subset(
    shape: str,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    lon_bounds: list[float] | None = None,
    lat_bounds: list[float] | None = None,
    polygon_lon_lat: list[list[float]] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    center_lon: float | None = None,
    center_lat: float | None = None,
    radius: float | None = None,
    k: int | None = None,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    acknowledge: str | None = None,
) -> dict[str, Any]:
    """Select part of a mesh (and optionally a variable on it); returns a result handle.

    shape: bbox (lon_bounds, lat_bounds; keeps faces whose whole footprint
    fits) | polygon (polygon_lon_lat; face centres inside) | cross_section
    (latitude or longitude line) | circle (center_lon/lat, radius degrees) |
    nearest (center_lon/lat, k faces). Longitudes are -180..180. An empty
    selection is refused with the mesh extent. The handle can be plotted
    or exported.
    """
    grid_path, data_path = _resolve(session_id, dataset_handle, grid_path, data_path)
    g = _need(grid_path, "grid_path")
    common = {"grid_path": g, "data_path": data_path, "variable_name": variable_name}
    kind = shape.strip().lower()
    if kind == "bbox":
        op, args = (
            "subset_bbox",
            {
                **common,
                "lon_bounds": _need(lon_bounds, "lon_bounds"),
                "lat_bounds": _need(lat_bounds, "lat_bounds"),
            },
        )
    elif kind == "polygon":
        op, args = (
            "subset_polygon",
            {**common, "polygon_lon_lat": _need(polygon_lon_lat, "polygon_lon_lat")},
        )
    elif kind == "cross_section":
        op, args = (
            "cross_section",
            {**common, "latitude": latitude, "longitude": longitude},
        )
    elif kind in ("circle", "nearest"):
        op = "subset_near_point"
        args = {
            **common,
            "selection": "bounding_circle" if kind == "circle" else "nearest_neighbor",
            "center_lon": _need(center_lon, "center_lon"),
            "center_lat": _need(center_lat, "center_lat"),
            "radius": radius,
            "k": k,
        }
    else:
        raise ValueError(
            f"Unknown shape {shape!r}. One of: bbox, polygon, cross_section, circle, nearest."
        )
    result = _run(
        op, args, use_remote=use_remote, endpoint=endpoint, session_id=session_id
    )
    if result.get("status") == "running":
        return json_safe(result)
    result = _persist(
        result, kind=op, name=f"{op}:{variable_name or g}", session_id=session_id
    )
    codes = _codes(result)
    checks = _zero_coverage_check(
        op,
        codes,
        "Nothing selected. Check -180..180 longitudes against the source_extent reported, or widen the region.",
    )
    return _emit(
        result,
        tool="subset",
        inputs=_inputs(
            shape=kind,
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            lon_bounds=lon_bounds,
            lat_bounds=lat_bounds,
            latitude=latitude,
            longitude=longitude,
        ),
        checks=checks,
        acknowledge=acknowledge,
    )


INLINE_IMAGE_LIMIT_BYTES = 256 * 1024


def plot(
    kind: str,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    result_handle: str | None = None,
    lon_bounds: list[float] | None = None,
    lat_bounds: list[float] | None = None,
    width: int = 800,
    height: int = 400,
    title: str | None = None,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    time_index: int = 0,
    level_index: int = 0,
    lat_spec: float | list[float] | None = None,
    conservative: bool = False,
    coastlines: bool = False,
    force_raster: bool = False,
    use_remote: bool = False,
    endpoint: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
) -> list[dict[str, Any]]:
    """Render a PNG: kind = mesh (wireframe) | field (variable) | profile (zonal mean).

    Meshes above 200k faces are rasterized to the requested pixel size
    instead of drawn polygon by polygon; the reply says which
    (render_mode). lon_bounds/lat_bounds crop mesh and field plots;
    coastlines=True draws Natural Earth features behind a mesh (local
    only). result_handle plots a stored subset instead of a file. Returns an
    image (inline when small, otherwise a resource link to the stored PNG)
    plus a JSON text block with render metadata.
    """
    try:
        return _plot(
            kind,
            grid_path,
            data_path,
            variable_name,
            result_handle,
            lon_bounds,
            lat_bounds,
            width,
            height,
            title,
            cmap,
            vmin,
            vmax,
            time_index,
            level_index,
            lat_spec,
            conservative,
            coastlines,
            force_raster,
            use_remote,
            endpoint,
            session_id,
            dataset_handle,
        )
    except Exception as exc:
        from uxarray_mcp.remote.executor import RemoteError

        payload = (
            exc.to_dict()
            if isinstance(exc, RemoteError)
            else {
                "status": "error",
                "error_code": type(exc).__name__,
                "message": str(exc),
            }
        )
        return [{"type": "text", "text": json.dumps(payload)}]


def _plot(
    kind: str,
    grid_path: str | None,
    data_path: str | None,
    variable_name: str | None,
    result_handle: str | None,
    lon_bounds: Any,
    lat_bounds: Any,
    width: int,
    height: int,
    title: str | None,
    cmap: str,
    vmin: Any,
    vmax: Any,
    time_index: int,
    level_index: int,
    lat_spec: Any,
    conservative: bool,
    coastlines: bool,
    force_raster: bool,
    use_remote: bool,
    endpoint: str | None,
    session_id: str | None,
    dataset_handle: str | None,
) -> list[dict[str, Any]]:
    grid_path, data_path = _resolve(session_id, dataset_handle, grid_path, data_path)
    if result_handle:
        record = state.get_result(result_handle)
        artifact = record.get("artifact_path")
        if not artifact:
            raise FileNotFoundError(
                f"Result {result_handle!r} has no stored artifact to plot."
            )
        grid_path = artifact
        if (
            record.get("kind", "").startswith("remap")
            or record.get("kind") == "temporal_mean"
        ):
            data_path = artifact
    k = kind.strip().lower()
    g = _need(grid_path, "grid_path")
    if k == "mesh":
        op, args = (
            "plot_mesh",
            {
                "grid_path": g,
                "width": width,
                "height": height,
                "title": title,
                "lon_bounds": lon_bounds,
                "lat_bounds": lat_bounds,
                "coastlines": coastlines,
                "force_raster": force_raster,
            },
        )
    elif k == "field":
        op, args = (
            "plot_field",
            {
                "grid_path": g,
                "data_path": _need(data_path, "data_path"),
                "variable_name": _need(variable_name, "variable_name"),
                "width": width,
                "height": height,
                "cmap": cmap,
                "vmin": vmin,
                "vmax": vmax,
                "title": title,
                "time_index": time_index,
                "level_index": level_index,
                "force_raster": force_raster,
            },
        )
    elif k == "profile":
        op, args = (
            "plot_profile",
            {
                "grid_path": g,
                "data_path": _need(data_path, "data_path"),
                "variable_name": _need(variable_name, "variable_name"),
                "width": width,
                "height": height,
                "lat_spec": lat_spec,
                "conservative": conservative,
                "time_index": time_index,
                "level_index": level_index,
                "title": title,
            },
        )
    else:
        raise ValueError(f"Unknown kind {kind!r}. One of: mesh, field, profile.")
    if coastlines and k == "mesh" and (use_remote or endpoint):
        raise ValueError(
            "coastlines=True renders locally only; drop it or run without use_remote."
        )
    result = _run(
        op, args, use_remote=use_remote, endpoint=endpoint, session_id=session_id
    )
    if result.get("status") == "running":
        return [{"type": "text", "text": json.dumps(json_safe(result))}]
    png: bytes = result.pop("png")
    stored = _store_png(png, k)
    meta = _emit(
        result,
        tool="plot",
        inputs=_inputs(
            kind=k,
            grid_path=grid_path,
            data_path=data_path,
            variable_name=variable_name,
            result_handle=result_handle,
            lon_bounds=lon_bounds,
            lat_bounds=lat_bounds,
            width=width,
            height=height,
        ),
        artifacts=[stored] if stored.get("uri") else None,
    )
    meta["image_size_bytes"] = len(png)
    blocks: list[dict[str, Any]] = []
    if stored.get("uri") and len(png) >= INLINE_IMAGE_LIMIT_BYTES:
        blocks.append(
            {
                "type": "resource_link",
                "uri": stored["uri"],
                "name": stored["name"],
                "mimeType": "image/png",
            }
        )
        meta["image_delivery"] = "resource_link"
    else:
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(png).decode("ascii"),
                },
            }
        )
        meta["image_delivery"] = "inline"
    if stored.get("path"):
        meta["image_path"] = stored["path"]
    blocks.append({"type": "text", "text": json.dumps(meta)})
    return blocks


def _store_png(png: bytes, kind: str) -> dict[str, Any]:
    try:
        result_id = state._new_id("plot")
        path = state._artifacts_dir() / f"{result_id}.png"
        path.write_bytes(png)
    except Exception as exc:
        return {"stored": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "type": "plot",
        "kind": kind,
        "uri": path.as_uri(),
        "name": path.name,
        "path": str(path),
        "size": len(png),
    }


@guard
def export(
    output_path: str,
    format: str = "netcdf",
    result_handle: str | None = None,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
) -> dict[str, Any]:
    """Write a stored result (result_handle) or a file's variable to NetCDF or CSV.

    Reports export_fidelity: attributes, fill values or coordinates that the
    format could not carry are named rather than dropped silently.
    """
    import xarray as xr

    from uxarray_mcp.core import export as core_export

    grid_path, data_path = _resolve(session_id, dataset_handle, grid_path, data_path)
    if result_handle:
        record = state.get_result(result_handle)
        artifact = record.get("artifact_path")
        if not artifact:
            raise FileNotFoundError(
                f"Result {result_handle!r} has no artifact to export."
            )
        obj: Any = xr.open_dataset(artifact)
        if variable_name:
            obj = obj[variable_name]
        result = (
            core_export.export_dataset(obj, output_path, format=format)
            if hasattr(obj, "data_vars")
            else core_export.export_dataarray(obj, output_path, format=format)
        )
    else:
        from uxarray_mcp.core.fields import load_face_variable

        _, uxda, _ = load_face_variable(
            _need(grid_path, "grid_path"),
            _need(data_path, "data_path"),
            _need(variable_name, "variable_name"),
        )
        result = core_export.export_dataarray(uxda, output_path, format=format)
    return _emit(
        result,
        tool="export",
        inputs=_inputs(
            output_path=output_path,
            format=format,
            result_handle=result_handle,
            variable_name=variable_name,
        ),
    )


@guard
def session(
    action: str,
    session_id: str | None = None,
    name: str | None = None,
    grid_path: str | None = None,
    data_path: str | None = None,
    dataset_handle: str | None = None,
    result_handle: str | None = None,
) -> dict[str, Any]:
    """Session state: create | register (grid_path [+ data_path] -> dataset_handle) | get | result | reset.

    Register a dataset once, then pass session_id + dataset_handle to the
    other tools instead of repeating paths. Subsets, remaps and temporal
    means return result_handle values; action=result shows one.
    """
    act = action.strip().lower()
    if act == "create":
        out: dict[str, Any] = state.create_session(name=name)
    elif act == "register":
        out = state.register_dataset(
            _need(session_id, "session_id"),
            grid_path=_need(grid_path, "grid_path"),
            data_path=data_path,
            name=name,
        )
    elif act == "get":
        out = state.get_session(_need(session_id, "session_id"))
    elif act == "result":
        out = state.get_result(_need(result_handle, "result_handle"))
    elif act == "reset":
        out = state.reset_session(_need(session_id, "session_id"))
    else:
        raise ValueError(
            f"Unknown action {action!r}. One of: create, register, get, result, reset."
        )
    return _emit(
        dict(out),
        tool="session",
        inputs=_inputs(
            action=act, session_id=session_id, dataset_handle=dataset_handle
        ),
    )


@guard
def endpoint(
    action: str = "status",
    endpoint: str | None = None,
    path: str | None = None,
    probe_timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Globus Compute endpoints: status | validate | probe_path | check_yac.

    status lists configured endpoints with manager state (registered,
    offline) and, for the named one, runs a worker probe reporting node,
    Python/uxarray versions and round-trip seconds (a scheduler-backed
    endpoint can take a minute to answer cold). validate adds a header read
    of `path` on the worker. probe_path reads a file's header remotely.
    check_yac reports whether conservative remapping is available there.
    """
    from uxarray_mcp.remote import health

    config = load_config()
    act = action.strip().lower()
    out: dict[str, Any] = {
        "endpoints": health.all_manager_statuses(config),
        "default_endpoint": config.default_endpoint,
    }
    target = endpoint or config.default_endpoint
    if act == "status" and target:
        out["worker"] = health.worker_probe(
            target, timeout_seconds=probe_timeout_seconds
        )
    elif act in ("validate", "probe_path"):
        if act == "validate":
            out["worker"] = health.worker_probe(
                target, timeout_seconds=probe_timeout_seconds
            )
        if path:
            out["path"] = _run(
                "header_facts", {"path": path}, use_remote=True, endpoint=target
            )
        out["passed"] = out.get("worker", {}).get(
            "status", "active"
        ) == "active" and "error" not in out.get("path", {})
    elif act == "check_yac":
        probe = health.worker_probe(target, timeout_seconds=probe_timeout_seconds)
        out["worker"] = probe
        out["conservative_remap_available"] = bool(probe.get("yac_available"))
    elif act != "status":
        raise ValueError(
            f"Unknown action {action!r}. One of: status, validate, probe_path, check_yac."
        )
    return _emit(
        out, tool="endpoint", inputs=_inputs(action=act, endpoint=endpoint, path=path)
    )


@guard
def get_operation(operation_id: str, wait_seconds: float = 0) -> dict[str, Any]:
    """Collect a remote operation that outlived its call, or read its record.

    A tool that returns status="running" names an operation_id; call this
    (optionally waiting up to wait_seconds) to get the finished result.
    """
    from uxarray_mcp.remote import executor

    result = executor.redeem(operation_id, wait_seconds=wait_seconds)
    if result.get("status") == "running" or "operation" in result:
        return json_safe(result)
    return _emit(
        result, tool="get_operation", inputs=_inputs(operation_id=operation_id)
    )


def _need(value: Any, name: str) -> Any:
    if value is None:
        raise ValueError(f"{name} is required for this call.")
    return value
