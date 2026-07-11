"""Vector calculus and azimuthal averaging on unstructured meshes."""

from __future__ import annotations

from typing import Any

# Units that look like a genuine 2-D vector (velocity/flux) component. Used only
# to raise a soft, non-blocking warning when curl/divergence inputs do not look
# like real vector components — the math is still valid, but the result is only
# physically meaningful for true vector fields.
_VELOCITY_LIKE_UNIT_HINTS = (
    "m/s",
    "m s-1",
    "m s^-1",
    "meter/second",
    "meters/second",
    "cm/s",
    "km/h",
    "kg/m2/s",
    "kg m-2 s-1",
    "pa/s",
    "n/m2",
)


def _vector_component_warnings(
    u_variable: str,
    v_variable: str,
    u: Any,
    v: Any,
    operation: str,
) -> list[str]:
    """Return soft warnings when (u, v) do not look like real vector components.

    curl and divergence are only physically meaningful when ``u`` and ``v`` are
    the two horizontal components of a genuine vector field (e.g. eastward and
    northward velocity). The underlying finite-volume operators will happily
    compute a number from *any* two scalar fields, so this guardrail flags the
    common misuse patterns without blocking the computation:

    1. ``u`` and ``v`` are the same variable (a scalar used as both components).
    2. Neither component carries a velocity/flux-like ``units`` attribute.

    Warnings are attached to the result so the caller — and any downstream
    scientist — can see that the inputs were suspicious.
    """
    warnings: list[str] = []

    if u_variable == v_variable:
        warnings.append(
            f"{operation}: u_variable and v_variable are the same field "
            f"('{u_variable}'). {operation} is only physically meaningful for a "
            "true 2-D vector field (distinct eastward/northward components); "
            "the result here is a mathematical artifact, not a physical "
            f"{operation}."
        )

    def _unit(var: Any) -> str:
        attrs = getattr(var, "attrs", {}) or {}
        return str(attrs.get("units", "")).strip().lower()

    u_unit, v_unit = _unit(u), _unit(v)

    def _looks_velocity(unit: str) -> bool:
        return any(hint in unit for hint in _VELOCITY_LIKE_UNIT_HINTS)

    if not (_looks_velocity(u_unit) or _looks_velocity(v_unit)):
        seen = ", ".join(
            f"{name}='{unit or 'unset'}'"
            for name, unit in ((u_variable, u_unit), (v_variable, v_unit))
        )
        warnings.append(
            f"{operation}: neither component has a velocity/flux-like 'units' "
            f"attribute ({seen}). Verify that '{u_variable}' and '{v_variable}' "
            "are genuine vector components (e.g. m/s) before interpreting the "
            f"{operation} physically."
        )

    return warnings


def compute_gradient(
    uxds: Any, variable_name: str, scale_by_radius: bool = False
) -> dict:
    """Compute the gradient of a face-centered scalar field.

    Uses UXarray's Green-Gauss finite-volume gradient, which forms a closed
    control volume around each cell by connecting centroids of neighbouring
    cells.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset.
    variable_name : str
        Face-centered scalar variable to differentiate.
    scale_by_radius : bool, default False
        When ``True``, divide the unit-sphere derivatives by
        ``uxgrid.sphere_radius`` to return physical units (requires a grid with
        ``sphere_radius``). The default ``False`` keeps the unit-sphere result.

    Returns
    -------
    dict
        Keys: variable_name, zonal_component_name, meridional_component_name,
        n_face, stats (min/max/mean for each component).
    """
    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. Available: {list(uxds.data_vars)}"
        )
    var = uxds[variable_name]
    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Gradient requires face-centered data."
        )

    import numpy as np

    # gradient() returns a UxDataset with zonal and meridional components.
    grad = var.gradient(scale_by_radius=scale_by_radius)
    comp_names = list(grad.data_vars)

    def _stats(arr: Any) -> dict:
        vals = arr.values
        finite = vals[np.isfinite(vals)]
        if finite.size == 0:
            return {"min": None, "max": None, "mean": None}
        return {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
        }

    components = {name: _stats(grad[name]) for name in comp_names}

    return {
        "variable_name": variable_name,
        "components": comp_names,
        "component_stats": components,
        "n_face": int(uxds.uxgrid.n_face),
        "scale_by_radius": bool(scale_by_radius),
        "interpretation": "zonal (∂/∂x) and meridional (∂/∂y) components of the gradient",
    }


def compute_curl(
    uxds: Any, u_variable: str, v_variable: str, scale_by_radius: bool = False
) -> dict:
    """Compute the curl (relative vorticity) of a 2-D vector field (u, v).

    The curl is the vertical component of ∇ × (u, v):
        ζ = ∂v/∂x − ∂u/∂y

    For atmospheric wind fields this is the relative vorticity.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset containing both components.
    u_variable : str
        Zonal (east–west) component variable name.
    v_variable : str
        Meridional (north–south) component variable name.
    scale_by_radius : bool, default False
        When ``True``, divide the unit-sphere result by ``uxgrid.sphere_radius``
        to return physical units (``1/s`` for wind in ``m/s``; requires a grid
        with ``sphere_radius``). The default ``False`` keeps the unit sphere.

    Returns
    -------
    dict
        Keys: u_variable, v_variable, n_face, stats (min/max/mean/std of curl).
    """
    for name in (u_variable, v_variable):
        if name not in uxds.data_vars:
            raise ValueError(
                f"Variable '{name}' not found. Available: {list(uxds.data_vars)}"
            )
    u = uxds[u_variable]
    v = uxds[v_variable]
    for name, var in ((u_variable, u), (v_variable, v)):
        if "n_face" not in var.dims and "nCells" not in var.dims:
            raise ValueError(
                f"Variable '{name}' is not face-centered. "
                "Curl requires face-centered vector components."
            )

    import numpy as np

    component_warnings = _vector_component_warnings(
        u_variable, v_variable, u, v, "curl"
    )

    result = u.curl(v, scale_by_radius=scale_by_radius)
    vals = result.values
    finite = vals[np.isfinite(vals)]

    stats: dict = {}
    if finite.size > 0:
        stats = {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "std": float(finite.std()),
        }
    else:
        stats = {"min": None, "max": None, "mean": None, "std": None}

    return {
        "u_variable": u_variable,
        "v_variable": v_variable,
        "interpretation": "relative vorticity ζ = ∂v/∂x − ∂u/∂y",
        "n_face": int(uxds.uxgrid.n_face),
        "scale_by_radius": bool(scale_by_radius),
        "stats": stats,
        "component_warnings": component_warnings,
    }


def compute_divergence(uxds: Any, u_variable: str, v_variable: str) -> dict:
    """Compute the horizontal divergence of a 2-D vector field (u, v).

    Divergence = ∂u/∂x + ∂v/∂y.

    Positive values indicate divergence (outflow), negative values indicate
    convergence (inflow). Surface wind convergence drives rising motion and
    convection.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset.
    u_variable : str
        Zonal (east–west) component variable name.
    v_variable : str
        Meridional (north–south) component variable name.

    Returns
    -------
    dict
        Keys: u_variable, v_variable, n_face, stats (min/max/mean/std).
    """
    for name in (u_variable, v_variable):
        if name not in uxds.data_vars:
            raise ValueError(
                f"Variable '{name}' not found. Available: {list(uxds.data_vars)}"
            )
    u = uxds[u_variable]
    v = uxds[v_variable]
    for name, var in ((u_variable, u), (v_variable, v)):
        if "n_face" not in var.dims and "nCells" not in var.dims:
            raise ValueError(
                f"Variable '{name}' is not face-centered. "
                "Divergence requires face-centered vector components."
            )

    import numpy as np

    component_warnings = _vector_component_warnings(
        u_variable, v_variable, u, v, "divergence"
    )

    result = u.divergence(v)
    vals = result.values
    finite = vals[np.isfinite(vals)]

    stats: dict = {}
    if finite.size > 0:
        stats = {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "std": float(finite.std()),
        }
    else:
        stats = {"min": None, "max": None, "mean": None, "std": None}

    return {
        "u_variable": u_variable,
        "v_variable": v_variable,
        "interpretation": "horizontal divergence ∂u/∂x + ∂v/∂y",
        "n_face": int(uxds.uxgrid.n_face),
        "stats": stats,
        "component_warnings": component_warnings,
    }


def compute_azimuthal_mean(
    uxds: Any,
    variable_name: str,
    center_lon: float,
    center_lat: float,
    outer_radius: float,
    radius_step: float,
) -> dict:
    """Compute the azimuthal (radial) mean around a centre point.

    Averages the variable along circles of constant great-circle distance from
    the centre, producing a radial profile. Useful for analysing tropical
    cyclones, polar vortex structure, or any feature with approximate radial
    symmetry.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset.
    variable_name : str
        Face-centered variable to average.
    center_lon : float
        Longitude of the centre point (degrees).
    center_lat : float
        Latitude of the centre point (degrees).
    outer_radius : float
        Maximum radius in great-circle degrees.
    radius_step : float
        Radial bin width in great-circle degrees.

    Returns
    -------
    dict
        Keys: variable_name, center, radii, azimuthal_mean_values, n_face.
    """
    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. Available: {list(uxds.data_vars)}"
        )
    var = uxds[variable_name]
    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Azimuthal mean requires face-centered data."
        )

    result = var.azimuthal_mean(
        center_coord=(center_lon, center_lat),
        outer_radius=outer_radius,
        radius_step=radius_step,
    )

    # result is an xr.DataArray with a radius coordinate
    radii = result.coords[result.dims[0]].values.tolist()
    values = result.values.tolist()

    return {
        "variable_name": variable_name,
        "center": {"lon": center_lon, "lat": center_lat},
        "outer_radius_deg": outer_radius,
        "radius_step_deg": radius_step,
        "radii_deg": radii,
        "azimuthal_mean_values": values,
        "n_face": int(uxds.uxgrid.n_face),
    }
