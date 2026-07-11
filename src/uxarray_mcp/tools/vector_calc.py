"""Vector calculus tools with optional HPC remote execution."""

from __future__ import annotations

from typing import Any, Dict, Optional

from uxarray_mcp.domain.mesh import load_dataset
from uxarray_mcp.state import OperationTracker

from .remote_tools import (
    _endpoint_manager_is_up,
    _path_is_locally_reachable,
    _run_sync,
)


def _run_vector_calc(
    *,
    tool_name: str,
    use_remote: bool,
    endpoint: str | None,
    grid_path: str,
    session_id: str | None,
    local_call,
    remote_call,
) -> Dict[str, Any]:
    """Dispatch helper for vector calculus tools.

    Mirrors _run_with_optional_hpc but vector calc tools take grid_path +
    data_path rather than a single file_path, and remote dispatch goes through
    the agent's dedicated vector-calc methods.
    """
    tracker = OperationTracker(tool_name, session_id=session_id)

    if not use_remote:
        tracker.stage("running", f"Running {tool_name} locally.")
        result = local_call()
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.succeed(f"{tool_name} completed locally.")
        return result

    from uxarray_mcp.remote.agent import get_agent

    agent = get_agent(endpoint=endpoint, path=grid_path)
    if not agent.config.endpoint_id:
        if not _path_is_locally_reachable(grid_path):
            msg = (
                f"{tool_name}: use_remote=True but no HPC endpoint is configured "
                f"and the path {grid_path!r} does not exist locally."
            )
            tracker.fail(msg)
            raise RuntimeError(msg)
        tracker.stage("fallback", "No endpoint configured; running locally.")
        result = local_call()
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.succeed(f"{tool_name} completed locally (no endpoint).")
        return result

    ready, reason = _endpoint_manager_is_up(agent)
    if not ready:
        if not _path_is_locally_reachable(grid_path):
            msg = (
                f"{tool_name}: HPC endpoint not ready ({reason}) and "
                f"{grid_path!r} does not exist locally."
            )
            tracker.fail(msg)
            raise RuntimeError(msg)
        tracker.stage("fallback", "Endpoint not ready; running locally.")
        result = local_call()
        result["_provenance"]["warnings"].append(
            f"HPC endpoint not ready ({reason}); ran locally."
        )
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.succeed(f"{tool_name} completed locally (endpoint not ready).")
        return result

    tracker.stage("submitted", f"Submitting {tool_name} to HPC endpoint.")
    result = remote_call(agent)
    result["_provenance"]["operation_id"] = tracker.operation_id
    tracker.succeed(f"{tool_name} completed with remote execution.")
    return result


def calculate_gradient(
    grid_path: str,
    data_path: str,
    variable_name: str,
    scale_by_radius: bool = False,
    use_remote: bool = False,
    endpoint: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the spatial gradient of a face-centered scalar field.

    Uses UXarray's Green-Gauss finite-volume gradient to compute the zonal
    (d/dx) and meridional (d/dy) components on the unstructured mesh.

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file (local or HPC filesystem).
    data_path : str
        Path to the data file containing the variable.
    variable_name : str
        Name of the face-centered scalar variable.
    scale_by_radius : bool
        If True, divide unit-sphere derivatives by ``uxgrid.sphere_radius`` for
        physical units (requires a grid with ``sphere_radius``). Default False
        preserves the unit-sphere result. Local execution passes this to the
        pinned UXarray directly. The remote worker, which may run an older
        UXarray, applies it capability-safely and falls back to the unit sphere
        if unsupported; the result reports the ``scale_by_radius`` actually
        applied.
    use_remote : bool
        If True and an HPC endpoint is configured, execute remotely.
    endpoint : str, optional
        Named endpoint to target when several are configured.
    session_id : str, optional
        Session to track this operation under.

    Returns
    -------
    dict
        Dictionary with keys ``components`` (list of output variable names),
        ``component_stats`` (min/max/mean per component), ``n_face``,
        ``interpretation``, and ``_provenance``.

    Examples
    --------
    >>> calculate_gradient("grid.nc", "data.nc", "temperature")
    {"components": ["d_temperature_d_x", "d_temperature_d_y"], ...}
    """

    from uxarray_mcp.domain.vector_calc import compute_gradient
    from uxarray_mcp.provenance import attach_provenance

    inputs = {
        "grid_path": grid_path,
        "data_path": data_path,
        "variable_name": variable_name,
        "scale_by_radius": scale_by_radius,
    }

    def _local():
        uxds = load_dataset(grid_path, data_path)
        return attach_provenance(
            compute_gradient(uxds, variable_name, scale_by_radius=scale_by_radius),
            tool="calculate_gradient",
            inputs=inputs,
        )

    return _run_vector_calc(
        tool_name="calculate_gradient",
        use_remote=use_remote,
        endpoint=endpoint,
        grid_path=grid_path,
        session_id=session_id,
        local_call=_local,
        remote_call=lambda agent: _run_sync(
            lambda: agent.calculate_gradient_remote(
                grid_path, data_path, variable_name, scale_by_radius
            )
        ),
    )


def calculate_curl(
    grid_path: str,
    data_path: str,
    u_variable: str,
    v_variable: str,
    scale_by_radius: bool = False,
    use_remote: bool = False,
    endpoint: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the curl (relative vorticity) of a 2-D wind or vector field.

    The curl is the vertical component of the cross product:

        zeta = dv/dx - du/dy

    For atmospheric wind fields (u = zonal, v = meridional) this is the
    **relative vorticity** — the primary diagnostic for cyclones,
    anticyclones, and jet-stream structure on unstructured meshes.

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file (local or HPC filesystem).
    data_path : str
        Path to the data file containing both vector components.
    u_variable : str
        Zonal (east-west) component, e.g. ``"uReconstructZonal"``.
    v_variable : str
        Meridional (north-south) component, e.g. ``"uReconstructMeridional"``.
    scale_by_radius : bool
        If True, divide the unit-sphere result by ``uxgrid.sphere_radius`` for
        physical units (requires a grid with ``sphere_radius``). Default False
        preserves the unit-sphere result. Local execution passes this to the
        pinned UXarray directly. The remote worker, which may run an older
        UXarray, applies it capability-safely and falls back to the unit sphere
        if unsupported; the result reports the ``scale_by_radius`` actually
        applied.
    use_remote : bool
        If True and an HPC endpoint is configured, execute remotely.
    endpoint : str, optional
        Named endpoint to target when several are configured.
    session_id : str, optional
        Session to track this operation under.

    Returns
    -------
    dict
        Dictionary with keys ``u_variable``, ``v_variable``,
        ``interpretation``, ``n_face``, ``stats`` (min/max/mean/std),
        and ``_provenance``.

    Examples
    --------
    >>> calculate_curl("grid.nc", "data.nc", "u", "v")
    {"stats": {"min": -2.3e-4, "max": 1.8e-4, ...}, ...}

    >>> calculate_curl("/hpc/grid.nc", "/hpc/data.nc", "u", "v", use_remote=True)
    {"stats": {...}, "_provenance": {"execution_venue": "hpc:...", ...}}
    """

    from uxarray_mcp.domain.vector_calc import compute_curl
    from uxarray_mcp.provenance import attach_provenance

    inputs = {
        "grid_path": grid_path,
        "data_path": data_path,
        "u_variable": u_variable,
        "v_variable": v_variable,
        "scale_by_radius": scale_by_radius,
    }

    def _local():
        uxds = load_dataset(grid_path, data_path)
        result = compute_curl(
            uxds, u_variable, v_variable, scale_by_radius=scale_by_radius
        )
        return attach_provenance(
            result,
            tool="calculate_curl",
            inputs=inputs,
            warnings=result.get("component_warnings") or None,
        )

    return _run_vector_calc(
        tool_name="calculate_curl",
        use_remote=use_remote,
        endpoint=endpoint,
        grid_path=grid_path,
        session_id=session_id,
        local_call=_local,
        remote_call=lambda agent: _run_sync(
            lambda: agent.calculate_curl_remote(
                grid_path, data_path, u_variable, v_variable, scale_by_radius
            )
        ),
    )


def calculate_divergence(
    grid_path: str,
    data_path: str,
    u_variable: str,
    v_variable: str,
    use_remote: bool = False,
    endpoint: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the horizontal divergence of a 2-D vector field.

    divergence = du/dx + dv/dy

    Negative divergence (convergence) drives rising motion and convection.
    Positive divergence indicates sinking motion. Together with vorticity
    (curl), divergence characterises the full kinematic structure of
    atmospheric flow.

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file (local or HPC filesystem).
    data_path : str
        Path to the data file containing both vector components.
    u_variable : str
        Zonal (east-west) component.
    v_variable : str
        Meridional (north-south) component.
    use_remote : bool
        If True and an HPC endpoint is configured, execute remotely.
    endpoint : str, optional
        Named endpoint to target when several are configured.
    session_id : str, optional
        Session to track this operation under.

    Returns
    -------
    dict
        Dictionary with keys ``u_variable``, ``v_variable``,
        ``interpretation``, ``n_face``, ``stats`` (min/max/mean/std),
        and ``_provenance``.

    Examples
    --------
    >>> calculate_divergence(
    ...     "grid.nc", "data.nc", "u", "v", use_remote=True, endpoint="improv"
    ... )
    {"interpretation": "horizontal divergence du/dx + dv/dy", ...}
    """

    from uxarray_mcp.domain.vector_calc import compute_divergence
    from uxarray_mcp.provenance import attach_provenance

    inputs = {
        "grid_path": grid_path,
        "data_path": data_path,
        "u_variable": u_variable,
        "v_variable": v_variable,
    }

    def _local():
        uxds = load_dataset(grid_path, data_path)
        result = compute_divergence(uxds, u_variable, v_variable)
        return attach_provenance(
            result,
            tool="calculate_divergence",
            inputs=inputs,
            warnings=result.get("component_warnings") or None,
        )

    return _run_vector_calc(
        tool_name="calculate_divergence",
        use_remote=use_remote,
        endpoint=endpoint,
        grid_path=grid_path,
        session_id=session_id,
        local_call=_local,
        remote_call=lambda agent: _run_sync(
            lambda: agent.calculate_divergence_remote(
                grid_path, data_path, u_variable, v_variable
            )
        ),
    )


def calculate_azimuthal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    center_lon: float,
    center_lat: float,
    outer_radius: float,
    radius_step: float,
    use_remote: bool = False,
    endpoint: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the azimuthal (radial) mean of a variable around a centre point.

    Averages the field along concentric circles of constant great-circle
    distance from the centre, producing a radial profile. Useful for:

    - Tropical cyclone structure — radial profiles of wind, pressure, SST
    - Polar vortex analysis — radial decay from the pole
    - Storm-centred composites — any feature with approximate radial symmetry

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file (local or HPC filesystem).
    data_path : str
        Path to the data file.
    variable_name : str
        Face-centered variable to average.
    center_lon : float
        Longitude of the centre point in degrees.
    center_lat : float
        Latitude of the centre point in degrees.
    outer_radius : float
        Maximum radius in great-circle degrees.
    radius_step : float
        Radial bin width in great-circle degrees.
    use_remote : bool
        If True and an HPC endpoint is configured, execute remotely.
    endpoint : str, optional
        Named endpoint to target when several are configured.
    session_id : str, optional
        Session to track this operation under.

    Returns
    -------
    dict
        Dictionary with keys ``variable_name``, ``center``,
        ``outer_radius_deg``, ``radius_step_deg``, ``radii_deg``,
        ``azimuthal_mean_values``, ``n_face``, and ``_provenance``.

    Examples
    --------
    >>> calculate_azimuthal_mean(
    ...     "grid.nc",
    ...     "data.nc",
    ...     "pressure",
    ...     center_lon=-90.0,
    ...     center_lat=25.0,
    ...     outer_radius=10.0,
    ...     radius_step=0.5,
    ... )
    {"radii_deg": [0.0, 0.5, 1.0, ...], "azimuthal_mean_values": [...], ...}
    """

    from uxarray_mcp.domain.vector_calc import compute_azimuthal_mean
    from uxarray_mcp.provenance import attach_provenance

    inputs = {
        "grid_path": grid_path,
        "data_path": data_path,
        "variable_name": variable_name,
        "center_lon": center_lon,
        "center_lat": center_lat,
        "outer_radius": outer_radius,
        "radius_step": radius_step,
    }

    def _local():
        uxds = load_dataset(grid_path, data_path)
        return attach_provenance(
            compute_azimuthal_mean(
                uxds, variable_name, center_lon, center_lat, outer_radius, radius_step
            ),
            tool="calculate_azimuthal_mean",
            inputs=inputs,
        )

    return _run_vector_calc(
        tool_name="calculate_azimuthal_mean",
        use_remote=use_remote,
        endpoint=endpoint,
        grid_path=grid_path,
        session_id=session_id,
        local_call=_local,
        remote_call=lambda agent: _run_sync(
            lambda: agent.calculate_azimuthal_mean_remote(
                grid_path,
                data_path,
                variable_name,
                center_lon,
                center_lat,
                outer_radius,
                radius_step,
            )
        ),
    )
