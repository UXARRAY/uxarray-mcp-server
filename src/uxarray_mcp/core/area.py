"""Face area statistics, and the sphere they were measured on.

UXarray integrates face areas on the unit sphere and never applies the
grid's radius: ``Grid.sphere_radius`` is documented as storing "the original
radius for scaling results back to physical units", and defaults to ``1.0``.
Measured on a 648-face global mesh, ``sum(face_areas)`` is 12.566371, which is
4*pi steradians -- and a file that declares ``sphere_radius: 6371000.0``
round-trips that attribute into the reloaded grid and still sums to 12.566371.

So ``calculate_area`` was returning a dimensionless number with
``area_units: null``, ``physically_interpretable: null`` and no warning codes,
on grids that had said in their own metadata how big the sphere is. The
docstring example in ``remote_tools.calculate_area`` promised
``total_area: 5.10064e14``, the Earth's surface in square metres, which the
tool has never returned.

The radius is applied here instead. Areas scale as ``R**2``, so the whole
correction is one multiply, and the block that says which radius was used
travels with the numbers.
"""

from typing import Any

from .mesh_coverage import compute_mesh_coverage

#: UXarray's default when a grid declares nothing, and its unit-sphere basis.
UNIT_SPHERE_RADIUS = 1.0


def compute_area_stats(grid: Any, sphere_radius: float | None = None) -> dict:
    """Compute face area statistics for a loaded grid.

    Parameters
    ----------
    grid : ux.Grid
        Loaded UXarray grid.
    sphere_radius : float | None
        Radius in metres to scale the unit-sphere areas by. Overrides the
        grid's own ``sphere_radius`` when both are present, since a caller
        naming a radius is correcting the file rather than repeating it.

    Returns
    -------
    dict
        Keys: total_area, mean_area, min_area, max_area, area_units, n_face
        and area_basis.
        ``area_units`` is ``None`` when nothing established it. The grid's
        own ``units`` attribute wins; an explicit ``sphere_radius`` argument
        is documented in metres and so yields ``"m^2"``; a radius read from
        the grid yields neither, because a file that declares a radius
        without units has not said what those units are, and inventing
        ``"m^2"`` there is the fabrication this server exists to avoid.
    """
    face_areas = grid.face_areas

    area_units = None
    if hasattr(face_areas, "attrs") and "units" in face_areas.attrs:
        area_units = face_areas.attrs["units"]

    steradians = float(face_areas.sum())
    stats = {
        "total_area": steradians,
        "mean_area": float(face_areas.mean()),
        "min_area": float(face_areas.min()),
        "max_area": float(face_areas.max()),
        "area_units": area_units,
        "n_face": int(grid.n_face),
        # Attached before scaling, and measured on the unit sphere whatever
        # radius is applied below: a total is only readable as global or
        # regional next to the fraction of the sphere it was summed over.
        "mesh_coverage": compute_mesh_coverage(grid, steradians=steradians),
    }
    radius, source = resolve_sphere_radius(grid, sphere_radius)
    return apply_sphere_radius(stats, radius, source)


def resolve_sphere_radius(
    grid: Any,
    sphere_radius: float | None = None,
) -> tuple[float | None, str]:
    """Decide which radius the areas should be expressed on.

    Returns ``(None, "unit_sphere")`` when neither the caller nor the grid
    named one. UXarray reports ``sphere_radius`` as ``1.0`` in that case,
    which is indistinguishable from a genuine unit sphere and is treated as
    the same thing: either way the areas are steradians.
    """
    if sphere_radius is not None:
        return float(sphere_radius), "argument"
    declared = getattr(grid, "sphere_radius", None)
    try:
        declared = float(declared) if declared is not None else None
    except (TypeError, ValueError):
        declared = None
    if declared is None or declared == UNIT_SPHERE_RADIUS:
        return None, "unit_sphere"
    return declared, "grid"


def apply_sphere_radius(
    stats: dict[str, Any],
    radius: float | None,
    source: str,
) -> dict[str, Any]:
    """Scale unit-sphere areas onto a sphere of ``radius`` and say so.

    Separated from the measurement because the remote path gets its numbers
    from a worker rather than from a grid, and the scaling has to be the same
    arithmetic in both places or the two would disagree about what
    ``total_area`` means.
    """
    applied = UNIT_SPHERE_RADIUS if radius is None else float(radius)
    scaled = applied != UNIT_SPHERE_RADIUS
    result = dict(stats)
    if scaled:
        factor = applied**2
        for key in ("total_area", "mean_area", "min_area", "max_area"):
            value = result.get(key)
            if value is not None:
                result[key] = float(value) * factor
        if result.get("area_units") is None and source == "argument":
            result["area_units"] = "m^2"
    result["area_basis"] = {
        "sphere_radius": applied,
        "radius_source": source,
        "scaled": scaled,
    }
    return result
