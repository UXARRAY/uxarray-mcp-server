from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from uxarray_mcp.tools import inspect_variable

# -----------------------------------------------------------------------------
# Unit Tests (Mocked)
# -----------------------------------------------------------------------------


class TestInspectVariableBasic:
    """Tests for basic inspect_variable functionality using mocks."""

    def test_inspect_single_variable(self):
        """Test inspection of a single variable."""
        # Mock dataset
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_var.dims = ("n_face",)
        mock_var.shape = (100,)
        mock_var.dtype = np.dtype("float64")
        mock_var.attrs = {"units": "K", "long_name": "Temperature"}
        mock_var.values = np.array([270.0, 280.0, 290.0])

        mock_uxds.data_vars = {"temperature": mock_var}
        mock_uxds.__getitem__ = lambda self, key: mock_var
        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = inspect_variable("/grid.nc", "/data.nc", "temperature")

            assert len(result["variables"]) == 1
            var = result["variables"][0]
            assert var["name"] == "temperature"
            assert var["dims"] == ("n_face",)
            assert var["shape"] == (100,)
            assert var["dtype"] == "float64"
            assert var["location"] == "faces"
            assert var["attrs"]["units"] == "K"
            assert "statistics" in var
            assert var["statistics"]["min"] == 270.0

    def test_inspect_all_variables(self):
        """Test inspection of all variables in a dataset."""
        # Mock dataset with multiple variables
        mock_uxds = MagicMock()

        mock_temp = MagicMock()
        mock_temp.dims = ("n_face",)
        mock_temp.shape = (100,)
        mock_temp.dtype = np.dtype("float64")
        mock_temp.attrs = {"units": "K"}
        mock_temp.values = np.array([270.0, 280.0, 290.0])

        mock_sal = MagicMock()
        mock_sal.dims = ("n_node",)
        mock_sal.shape = (200,)
        mock_sal.dtype = np.dtype("float32")
        mock_sal.attrs = {"units": "PSU"}
        mock_sal.values = np.array([32.0, 34.0, 36.0])

        mock_uxds.data_vars = {"temperature": mock_temp, "salinity": mock_sal}
        mock_uxds.__getitem__ = lambda self, key: (
            mock_temp if key == "temperature" else mock_sal
        )
        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = inspect_variable("/grid.nc", "/data.nc")

            assert len(result["variables"]) == 2
            assert result["variables"][0]["name"] == "temperature"
            assert result["variables"][1]["name"] == "salinity"

    def test_variable_on_faces(self):
        """Test detection of face-centered data."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_var.dims = ("n_face", "n_level")
        mock_var.shape = (100, 10)
        mock_var.dtype = np.dtype("float64")
        mock_var.attrs = {}
        mock_var.values = np.random.rand(100, 10)

        mock_uxds.data_vars = {"var": mock_var}
        mock_uxds.__getitem__ = lambda self, key: mock_var
        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = inspect_variable("/grid.nc", "/data.nc", "var")

            assert result["variables"][0]["location"] == "faces"

    def test_variable_on_nodes(self):
        """Test detection of node-centered data."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_var.dims = ("n_node",)
        mock_var.shape = (200,)
        mock_var.dtype = np.dtype("float64")
        mock_var.attrs = {}
        mock_var.values = np.random.rand(200)

        mock_uxds.data_vars = {"var": mock_var}
        mock_uxds.__getitem__ = lambda self, key: mock_var
        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = inspect_variable("/grid.nc", "/data.nc", "var")

            assert result["variables"][0]["location"] == "nodes"

    def test_variable_on_edges(self):
        """Test detection of edge-centered data."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_var.dims = ("n_edge",)
        mock_var.shape = (300,)
        mock_var.dtype = np.dtype("float64")
        mock_var.attrs = {}
        mock_var.values = np.random.rand(300)

        mock_uxds.data_vars = {"var": mock_var}
        mock_uxds.__getitem__ = lambda self, key: mock_var
        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = inspect_variable("/grid.nc", "/data.nc", "var")

            assert result["variables"][0]["location"] == "edges"

    def test_statistics_numeric(self):
        """Test statistics computation for numeric variables."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_var.dims = ("n_face",)
        mock_var.shape = (5,)
        mock_var.dtype = np.dtype("float64")
        mock_var.attrs = {}
        mock_var.values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])

        mock_uxds.data_vars = {"var": mock_var}
        mock_uxds.__getitem__ = lambda self, key: mock_var
        mock_uxds.uxgrid.n_face = 5
        mock_uxds.uxgrid.n_node = 10
        mock_uxds.uxgrid.n_edge = 15

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = inspect_variable("/grid.nc", "/data.nc", "var")

            stats = result["variables"][0]["statistics"]
            assert stats is not None
            assert stats["min"] == 1.0
            assert stats["max"] == 5.0
            assert stats["mean"] == 3.0

    def test_statistics_non_numeric(self):
        """Test handling of non-numeric variables."""
        mock_uxds = MagicMock()
        mock_var = MagicMock()
        mock_var.dims = ("n_face",)
        mock_var.shape = (5,)
        mock_var.dtype = np.dtype("object")
        mock_var.attrs = {}
        mock_var.values = np.array(["a", "b", "c", "d", "e"])

        mock_uxds.data_vars = {"var": mock_var}
        mock_uxds.__getitem__ = lambda self, key: mock_var
        mock_uxds.uxgrid.n_face = 5
        mock_uxds.uxgrid.n_node = 10
        mock_uxds.uxgrid.n_edge = 15

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            result = inspect_variable("/grid.nc", "/data.nc", "var")

            stats = result["variables"][0]["statistics"]
            assert stats is None


class TestInspectVariableErrorHandling:
    """Tests for error handling and edge cases."""

    def test_grid_file_not_found(self):
        """Test handling of non-existent grid file."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.side_effect = [False, True]

            with pytest.raises(FileNotFoundError, match="Grid file not found"):
                inspect_variable("/nonexistent_grid.nc", "/data.nc")

    def test_data_file_not_found(self):
        """Test handling of non-existent data file."""
        with patch("uxarray_mcp.tools.inspection.Path") as MockPath:
            MockPath.return_value.exists.side_effect = [True, False]

            with pytest.raises(FileNotFoundError, match="Data file not found"):
                inspect_variable("/grid.nc", "/nonexistent_data.nc")

    def test_variable_not_found(self):
        """Test handling of invalid variable name."""
        mock_uxds = MagicMock()
        mock_data_vars = MagicMock()
        mock_data_vars.__contains__ = lambda self, key: (
            key
            in [
                "temperature",
                "salinity",
            ]
        )
        mock_data_vars.keys.return_value = ["temperature", "salinity"]

        mock_uxds.data_vars = mock_data_vars

        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", return_value=mock_uxds),
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(ValueError, match="Variable 'pressure' not found"):
                inspect_variable("/grid.nc", "/data.nc", "pressure")

    def test_dataset_loading_error(self):
        """Test handling of dataset loading errors."""
        with (
            patch("uxarray_mcp.tools.inspection.Path") as MockPath,
            patch("uxarray.open_dataset", side_effect=Exception("Load error")),
        ):
            MockPath.return_value.exists.return_value = True

            with pytest.raises(RuntimeError, match="Failed to load dataset"):
                inspect_variable("/grid.nc", "/data.nc")


# -----------------------------------------------------------------------------
# Integration Tests (Real Data)
# -----------------------------------------------------------------------------


def test_inspect_variable_integration(synthetic_mesh_with_data):
    """
    Integration test using a real synthetic dataset.
    Verifies that the tool actually works with uxarray reading real files.
    """
    grid_file, data_file = synthetic_mesh_with_data

    result = inspect_variable(grid_file, data_file)

    # Should have at least one variable
    assert len(result["variables"]) > 0

    # Check grid info is present
    assert "grid_info" in result
    assert result["grid_info"]["n_face"] > 0

    # Check variable structure
    var = result["variables"][0]
    assert "name" in var
    assert "dims" in var
    assert "shape" in var
    assert "dtype" in var
    assert "location" in var
    assert "attrs" in var
