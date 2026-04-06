"""Tests for plotting tools and domain rendering functions."""

import base64
from unittest.mock import MagicMock, patch

import pytest

from uxarray_mcp.domain.plotting import render_zonal_mean
from uxarray_mcp.tools.plotting import plot_mesh, plot_variable, plot_zonal_mean

# -----------------------------------------------------------------------------
# Domain Layer Tests (render functions)
# -----------------------------------------------------------------------------


class TestRenderZonalMean:
    """Tests for the render_zonal_mean domain function (pure matplotlib, no UXarray)."""

    def test_returns_png_bytes(self):
        lats = [-90.0, -60.0, -30.0, 0.0, 30.0, 60.0, 90.0]
        vals = [270.0, 280.0, 290.0, 300.0, 290.0, 280.0, 270.0]
        result = render_zonal_mean(lats, vals, "temperature")
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes

    def test_custom_dimensions(self):
        lats = [-90.0, 0.0, 90.0]
        vals = [250.0, 300.0, 250.0]
        result = render_zonal_mean(lats, vals, "temp", width=400, height=300)
        assert isinstance(result, bytes)
        assert len(result) > 0


# -----------------------------------------------------------------------------
# Tool Layer Tests — plot_mesh (mocked)
# -----------------------------------------------------------------------------


class TestPlotMeshMocked:
    """Tests for plot_mesh tool using mocks."""

    @patch("uxarray_mcp.tools.plotting.render_mesh", return_value=b"\x89PNG_fake_data")
    @patch("uxarray_mcp.tools.plotting.load_grid")
    def test_plot_mesh_basic(self, mock_load_grid, mock_render):
        mock_grid = MagicMock()
        mock_grid.n_face = 100
        mock_grid.n_node = 200
        mock_grid.n_edge = 300
        mock_load_grid.return_value = mock_grid

        result = plot_mesh("healpix:2")

        assert "image" in result
        assert result["image"].startswith("data:image/png;base64,")
        assert result["image_size_bytes"] == len(b"\x89PNG_fake_data")
        assert result["grid_info"]["n_face"] == 100
        assert "_provenance" in result
        assert result["_provenance"]["tool"] == "plot_mesh"

    @patch("uxarray_mcp.tools.plotting.render_mesh", return_value=b"\x89PNG_fake")
    @patch("uxarray_mcp.tools.plotting.load_grid")
    def test_plot_mesh_custom_dimensions(self, mock_load_grid, mock_render):
        mock_grid = MagicMock()
        mock_grid.n_face = 50
        mock_grid.n_node = 100
        mock_grid.n_edge = 150
        mock_load_grid.return_value = mock_grid

        result = plot_mesh("healpix:1", width=400, height=300)

        mock_render.assert_called_once_with(mock_grid, width=400, height=300)
        assert result["_provenance"]["inputs"]["width"] == 400


class TestPlotMeshErrors:
    """Tests for plot_mesh error handling."""

    @patch(
        "uxarray_mcp.tools.plotting.load_grid",
        side_effect=FileNotFoundError("not found"),
    )
    def test_file_not_found(self, mock_load):
        with pytest.raises(FileNotFoundError):
            plot_mesh("/nonexistent.nc")


# -----------------------------------------------------------------------------
# Tool Layer Tests — plot_variable (mocked)
# -----------------------------------------------------------------------------


class TestPlotVariableMocked:
    """Tests for plot_variable tool using mocks."""

    @patch("uxarray_mcp.tools.plotting.render_variable", return_value=b"\x89PNG_var")
    @patch("uxarray_mcp.tools.plotting.ux")
    def test_plot_variable_auto_select(self, mock_ux, mock_render):
        mock_var = MagicMock()
        mock_var.dims = ("n_face",)
        mock_uxds = MagicMock()
        mock_uxds.data_vars = ["temperature"]
        mock_uxds.__getitem__ = lambda self, key: mock_var
        mock_uxds.uxgrid.n_face = 100
        mock_uxds.uxgrid.n_node = 200
        mock_uxds.uxgrid.n_edge = 300
        mock_ux.open_dataset.return_value = mock_uxds

        with patch("uxarray_mcp.tools.plotting.Path") as MockPath:
            MockPath.return_value.exists.return_value = True

            result = plot_variable("grid.nc", "data.nc")

            assert "image" in result
            assert result["variable_name"] == "temperature"
            assert result["_provenance"]["tool"] == "plot_variable"

    def test_data_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="Data file not found"):
            plot_variable("healpix:2", "/nonexistent/data.nc")


# -----------------------------------------------------------------------------
# Tool Layer Tests — plot_zonal_mean (mocked)
# -----------------------------------------------------------------------------


class TestPlotZonalMeanMocked:
    """Tests for plot_zonal_mean tool using mocks."""

    @patch("uxarray_mcp.tools.plotting.render_zonal_mean", return_value=b"\x89PNG_zm")
    @patch("uxarray_mcp.tools.plotting.ux")
    def test_plot_zonal_mean_basic(self, mock_ux, mock_render):
        mock_uxds = MagicMock()
        mock_ux.open_dataset.return_value = mock_uxds

        zonal_stats = {
            "latitudes": [-90.0, 0.0, 90.0],
            "zonal_mean_values": [270.0, 300.0, 270.0],
        }

        with (
            patch("uxarray_mcp.tools.plotting.Path") as MockPath,
            patch(
                "uxarray_mcp.tools.plotting.compute_zonal_mean_stats",
                return_value=zonal_stats,
            ),
        ):
            MockPath.return_value.exists.return_value = True

            result = plot_zonal_mean("grid.nc", "data.nc", "temperature")

            assert "image" in result
            assert result["variable_name"] == "temperature"
            assert result["latitudes"] == [-90.0, 0.0, 90.0]
            assert result["_provenance"]["tool"] == "plot_zonal_mean"


# -----------------------------------------------------------------------------
# Integration Tests (Real Data — HEALPix)
# -----------------------------------------------------------------------------


class TestPlotMeshIntegration:
    """Integration tests using real HEALPix mesh."""

    def test_plot_mesh_healpix(self):
        result = plot_mesh("healpix:2")

        assert result["image"].startswith("data:image/png;base64,")
        assert result["image_size_bytes"] > 1000
        assert result["grid_info"]["n_face"] == 192
        assert "_provenance" in result

        b64_data = result["image"].split(",", 1)[1]
        png_bytes = base64.b64decode(b64_data)
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_plot_mesh_healpix_custom_size(self):
        result = plot_mesh("healpix:1", width=400, height=200)
        assert result["image_size_bytes"] > 0
        assert result["grid_info"]["n_face"] == 48
