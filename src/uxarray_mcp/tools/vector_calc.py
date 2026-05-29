"""Vector calculus and azimuthal mean tools for unstructured meshes."""

from __future__ import annotations

from typing import Any, Dict, Optional

import uxarray as ux

from uxarray_mcp.domain.vector_calc import (
    compute_azimuthal_mean,
    compute_curl,
    compute_divergence,
    compute_gradient,
)
from uxarray_mcp.provenance import attach_provenance


def calculate_gradient(
    grid_path: str,
    data_path: str,
    variable_name: str,
) -> Dict[str, Any]:
    """Compute the spatial gradient of a face-centered scalar field.

    Uses UXarray's Green-Gauss finite-volume gradient to compute the zonal
    (∂/∂x) and meridional (∂/∂y) components of the gradient on the
    unstructured mesh.

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file.
    data_path : str
        Path to the data file containing the variable.
    variable_name : str
        Name of the face-centered scalar variable.

    Returns
    -------
    dict
        Dictionary with keys ``components`` (list of output variable names),
        ``component_stats`` (min/max/mean for each component), ``n_face``,
        and ``interpretation``.

    Examples
    --------
    >>> calculate_gradient("grid.nc", "data.nc", "temperature")
    {"components": ["d_temperature_d_x", "d_temperature_d_y"],
     "component_stats": {...}, "n_face": 655362, ...}
    """
    uxds = ux.open_dataset(grid_path, data_path)
    result = compute_gradient(uxds, variable_name)
    return attach_provenance(
        result,
        tool="calculate_gradient",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
        },
    )


def calculate_curl(
    grid_path: str,
    data_path: str,
    u_variable: str,
    v_variable: str,
) -> Dict[str, Any]:
    """Compute the curl (relative vorticity) of a 2-D wind or vector field.

    The curl is the vertical component of ∇ × (u, v):

        ζ = ∂v/∂x − ∂u/∂y

    For atmospheric wind fields (u = zonal wind, v = meridional wind) this is
    the **relative vorticity** — a key diagnostic for identifying cyclones,
    anticyclones, and jet-stream structure on unstructured meshes.

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file.
    data_path : str
        Path to the data file containing both vector components.
    u_variable : str
        Zonal (east–west) component — e.g. ``"uReconstructZonal"``.
    v_variable : str
        Meridional (north–south) component — e.g. ``"uReconstructMeridional"``.

    Returns
    -------
    dict
        Dictionary with keys ``u_variable``, ``v_variable``,
        ``interpretation``, ``n_face``, and ``stats``
        (min, max, mean, std of the vorticity field).

    Examples
    --------
    >>> calculate_curl("grid.nc", "data.nc", "u", "v")
    {"interpretation": "relative vorticity ζ = ∂v/∂x − ∂u/∂y",
     "stats": {"min": -2.3e-4, "max": 1.8e-4, "mean": 3.1e-7, "std": 4.2e-5},
     "n_face": 655362, ...}
    """
    uxds = ux.open_dataset(grid_path, data_path)
    result = compute_curl(uxds, u_variable, v_variable)
    return attach_provenance(
        result,
        tool="calculate_curl",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "u_variable": u_variable,
            "v_variable": v_variable,
        },
    )


def calculate_divergence(
    grid_path: str,
    data_path: str,
    u_variable: str,
    v_variable: str,
) -> Dict[str, Any]:
    """Compute the horizontal divergence of a 2-D vector field.

    Divergence = ∂u/∂x + ∂v/∂y

    Positive divergence (outflow) is associated with sinking motion; negative
    divergence (convergence) drives rising motion and convection. Together with
    vorticity (curl), divergence characterises the full kinematic structure of
    atmospheric flow.

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file.
    data_path : str
        Path to the data file containing both vector components.
    u_variable : str
        Zonal (east–west) component.
    v_variable : str
        Meridional (north–south) component.

    Returns
    -------
    dict
        Dictionary with keys ``u_variable``, ``v_variable``,
        ``interpretation``, ``n_face``, and ``stats``
        (min, max, mean, std of the divergence field).

    Examples
    --------
    >>> calculate_divergence("grid.nc", "data.nc", "u", "v")
    {"interpretation": "horizontal divergence ∂u/∂x + ∂v/∂y",
     "stats": {"min": -1.1e-5, "max": 9.8e-6, "mean": -2.1e-9, "std": 8.3e-7},
     "n_face": 655362, ...}
    """
    uxds = ux.open_dataset(grid_path, data_path)
    result = compute_divergence(uxds, u_variable, v_variable)
    return attach_provenance(
        result,
        tool="calculate_divergence",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "u_variable": u_variable,
            "v_variable": v_variable,
        },
    )


def calculate_azimuthal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    center_lon: float,
    center_lat: float,
    outer_radius: float,
    radius_step: float,
) -> Dict[str, Any]:
    """Compute the azimuthal (radial) mean of a variable around a centre point.

    Averages the field along concentric circles of constant great-circle
    distance from the centre, producing a radial profile. Useful for:

    - **Tropical cyclone structure** — radial profiles of wind, pressure, SST
    - **Polar vortex analysis** — radial decay from the pole
    - **Storm-centred composites** — any feature with approximate radial symmetry

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file.
    data_path : str
        Path to the data file.
    variable_name : str
        Face-centered variable to average.
    center_lon : float
        Longitude of the centre point in degrees (−180 to 180 or 0 to 360).
    center_lat : float
        Latitude of the centre point in degrees (−90 to 90).
    outer_radius : float
        Maximum radius in great-circle degrees.
    radius_step : float
        Radial bin width in great-circle degrees.

    Returns
    -------
    dict
        Dictionary with keys ``variable_name``, ``center``,
        ``outer_radius_deg``, ``radius_step_deg``, ``radii_deg`` (list of
        bin centres), ``azimuthal_mean_values``, and ``n_face``.

    Examples
    --------
    >>> calculate_azimuthal_mean("grid.nc", "data.nc", "pressure",
    ...     center_lon=-90.0, center_lat=25.0,
    ...     outer_radius=10.0, radius_step=0.5)
    {"radii_deg": [0.0, 0.5, 1.0, ...], "azimuthal_mean_values": [...], ...}
    """
    uxds = ux.open_dataset(grid_path, data_path)
    result = compute_azimuthal_mean(
        uxds, variable_name, center_lon, center_lat, outer_radius, radius_step
    )
    return attach_provenance(
        result,
        tool="calculate_azimuthal_mean",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "center_lon": center_lon,
            "center_lat": center_lat,
            "outer_radius": outer_radius,
            "radius_step": radius_step,
        },
    )
