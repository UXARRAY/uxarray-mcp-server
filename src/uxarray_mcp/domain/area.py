"""Shared face area computation logic."""

from typing import Any


def compute_area_stats(grid: Any) -> dict:
    """Compute face area statistics for a loaded grid.

    Parameters
    ----------
    grid : ux.Grid
        Loaded UXarray grid.

    Returns
    -------
    dict
        Keys: total_area, mean_area, min_area, max_area, area_units, n_face.
        ``area_units`` is ``None`` when the grid carries no ``units``
        attribute at all -- reporting a fabricated ``"m^2"`` default in
        that case would silently invent metadata the source file never
        provided, which is the exact failure mode this server's
        provenance and guardrail mechanisms exist to prevent.
    """
    face_areas = grid.face_areas

    area_units = None
    if hasattr(face_areas, "attrs") and "units" in face_areas.attrs:
        area_units = face_areas.attrs["units"]

    return {
        "total_area": float(face_areas.sum()),
        "mean_area": float(face_areas.mean()),
        "min_area": float(face_areas.min()),
        "max_area": float(face_areas.max()),
        "area_units": area_units,
        "n_face": int(grid.n_face),
    }
