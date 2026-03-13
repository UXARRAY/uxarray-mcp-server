"""Shared grid loading with HEALPix support."""

from typing import Any


def load_grid(file_path: str) -> Any:
    """Load a UXarray Grid from a file path or HEALPix spec.

    Parameters
    ----------
    file_path : str
        Path to mesh file, or "healpix:<zoom>" for virtual HEALPix meshes.

    Returns
    -------
    ux.Grid
        Loaded grid object.
    """
    import uxarray as ux

    if file_path.lower().startswith("healpix"):
        parts = file_path.split(":")
        zoom = int(parts[1]) if len(parts) > 1 else 1
        return ux.Grid.from_healpix(zoom=zoom)

    return ux.open_grid(file_path)
