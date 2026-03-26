from unittest.mock import MagicMock, patch

import pytest

from uxarray_mcp.tools.inspection import calculate_area

# -----------------------------------------------------------------------------
# Unit Tests (Mocked)
# -----------------------------------------------------------------------------


class TestCalculateAreaBasic:
    """Tests for basic calculate_area functionality using mocks."""

    def test_calculate_area_basic(self):
        """Test basic area calculation."""
        mock_grid = MagicMock()
        mock_grid.n_face = 100
        mock_areas = MagicMock()
        mock_areas.sum.return_value = 1000.0
        mock_areas.mean.return_value = 10.0
        mock_areas.min.return_value = 5.0
        mock_areas.max.return_value = 15.0
        mock_areas.attrs = {"units": "m^2"}
        mock_grid.face_areas = mock_areas

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_grid", return_value=mock_grid),
        ):
            MockPath.return_value.exists.return_value = True

            result = calculate_area("/mesh.nc")

            assert result["total_area"] == 1000.0
            assert result["mean_area"] == 10.0
            assert result["min_area"] == 5.0
            assert result["max_area"] == 15.0
            assert result["area_units"] == "m^2"
            assert result["n_face"] == 100

    def test_calculate_area_healpix(self):
        """Test area calculation for HEALPix mesh."""
        mock_grid = MagicMock()
        mock_grid.n_face = 192  # 12 * 4^2 for zoom 2
        mock_areas = MagicMock()
        mock_areas.sum.return_value = 5.1e14
        mock_areas.mean.return_value = 2.66e12
        mock_areas.min.return_value = 2.5e12
        mock_areas.max.return_value = 2.7e12
        mock_areas.attrs = {}
        mock_grid.face_areas = mock_areas

        with patch("uxarray.Grid.from_healpix", return_value=mock_grid):
            result = calculate_area("healpix:2")

            assert result["total_area"] == 5.1e14
            assert result["n_face"] == 192
            assert result["area_units"] == "m^2"  # Default units

    def test_calculate_area_no_units(self):
        """Test area calculation when units not specified."""
        mock_grid = MagicMock()
        mock_grid.n_face = 50
        mock_areas = MagicMock()
        mock_areas.sum.return_value = 500.0
        mock_areas.mean.return_value = 10.0
        mock_areas.min.return_value = 8.0
        mock_areas.max.return_value = 12.0
        mock_areas.attrs = {}
        mock_grid.face_areas = mock_areas

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_grid", return_value=mock_grid),
        ):
            MockPath.return_value.exists.return_value = True

            result = calculate_area("/mesh.nc")

            assert result["area_units"] == "m^2"  # Default


class TestCalculateAreaErrorHandling:
    """Tests for error handling and edge cases."""

    def test_file_not_found(self):
        """Test handling of non-existent files."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.return_value = False

            with pytest.raises(FileNotFoundError, match="Mesh file not found"):
                calculate_area("/nonexistent/file.nc")

    def test_healpix_invalid_format(self):
        """Test invalid HEALPix format."""
        with pytest.raises(ValueError, match="Invalid HEALPix format"):
            calculate_area("healpix:invalid")

    def test_grid_loading_error(self):
        """Test handling of grid loading errors."""
        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_grid", side_effect=Exception("Load error")),
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(RuntimeError, match="Failed to load mesh file"):
                calculate_area("/mesh.nc")

    def test_area_calculation_error(self):
        """Test handling of area calculation errors."""
        mock_grid = MagicMock()
        # Make face_areas property raise an exception when accessed
        type(mock_grid).face_areas = property(
            lambda self: (_ for _ in ()).throw(Exception("Calculation error"))
        )

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_grid", return_value=mock_grid),
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(RuntimeError, match="Failed to calculate face areas"):
                calculate_area("/mesh.nc")


# -----------------------------------------------------------------------------
# Integration Tests (Real Data)
# -----------------------------------------------------------------------------


def test_calculate_area_integration(synthetic_mesh_file):
    """
    Integration test using a real synthetic mesh file.
    Verifies that the tool actually works with uxarray calculating real areas.
    """
    result = calculate_area(synthetic_mesh_file)

    # Should have calculated areas
    assert "total_area" in result
    assert "mean_area" in result
    assert "min_area" in result
    assert "max_area" in result
    assert "area_units" in result
    assert "n_face" in result

    # Total area should be positive
    assert result["total_area"] > 0
    assert result["mean_area"] > 0

    # Number of faces should match
    assert result["n_face"] == 1  # Our synthetic mesh has 1 triangle
