from unittest.mock import patch

import pytest

from uxarray_mcp.tools import inspect_mesh

# -----------------------------------------------------------------------------
# Unit Tests (Mocked)
# -----------------------------------------------------------------------------


class TestInspectMeshFormat:
    """Tests for different mesh formats using mocks (MPAS, UGRID, etc.)."""

    def test_inspect_mpas_mesh(self, mpas_grid):
        """Test inspection of an MPAS mesh."""
        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_grid", return_value=mpas_grid),
        ):
            MockPath.return_value.exists.return_value = True
            MockPath.return_value.stat.return_value.st_size = 1024 * 1024

            result = inspect_mesh("/path/to/mpas.nc")
            assert result["format"] == "MPAS"
            assert result["n_face"] == 100

    def test_inspect_ugrid_mesh(self, ugrid_grid):
        """Test inspection of a UGRID mesh."""
        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_grid", return_value=ugrid_grid),
        ):
            MockPath.return_value.exists.return_value = True
            MockPath.return_value.stat.return_value.st_size = 1024 * 1024

            result = inspect_mesh("/path/to/ugrid.nc")
            assert result["format"] == "UGRID"

    def test_inspect_scrip_mesh(self, scrip_grid):
        """Test inspection of a SCRIP mesh."""
        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_grid", return_value=scrip_grid),
        ):
            MockPath.return_value.exists.return_value = True
            MockPath.return_value.stat.return_value.st_size = 1024 * 1024

            result = inspect_mesh("/path/to/scrip.nc")
            assert result["format"] == "SCRIP"

    def test_inspect_shapefile_mesh(self, base_grid):
        """Test inspection of a Shapefile mesh."""
        base_grid.source_grid_spec = "Shapefile"
        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.Grid.from_file", return_value=base_grid) as mock_from_file,
        ):
            MockPath.return_value.exists.return_value = True
            MockPath.return_value.stat.return_value.st_size = 1024 * 1024

            result = inspect_mesh("/path/to/shapefile.shp")
            mock_from_file.assert_called_once_with(
                "/path/to/shapefile.shp", backend="geopandas"
            )
            assert result["format"] == "Shapefile"

    def test_inspect_geojson_mesh(self, base_grid):
        """Test inspection of a GeoJSON mesh."""
        base_grid.source_grid_spec = "GeoJSON"
        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.Grid.from_file", return_value=base_grid) as mock_from_file,
        ):
            MockPath.return_value.exists.return_value = True
            MockPath.return_value.stat.return_value.st_size = 1024 * 1024

            result = inspect_mesh("/path/to/geojson.geojson")
            mock_from_file.assert_called_once_with(
                "/path/to/geojson.geojson", backend="geopandas"
            )
            assert result["format"] == "GeoJSON"

    def test_inspect_healpix_mesh(self, base_grid):
        """Test inspection of a HEALPix mesh generation."""
        # Mock grid returned by from_healpix
        healpix_grid = base_grid
        healpix_grid.n_face = 12 * 4**2  # Zoom 2 (example)
        healpix_grid.n_node = 200  # Dummy
        healpix_grid.n_edge = 300  # Dummy

        with patch(
            "uxarray.Grid.from_healpix", return_value=healpix_grid
        ) as mock_from_healpix:
            result = inspect_mesh("healpix:2")

            mock_from_healpix.assert_called_once_with(zoom=2)
            assert result["format"] == "HEALPix"
            assert result["n_face"] == 192  # 12 * 4^2
            assert result["file_size_mb"] == 0.0

    def test_inspect_healpix_invalid_format(self):
        """Test invalid healpix format."""
        with pytest.raises(ValueError, match="Invalid HEALPix format"):
            inspect_mesh("healpix:invalid")


class TestInspectMeshErrorHandling:
    """Tests for error handling and edge cases."""

    def test_file_not_found(self):
        """Test handling of non-existent files."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.return_value = False

            with pytest.raises(FileNotFoundError, match="Mesh file not found"):
                inspect_mesh("/nonexistent/file.nc")

    # ... (Other error handling tests can remain or be simplified if redundant)
    # Keeping major ones for robustness


# -----------------------------------------------------------------------------
# Integration Tests (Real/Synthetic)
# -----------------------------------------------------------------------------


def test_inspect_synthetic_mesh(synthetic_mesh_file):
    """
    Integration test using a real (synthetic) temporary file.
    Verifies that the tool actually works with uxarray reading a real file.
    """
    result = inspect_mesh(synthetic_mesh_file)

    assert result["n_face"] == 1
    assert result["n_node"] == 3
    # Check that it detected valid mesh data (format name varies by detection)
    assert result["format"] is not None
