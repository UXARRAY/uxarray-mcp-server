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
        Keys: total_area, mean_area, min_area, max_area, area_units, n_face
    """
    face_areas = grid.face_areas

    area_units = "m^2"
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
