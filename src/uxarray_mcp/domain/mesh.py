"""Shared grid loading with HEALPix and GIS support."""

import os
from typing import Any

#: Largest HEALPix zoom we accept. Zoom ``z`` has ``12 * 4**z`` faces, so
#: ``z=13`` is already ~805M faces -- far past what a worker can hold. Anything
#: beyond this is a typo, and failing fast beats an OOM kill on an HPC node.
MAX_HEALPIX_ZOOM = 13


def is_healpix_spec(file_path: Any) -> bool:
    """True when ``file_path`` is a virtual HEALPix spec, not a real file.

    The spec form is ``healpix:<zoom>`` (case-insensitive). The colon is
    required: a prefix-only test such as ``startswith("healpix")`` also
    matches an ordinary file named ``healpix_z5_data.nc``, which would be
    silently replaced by a virtual grid of the wrong size instead of being
    read from disk.
    """
    if not isinstance(file_path, str):
        return False
    prefix, sep, _ = file_path.partition(":")
    return bool(sep) and prefix.strip().lower() == "healpix"


def parse_healpix_zoom(file_path: str) -> int:
    """Extract and validate the zoom level from a ``healpix:<zoom>`` spec.

    Raises
    ------
    ValueError
        If the spec is malformed, the zoom is not an integer, is negative, or
        exceeds :data:`MAX_HEALPIX_ZOOM`. Silently coercing these (the old
        behaviour) produced a valid-looking grid at the wrong resolution.
    """
    _, _, raw = file_path.partition(":")
    raw = raw.strip()
    try:
        zoom = int(raw)
    except ValueError:
        raise ValueError(
            "Invalid HEALPix format. Use 'healpix:<zoom_level>' "
            f"(e.g. 'healpix:2'); got {file_path!r}."
        ) from None
    if zoom < 0 or zoom > MAX_HEALPIX_ZOOM:
        raise ValueError(
            "Invalid HEALPix format. Zoom must be between 0 and "
            f"{MAX_HEALPIX_ZOOM} inclusive; got {zoom}."
        )
    return zoom


def load_grid(file_path: str) -> Any:
    """Load a UXarray Grid from a file path, HEALPix spec, or shapefile/geojson.

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

    if is_healpix_spec(file_path):
        return ux.Grid.from_healpix(zoom=parse_healpix_zoom(file_path))

    ext = os.path.splitext(file_path.lower())[1]
    if ext in [".shp", ".geojson"]:
        return ux.Grid.from_file(file_path, backend="geopandas")

    return ux.open_grid(file_path)


def load_dataset(grid_path: str, data_path: str) -> Any:
    """Load a UXarray Dataset from grid and data paths, supporting shapefiles/geojson.

    Parameters
    ----------
    grid_path : str
        Path to mesh grid file or "healpix:<zoom>".
    data_path : str
        Path to netCDF data file.

    Returns
    -------
    ux.UxDataset
        Loaded dataset object.
    """
    import uxarray as ux
    import xarray as xr

    # HEALPix and GIS grids don't round-trip through ux.open_dataset() as a
    # "grid file" the way a real UGRID/MPAS/SCRIP file does: grid.to_xarray()
    # returns a minimal representation (e.g. HEALPix has no node coordinates)
    # that the generic UGRID reader rejects. Attach the data directly to the
    # already-loaded Grid object instead.
    if is_healpix_spec(grid_path):
        grid = ux.Grid.from_healpix(zoom=parse_healpix_zoom(grid_path))
        return ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)

    ext = os.path.splitext(grid_path.lower())[1]
    if ext in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        return ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)

    return ux.open_dataset(grid_path, data_path)
