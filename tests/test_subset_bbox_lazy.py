"""Correctness check for remote_subset_bbox_plot's SCRIP memory pre-check.

``remote_subset_bbox_plot`` (remote/compute_functions.py) refuses cleanly,
with a clear ``ValueError``, before ever calling ``ux.open_grid(...)`` on a
SCRIP ``.nc`` file whose corner arrays are estimated to exceed a 100 GiB
safety threshold -- an outer safety net for files too large even for the
dask-native lazy SCRIP dedup path, rather than the load-bearing guard it
used to be before that fix landed.

The oversized fixture uses ``uint8`` zeros (not float64) so that hitting
the real element count needed to exceed 100 GiB (the pre-check estimate
always assumes 8-byte floats, matching real SCRIP files, regardless of the
fixture's actual on-disk dtype) is cheap to write and store on disk.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.remote import compute_functions as cf

pytest.importorskip("uxarray")
pytest.importorskip("dask")

LON_BOUNDS = [-100.0, -90.0]
LAT_BOUNDS = [25.0, 35.0]


def _write_small_scrip(path, n_face=20, n_corner=4):
    rng = np.random.default_rng(0)
    base_lon = rng.uniform(0.0, 360.0, size=n_face)
    base_lat = rng.uniform(-80.0, 80.0, size=n_face)
    corner_lon = np.stack(
        [base_lon + rng.uniform(-0.1, 0.1, size=n_face) for _ in range(n_corner)],
        axis=1,
    )
    corner_lat = np.stack(
        [base_lat + rng.uniform(-0.1, 0.1, size=n_face) for _ in range(n_corner)],
        axis=1,
    )
    ds = xr.Dataset(
        {
            "grid_corner_lon": (("grid_size", "grid_corners"), corner_lon),
            "grid_corner_lat": (("grid_size", "grid_corners"), corner_lat),
            "grid_center_lon": (("grid_size",), base_lon),
            "grid_center_lat": (("grid_size",), base_lat),
            "grid_area": (("grid_size",), np.ones(n_face)),
            "grid_imask": (("grid_size",), np.ones(n_face, dtype=np.int32)),
            "grid_dims": (("grid_rank",), np.array([n_face], dtype=np.int32)),
        }
    )
    ds.to_netcdf(path)


def _write_oversized_scrip(path):
    """A SCRIP-shaped .nc file whose declared (grid_size, grid_corners)
    shape alone -- 2 * 2000 * 3,500,000 * 8 bytes ~= 104.4 GiB -- exceeds
    the pre-check's 100 GiB threshold, without actually allocating
    gigabytes: the underlying data is all-zero uint8 with light
    compression, so the file is ~12 MB on disk and writes in a couple of
    seconds.
    """
    import dask.array as da

    n_face, n_corner = 2000, 3_500_000
    shape = (n_face, n_corner)
    lon = da.zeros(shape, chunks=(n_face, n_corner), dtype="u1")
    lat = da.zeros(shape, chunks=(n_face, n_corner), dtype="u1")
    ds = xr.Dataset(
        {
            "grid_corner_lon": (("grid_size", "grid_corners"), lon),
            "grid_corner_lat": (("grid_size", "grid_corners"), lat),
            "grid_area": (("grid_size",), np.ones(n_face)),
        }
    )
    encoding = {
        v: {"zlib": True, "complevel": 1}
        for v in ("grid_corner_lon", "grid_corner_lat")
    }
    ds.to_netcdf(path, encoding=encoding)


def test_oversized_scrip_grid_refused_cleanly(tmp_path):
    grid_path = str(tmp_path / "huge_scrip.nc")
    _write_oversized_scrip(grid_path)

    with pytest.raises(ValueError, match="Refusing to open SCRIP grid"):
        cf.remote_subset_bbox_plot(
            grid_path=grid_path,
            lon_bounds=LON_BOUNDS,
            lat_bounds=LAT_BOUNDS,
            region_name="oversized",
        )


def test_small_scrip_grid_proceeds_normally(tmp_path):
    """A small SCRIP grid, comfortably under the threshold, must be
    unaffected by the pre-check and plot exactly as before."""
    grid_path = str(tmp_path / "small_scrip.nc")
    _write_small_scrip(grid_path)

    result = cf.remote_subset_bbox_plot(
        grid_path=grid_path,
        lon_bounds=[-180.0, 180.0],
        lat_bounds=[-90.0, 90.0],
        region_name="small",
    )
    assert result["n_face_total"] == 20


def test_non_scrip_nc_unaffected_by_precheck(tmp_path):
    """A .nc file without grid_corner_lat (e.g. UGRID) must skip the
    SCRIP-specific pre-check entirely and proceed via the normal path."""
    import uxarray as ux

    grid_path = str(tmp_path / "not_scrip.nc")
    node_lon = np.array([-95.0, -94.0, -94.0, -95.0])
    node_lat = np.array([28.0, 28.0, 29.0, 29.0])
    face_node_connectivity = np.array([[0, 1, 2, 3]])
    grid = ux.Grid.from_topology(
        node_lon=node_lon,
        node_lat=node_lat,
        face_node_connectivity=face_node_connectivity,
        fill_value=-1,
        start_index=0,
    )
    grid.to_xarray().to_netcdf(grid_path)

    result = cf.remote_subset_bbox_plot(
        grid_path=grid_path,
        lon_bounds=LON_BOUNDS,
        lat_bounds=LAT_BOUNDS,
        region_name="ugrid-fallback",
    )
    assert result["n_face_total"] == 1
