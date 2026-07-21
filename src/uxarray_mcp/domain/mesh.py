"""Shared grid loading with HEALPix and GIS support."""

import os
from typing import Any


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

    if file_path.lower().startswith("healpix"):
        parts = file_path.split(":")
        zoom = int(parts[1]) if len(parts) > 1 else 1
        return ux.Grid.from_healpix(zoom=zoom)

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
    if grid_path.lower().startswith("healpix"):
        parts = grid_path.split(":")
        zoom = int(parts[1]) if len(parts) > 1 else 1
        grid = ux.Grid.from_healpix(zoom=zoom)
        return ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)

    ext = os.path.splitext(grid_path.lower())[1]
    if ext in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        return ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)

    return ux.open_dataset(grid_path, data_path)
