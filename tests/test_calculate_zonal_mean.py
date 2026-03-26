"""Tests for the calculate_zonal_mean tool."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from uxarray_mcp.tools import calculate_zonal_mean


class TestCalculateZonalMeanUnit:
    """Unit tests for calculate_zonal_mean using mocks."""

    def test_zonal_mean_default_params(self):
        """Test zonal mean calculation with default parameters."""
        # Mock the dataset and variable
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_zonal_result = MagicMock()

        # Set up the mock chain
        mock_uxds.__getitem__.return_value = mock_var
        mock_var.dims = ("n_face",)
        mock_var.zonal_mean.return_value = mock_zonal_result

        # Mock the zonal mean result
        mock_zonal_result.coords = {"latitudes": MagicMock()}
        mock_zonal_result.coords["latitudes"].values = np.array(
            [
                -90,
                -80,
                -70,
                -60,
                -50,
                -40,
                -30,
                -20,
                -10,
                0,
                10,
                20,
                30,
                40,
                50,
                60,
                70,
                80,
                90,
            ]
        )
        mock_zonal_result.values = np.array(
            [
                271.5,
                273.2,
                275.0,
                277.1,
                280.3,
                283.5,
                286.2,
                288.0,
                289.5,
                290.0,
                289.5,
                288.0,
                286.2,
                283.5,
                280.3,
                277.1,
                275.0,
                273.2,
                271.5,
            ]
        )

        # Mock grid info
        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        # Mock data_vars
        # Mock data_vars properly
        mock_data_vars = MagicMock()
        mock_data_vars.__contains__ = lambda self, key: key == "temperature"
        mock_uxds.data_vars = mock_data_vars

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = calculate_zonal_mean("/grid.nc", "/data.nc", "temperature")

            assert result["variable_name"] == "temperature"
            assert len(result["latitudes"]) == 19
            assert len(result["zonal_mean_values"]) == 19
            assert result["conservative"] is False
            assert result["grid_info"]["n_face"] == 100

            # Verify zonal_mean was called with default parameters
            mock_var.zonal_mean.assert_called_once_with(conservative=False)

    def test_zonal_mean_conservative(self):
        """Test conservative zonal mean calculation."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_zonal_result = MagicMock()

        mock_uxds.__getitem__.return_value = mock_var
        mock_var.dims = ("n_face",)
        mock_var.zonal_mean.return_value = mock_zonal_result

        mock_zonal_result.coords = {"latitudes": MagicMock()}
        mock_zonal_result.coords["latitudes"].values = np.array([-60, -30, 0, 30, 60])
        mock_zonal_result.values = np.array([275.0, 282.0, 290.0, 282.0, 275.0])

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300
        # Mock data_vars properly
        mock_data_vars = MagicMock()
        mock_data_vars.__contains__ = lambda self, key: key == "temperature"
        mock_uxds.data_vars = mock_data_vars

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = calculate_zonal_mean(
                "/grid.nc", "/data.nc", "temperature", conservative=True
            )

            assert result["conservative"] is True
            assert len(result["latitudes"]) == 5

            # Verify conservative flag was passed
            mock_var.zonal_mean.assert_called_once_with(conservative=True)

    def test_zonal_mean_custom_lat_tuple(self):
        """Test zonal mean with custom latitude specification (tuple)."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_zonal_result = MagicMock()

        mock_uxds.__getitem__.return_value = mock_var
        mock_var.dims = ("n_face",)
        mock_var.zonal_mean.return_value = mock_zonal_result

        mock_zonal_result.coords = {"latitudes": MagicMock()}
        mock_zonal_result.coords["latitudes"].values = np.array(
            [-60, -40, -20, 0, 20, 40, 60]
        )
        mock_zonal_result.values = np.array(
            [275.0, 280.0, 285.0, 290.0, 285.0, 280.0, 275.0]
        )

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300
        # Mock data_vars properly
        mock_data_vars = MagicMock()
        mock_data_vars.__contains__ = lambda self, key: key == "temperature"
        mock_uxds.data_vars = mock_data_vars

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = calculate_zonal_mean(
                "/grid.nc", "/data.nc", "temperature", lat_spec=(-60, 60, 20)
            )

            assert len(result["latitudes"]) == 7

            # Verify lat_spec was passed
            mock_var.zonal_mean.assert_called_once_with(
                lat=(-60, 60, 20), conservative=False
            )

    def test_zonal_mean_single_latitude(self):
        """Test zonal mean at a single latitude."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_zonal_result = MagicMock()

        mock_uxds.__getitem__.return_value = mock_var
        mock_var.dims = ("n_face",)
        mock_var.zonal_mean.return_value = mock_zonal_result

        mock_zonal_result.coords = {"latitudes": MagicMock()}
        mock_zonal_result.coords["latitudes"].values = np.array([30.0])
        mock_zonal_result.values = np.array([285.0])

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300
        # Mock data_vars properly
        mock_data_vars = MagicMock()
        mock_data_vars.__contains__ = lambda self, key: key == "temperature"
        mock_uxds.data_vars = mock_data_vars

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = calculate_zonal_mean(
                "/grid.nc", "/data.nc", "temperature", lat_spec=30.0
            )

            assert len(result["latitudes"]) == 1
            assert result["latitudes"][0] == 30.0
            assert result["zonal_mean_values"][0] == 285.0

            # Verify lat_spec was passed
            mock_var.zonal_mean.assert_called_once_with(lat=30.0, conservative=False)

    def test_zonal_mean_explicit_latitudes(self):
        """Test zonal mean with explicit latitude list."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_zonal_result = MagicMock()

        mock_uxds.__getitem__.return_value = mock_var
        mock_var.dims = ("n_face",)
        mock_var.zonal_mean.return_value = mock_zonal_result

        mock_zonal_result.coords = {"latitudes": MagicMock()}
        mock_zonal_result.coords["latitudes"].values = np.array([-45, 0, 45])
        mock_zonal_result.values = np.array([278.0, 290.0, 278.0])

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300
        # Mock data_vars properly
        mock_data_vars = MagicMock()
        mock_data_vars.__contains__ = lambda self, key: key == "temperature"
        mock_uxds.data_vars = mock_data_vars

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = calculate_zonal_mean(
                "/grid.nc", "/data.nc", "temperature", lat_spec=[-45, 0, 45]
            )

            assert len(result["latitudes"]) == 3
            assert result["latitudes"] == [-45, 0, 45]

            # Verify lat_spec was passed
            mock_var.zonal_mean.assert_called_once_with(
                lat=[-45, 0, 45], conservative=False
            )

    def test_zonal_mean_grid_file_not_found(self):
        """Test error handling when grid file doesn't exist."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.side_effect = [False, True]

            with pytest.raises(FileNotFoundError, match="Grid file not found"):
                calculate_zonal_mean("/nonexistent_grid.nc", "/data.nc", "temperature")

    def test_zonal_mean_data_file_not_found(self):
        """Test error handling when data file doesn't exist."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.side_effect = [True, False]

            with pytest.raises(FileNotFoundError, match="Data file not found"):
                calculate_zonal_mean("/grid.nc", "/nonexistent_data.nc", "temperature")

    def test_zonal_mean_variable_not_found(self):
        """Test error handling when variable doesn't exist."""
        mock_uxds = MagicMock()
        mock_uxds.data_vars = MagicMock()
        mock_uxds.data_vars.__contains__ = lambda self, key: (
            key
            in [
                "pressure",
                "salinity",
            ]
        )
        mock_uxds.data_vars.keys.return_value = ["pressure", "salinity"]

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(ValueError, match="Variable 'temperature' not found"):
                calculate_zonal_mean("/grid.nc", "/data.nc", "temperature")

    def test_zonal_mean_not_face_centered(self):
        """Test error handling when variable is not face-centered."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_var.dims = ("n_node",)  # Node-centered, not face-centered

        mock_uxds.__getitem__.return_value = mock_var
        # Mock data_vars properly
        mock_data_vars = MagicMock()
        mock_data_vars.__contains__ = lambda self, key: key == "temperature"
        mock_uxds.data_vars = mock_data_vars

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(ValueError, match="not face-centered"):
                calculate_zonal_mean("/grid.nc", "/data.nc", "temperature")

    def test_zonal_mean_dataset_load_error(self):
        """Test error handling when dataset fails to load."""
        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", side_effect=Exception("Load error")),
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(RuntimeError, match="Failed to load dataset"):
                calculate_zonal_mean("/grid.nc", "/data.nc", "temperature")

    def test_zonal_mean_computation_error(self):
        """Test error handling when zonal mean computation fails."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()

        mock_uxds.__getitem__.return_value = mock_var
        mock_var.dims = ("n_face",)
        mock_var.zonal_mean.side_effect = Exception("Computation error")

        # Mock data_vars properly
        mock_data_vars = MagicMock()
        mock_data_vars.__contains__ = lambda self, key: key == "temperature"
        mock_uxds.data_vars = mock_data_vars

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(RuntimeError, match="Failed to compute zonal mean"):
                calculate_zonal_mean("/grid.nc", "/data.nc", "temperature")


class TestCalculateZonalMeanIntegration:
    """Integration tests for calculate_zonal_mean using real data."""

    def test_zonal_mean_with_synthetic_data(self, synthetic_mesh_with_data):
        """Integration test with synthetic mesh data."""
        grid_file, data_file = synthetic_mesh_with_data

        result = calculate_zonal_mean(grid_file, data_file, "temperature")

        assert result["variable_name"] == "temperature"
        assert "latitudes" in result
        assert "zonal_mean_values" in result
        assert len(result["latitudes"]) == len(result["zonal_mean_values"])
        assert result["conservative"] is False
        assert result["grid_info"]["n_face"] == 1
