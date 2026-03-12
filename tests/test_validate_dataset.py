import pytest
from unittest.mock import patch, MagicMock
import numpy as np
from uxarray_mcp.tools.inspection import validate_dataset


class TestValidateDataset:
    def test_validate_clean_dataset(self):
        """Test validation of a clean dataset with no issues."""
        mock_uxds = MagicMock()

        mock_temp = MagicMock()
        mock_temp.values = np.array([280.0, 285.0, 290.0, 295.0])
        mock_temp.attrs = {}
        mock_sal = MagicMock()
        mock_sal.values = np.array([32.0, 34.0, 36.0, 38.0])
        mock_sal.attrs = {}

        mock_uxds.data_vars = {"temperature": mock_temp, "salinity": mock_sal}
        mock_uxds.__getitem__ = (
            lambda self, key: mock_temp if key == "temperature" else mock_sal
        )

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", return_value=mock_uxds
        ):
            MockPath.return_value.exists.return_value = True
            result = validate_dataset("grid.nc", "data.nc")

            assert result["is_valid"] is True
            assert len(result["issues"]) == 0
            assert len(result["variables"]) == 2

            temp_result = next(
                v for v in result["variables"] if v["name"] == "temperature"
            )
            assert temp_result["has_nan"] is False
            assert temp_result["has_inf"] is False
            assert temp_result["nan_count"] == 0
            assert temp_result["total_values"] == 4
            assert temp_result["value_range"] == [280.0, 295.0]

    def test_validate_dataset_with_nan(self):
        """Test validation detects NaN values."""
        mock_uxds = MagicMock()

        mock_temp = MagicMock()
        mock_temp.values = np.array([280.0, np.nan, 290.0, 295.0])
        mock_temp.attrs = {}

        mock_uxds.data_vars = {"temperature": mock_temp}
        mock_uxds.__getitem__ = lambda self, key: mock_temp

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", return_value=mock_uxds
        ):
            MockPath.return_value.exists.return_value = True
            result = validate_dataset("grid.nc", "data.nc")

            assert result["is_valid"] is False
            assert len(result["issues"]) == 1
            assert "NaN" in result["issues"][0]

            temp_result = result["variables"][0]
            assert temp_result["has_nan"] is True
            assert temp_result["nan_count"] == 1
            assert temp_result["nan_percentage"] == 25.0

    def test_validate_dataset_with_inf(self):
        """Test validation detects Inf values."""
        mock_uxds = MagicMock()

        mock_temp = MagicMock()
        mock_temp.values = np.array([280.0, np.inf, 290.0, 295.0])
        mock_temp.attrs = {}

        mock_uxds.data_vars = {"temperature": mock_temp}
        mock_uxds.__getitem__ = lambda self, key: mock_temp

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", return_value=mock_uxds
        ):
            MockPath.return_value.exists.return_value = True
            result = validate_dataset("grid.nc", "data.nc")

            assert result["is_valid"] is False
            assert len(result["issues"]) == 1
            assert "Inf" in result["issues"][0]

            temp_result = result["variables"][0]
            assert temp_result["has_inf"] is True
            assert temp_result["inf_count"] == 1

    def test_validate_dataset_non_numeric(self):
        """Test validation skips non-numeric variables."""
        mock_uxds = MagicMock()

        mock_str_var = MagicMock()
        mock_str_var.values = np.array(["a", "b", "c"], dtype=object)
        mock_temp = MagicMock()
        mock_temp.values = np.array([280.0, 285.0, 290.0])
        mock_temp.attrs = {}

        mock_uxds.data_vars = {"labels": mock_str_var, "temperature": mock_temp}
        mock_uxds.__getitem__ = (
            lambda self, key: mock_str_var if key == "labels" else mock_temp
        )

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", return_value=mock_uxds
        ):
            MockPath.return_value.exists.return_value = True
            result = validate_dataset("grid.nc", "data.nc")

            assert len(result["variables"]) == 1
            assert result["variables"][0]["name"] == "temperature"

    def test_validate_dataset_grid_file_not_found(self):
        """Test error handling when grid file doesn't exist."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            mock_grid_path = MagicMock()
            mock_grid_path.exists.return_value = False
            mock_data_path = MagicMock()
            mock_data_path.exists.return_value = True

            def path_side_effect(arg):
                if "grid" in arg:
                    return mock_grid_path
                return mock_data_path

            MockPath.side_effect = path_side_effect

            with pytest.raises(FileNotFoundError, match="Grid file not found"):
                validate_dataset("grid.nc", "data.nc")

    def test_validate_dataset_data_file_not_found(self):
        """Test error handling when data file doesn't exist."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            mock_grid_path = MagicMock()
            mock_grid_path.exists.return_value = True
            mock_data_path = MagicMock()
            mock_data_path.exists.return_value = False

            def path_side_effect(arg):
                if "data" in arg:
                    return mock_data_path
                return mock_grid_path

            MockPath.side_effect = path_side_effect

            with pytest.raises(FileNotFoundError, match="Data file not found"):
                validate_dataset("grid.nc", "data.nc")

    def test_validate_dataset_load_error(self):
        """Test error handling when dataset fails to load."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", side_effect=Exception("Load failed")
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(RuntimeError, match="Failed to load dataset"):
                validate_dataset("grid.nc", "data.nc")

    def test_validate_dataset_with_fill_values(self):
        """Test detection of NetCDF fill values."""
        mock_uxds = MagicMock()

        mock_temp = MagicMock()
        mock_temp.values = np.array([280.0, 285.0, 9999.0, 295.0])
        mock_temp.attrs = {"_FillValue": 9999.0}

        mock_uxds.data_vars = {"temperature": mock_temp}
        mock_uxds.__getitem__ = lambda self, key: mock_temp

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", return_value=mock_uxds
        ):
            MockPath.return_value.exists.return_value = True
            result = validate_dataset("grid.nc", "data.nc")

            assert result["is_valid"] is False
            assert any("fill value" in issue for issue in result["issues"])

            temp_result = result["variables"][0]
            assert temp_result["fill_value_count"] == 1

    def test_validate_dataset_with_suspicious_fill_values(self):
        """Test detection of common fill value patterns."""
        mock_uxds = MagicMock()

        mock_temp = MagicMock()
        mock_temp.values = np.array([280.0, -9999.0, 290.0, 295.0])
        mock_temp.attrs = {}

        mock_uxds.data_vars = {"temperature": mock_temp}
        mock_uxds.__getitem__ = lambda self, key: mock_temp

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", return_value=mock_uxds
        ):
            MockPath.return_value.exists.return_value = True
            result = validate_dataset("grid.nc", "data.nc")

            assert result["is_valid"] is False
            temp_result = result["variables"][0]
            assert temp_result["suspicious_fill_count"] > 0

    def test_validate_dataset_invalid_latitude(self):
        """Test detection of out-of-range latitude values."""
        mock_uxds = MagicMock()

        mock_lat = MagicMock()
        mock_lat.values = np.array([-95.0, 0.0, 45.0, 90.0])
        mock_lat.attrs = {}

        mock_uxds.data_vars = {"latitude": mock_lat}
        mock_uxds.__getitem__ = lambda self, key: mock_lat

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", return_value=mock_uxds
        ):
            MockPath.return_value.exists.return_value = True
            result = validate_dataset("grid.nc", "data.nc")

            assert result["is_valid"] is False
            assert any(
                "latitude" in issue and "out of valid range" in issue
                for issue in result["issues"]
            )

            lat_result = result["variables"][0]
            assert lat_result["coordinate_issues"] is not None

    def test_validate_dataset_invalid_longitude(self):
        """Test detection of out-of-range longitude values."""
        mock_uxds = MagicMock()

        mock_lon = MagicMock()
        mock_lon.values = np.array([0.0, 180.0, 365.0, 270.0])
        mock_lon.attrs = {}

        mock_uxds.data_vars = {"longitude": mock_lon}
        mock_uxds.__getitem__ = lambda self, key: mock_lon

        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with patch("uxarray_mcp.tools.inspection.Path") as MockPath, patch(
            "uxarray.open_dataset", return_value=mock_uxds
        ):
            MockPath.return_value.exists.return_value = True
            result = validate_dataset("grid.nc", "data.nc")

            assert result["is_valid"] is False
            assert any(
                "longitude" in issue and "out of valid range" in issue
                for issue in result["issues"]
            )

            lon_result = result["variables"][0]
            assert lon_result["coordinate_issues"] is not None
