"""Real (non-mocked) end-to-end tests for uxarray_mcp.domain.mesh.load_dataset.

Regression coverage for a bug where HEALPix and GIS (shapefile/GeoJSON)
grids combined with a *separate* data file crashed with
``ValueError: cannot rename 'node_lon' because it is not a variable or
dimension in this dataset``. The bug existed because ``load_dataset``
routed these grid types through ``ux.open_dataset(grid.to_xarray(),
data_path)``, treating the grid's minimal ``to_xarray()`` representation as
if it were a full UGRID *file* — which the generic UGRID reader rejects for
HEALPix (no node coordinates) and geopandas-backed grids alike.

Every existing test of these grid types (``test_inspect_mesh.py``,
``TestScaleByRadius`` in ``test_vector_calc.py``, etc.) either exercises
grid-only operations (no ``data_path``) or mocks ``load_dataset`` itself, so
this real file-I/O path was never actually run end-to-end. These tests
intentionally avoid mocking ``load_dataset`` for that reason.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.domain.mesh import load_dataset


def _write_polygon_shapefile(path):
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import Polygon

    gdf = geopandas.GeoDataFrame(
        {"value": [1, 2, 3]},
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
        ],
        crs="EPSG:4326",
    )
    gdf.to_file(path)


class TestLoadDatasetHealpix:
    def test_attaches_data_to_healpix_grid(self, tmp_path):
        import uxarray as ux

        grid = ux.Grid.from_healpix(zoom=2)
        data_path = tmp_path / "data.nc"
        xr.Dataset(
            {"temperature": (["n_face"], np.zeros(grid.n_face), {"units": "K"})}
        ).to_netcdf(data_path)

        uxds = load_dataset("healpix:2", str(data_path))

        assert uxds.uxgrid.n_face == grid.n_face
        assert "temperature" in uxds.data_vars
        assert uxds["temperature"].shape == (grid.n_face,)

    def test_run_analysis_gradient_on_healpix_with_data(self, tmp_path):
        """End-to-end regression: this exact call used to raise ValueError."""
        import uxarray as ux

        from uxarray_mcp.tools import run_analysis

        grid = ux.Grid.from_healpix(zoom=2)
        data_path = tmp_path / "data.nc"
        rng = np.random.default_rng(0)
        xr.Dataset(
            {
                "phi": (
                    ["n_face"],
                    rng.standard_normal(grid.n_face),
                    {"units": "K"},
                )
            }
        ).to_netcdf(data_path)

        result = run_analysis(
            operation="gradient",
            grid_path="healpix:2",
            data_path=str(data_path),
            variable_name="phi",
        )
        assert result["n_face"] == grid.n_face
        assert "_provenance" in result


class TestLoadDatasetGIS:
    def test_attaches_data_to_shapefile_grid(self, tmp_path):
        shp_path = tmp_path / "polygons.shp"
        _write_polygon_shapefile(shp_path)

        data_path = tmp_path / "data.nc"
        xr.Dataset(
            {"value": (["n_face"], np.array([10.0, 20.0, 30.0]), {"units": "K"})}
        ).to_netcdf(data_path)

        uxds = load_dataset(str(shp_path), str(data_path))

        assert uxds.uxgrid.n_face == 3
        assert "value" in uxds.data_vars


class TestRemoteComputeFunctionsHealpixData:
    """Same regression, exercised through ``remote.compute_functions``.

    These are plain functions (no Globus Compute machinery involved when
    called directly), so they can be tested locally. The remote module
    duplicates the grid/data-loading branch inline in ~20 functions
    (Globus Compute serializes each function body standalone, so a shared
    helper isn't reliable across SDK versions — see the module's own NOTE),
    so each duplicate was an independent copy of the same bug.
    """

    @staticmethod
    def _make_healpix_fixture(tmp_path):
        import uxarray as ux

        grid = ux.Grid.from_healpix(zoom=2)
        data_path = tmp_path / "data.nc"
        rng = np.random.default_rng(1)
        xr.Dataset(
            {
                "temperature": (
                    ["n_face"],
                    rng.standard_normal(grid.n_face),
                    {"units": "K"},
                )
            }
        ).to_netcdf(data_path)
        return grid, str(data_path)

    def test_remote_calculate_zonal_mean_on_healpix(self, tmp_path):
        from uxarray_mcp.remote.compute_functions import remote_calculate_zonal_mean

        grid, data_path = self._make_healpix_fixture(tmp_path)
        result = remote_calculate_zonal_mean(
            "healpix:2", data_path, "temperature", None, False
        )
        assert len(result["zonal_mean_values"]) == len(result["latitudes"])
        assert result["grid_info"]["n_face"] == grid.n_face

    def test_remote_inspect_variable_on_healpix(self, tmp_path):
        from uxarray_mcp.remote.compute_functions import remote_inspect_variable

        _, data_path = self._make_healpix_fixture(tmp_path)
        result = remote_inspect_variable("healpix:2", data_path, None)
        names = [v["name"] for v in result["variables"]]
        assert "temperature" in names

    def test_remote_calculate_gradient_on_healpix(self, tmp_path):
        from uxarray_mcp.remote.compute_functions import remote_calculate_gradient

        grid, data_path = self._make_healpix_fixture(tmp_path)
        result = remote_calculate_gradient("healpix:2", data_path, "temperature", False)
        assert result["n_face"] == grid.n_face
