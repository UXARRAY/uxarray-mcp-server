"""Tests for plotting tools and domain rendering functions."""

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from uxarray_mcp.domain.plotting import render_zonal_mean
from uxarray_mcp.tools.plotting import plot_mesh, plot_variable, plot_zonal_mean
from uxarray_mcp.tools.remote_tools import (
    plot_mesh_hpc,
    plot_variable_hpc,
    plot_zonal_mean_hpc,
)

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

    def test_custom_line_color(self):
        lats = [-90.0, 0.0, 90.0]
        vals = [270.0, 300.0, 270.0]
        result = render_zonal_mean(lats, vals, "temp", line_color="red")
        assert isinstance(result, bytes)
        assert result[:8] == b"\x89PNG\r\n\x1a\n"

    def test_custom_title(self):
        lats = [-90.0, 0.0, 90.0]
        vals = [270.0, 300.0, 270.0]
        result = render_zonal_mean(lats, vals, "temp", title="My Custom Title")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_empty_bytes_raises(self):
        """render_zonal_mean should raise if savefig produces empty output."""
        lats = [-90.0, 0.0, 90.0]
        vals = [270.0, 300.0, 270.0]
        with patch("uxarray_mcp.domain.plotting.plt") as mock_plt:
            mock_fig = MagicMock()
            mock_ax = MagicMock()
            mock_plt.subplots.return_value = (mock_fig, mock_ax)
            mock_fig.savefig.side_effect = lambda buf, **kw: None  # writes nothing
            with pytest.raises(ValueError, match="empty"):
                render_zonal_mean(lats, vals, "temp")


class TestRenderEmptyBytesGuard:
    """Test the post-render empty-bytes guard in domain rendering functions."""

    def test_render_zonal_mean_empty_raises(self):
        """render_zonal_mean raises ValueError when savefig produces no bytes."""
        lats = [-90.0, 0.0, 90.0]
        vals = [270.0, 300.0, 270.0]
        with patch("uxarray_mcp.domain.plotting.plt") as mock_plt:
            mock_fig = MagicMock()
            mock_ax = MagicMock()
            mock_plt.subplots.return_value = (mock_fig, mock_ax)
            mock_fig.savefig.side_effect = lambda buf, **kw: None  # writes nothing
            with pytest.raises(ValueError, match="empty"):
                render_zonal_mean(lats, vals, "temp")


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

        assert len(result) == 2
        assert result[0].type == "image"
        assert (
            result[0].data.startswith("iVBORw0K")
            or result[0].data.startswith("data:image/")
            or "PNG" in base64.b64decode(result[0].data)[:8].decode("utf-8", "ignore")
        )

        import json

        prov = json.loads(result[1].text)
        assert prov["image_size_bytes"] == len(b"\x89PNG_fake_data")
        assert prov["grid_info"]["n_face"] == 100
        assert "_provenance" in prov
        assert prov["_provenance"]["tool"] == "plot_mesh"

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
        import json

        prov = json.loads(result[1].text)
        assert prov["_provenance"]["inputs"]["width"] == 400


class TestPlotMeshErrors:
    """Tests for plot_mesh error handling."""

    @patch(
        "uxarray_mcp.tools.plotting.load_grid",
        side_effect=FileNotFoundError("not found"),
    )
    def test_file_not_found(self, mock_load):
        with pytest.raises(FileNotFoundError):
            plot_mesh("/nonexistent.nc")

    def test_empty_file_raises(self):
        """plot_mesh should raise ValueError for a zero-byte file."""
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as f:
            empty_path = f.name  # file is created but empty
        try:
            with pytest.raises(ValueError, match="empty"):
                plot_mesh(empty_path)
        finally:
            Path(empty_path).unlink(missing_ok=True)


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

            assert len(result) == 2
            assert result[0].type == "image"

            import json

            prov = json.loads(result[1].text)
            assert prov["variable_name"] == "temperature"
            assert prov["_provenance"]["tool"] == "plot_variable"

    def test_data_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="Data file not found"):
            plot_variable("healpix:2", "/nonexistent/data.nc")

    def test_empty_data_file_raises(self):
        """plot_variable should raise ValueError for a zero-byte data file."""
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as f:
            empty_path = f.name
        try:
            with pytest.raises(ValueError, match="empty"):
                plot_variable("healpix:2", empty_path)
        finally:
            Path(empty_path).unlink(missing_ok=True)

    @patch("uxarray_mcp.tools.plotting.render_variable", return_value=b"\x89PNG_var")
    @patch("uxarray_mcp.tools.plotting.ux")
    def test_plot_variable_vmin_vmax(self, mock_ux, mock_render):
        """vmin/vmax are passed through to render_variable."""
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
            MockPath.return_value.stat.return_value.st_size = 1000

            plot_variable("grid.nc", "data.nc", vmin=-5.0, vmax=5.0)

            mock_render.assert_called_once()
            _, kwargs = mock_render.call_args
            assert kwargs["vmin"] == -5.0
            assert kwargs["vmax"] == 5.0

    @patch("uxarray_mcp.tools.plotting.render_variable", return_value=b"\x89PNG_var")
    @patch("uxarray_mcp.tools.plotting.ux")
    def test_plot_variable_custom_title(self, mock_ux, mock_render):
        """title is passed through to render_variable."""
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
            MockPath.return_value.stat.return_value.st_size = 1000

            plot_variable("grid.nc", "data.nc", title="My Title")

            _, kwargs = mock_render.call_args
            assert kwargs["title"] == "My Title"


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
            MockPath.return_value.stat.return_value.st_size = 1000

            result = plot_zonal_mean("grid.nc", "data.nc", "temperature")

            assert len(result) == 2
            assert result[0].type == "image"

            import json

            prov = json.loads(result[1].text)
            assert prov["variable_name"] == "temperature"
            assert prov["latitudes"] == [-90.0, 0.0, 90.0]
            assert prov["_provenance"]["tool"] == "plot_zonal_mean"

    @patch("uxarray_mcp.tools.plotting.render_zonal_mean", return_value=b"\x89PNG_zm")
    @patch("uxarray_mcp.tools.plotting.ux")
    def test_plot_zonal_mean_line_color_and_title(self, mock_ux, mock_render):
        """line_color and title are passed through to render_zonal_mean."""
        mock_ux.open_dataset.return_value = MagicMock()
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
            MockPath.return_value.stat.return_value.st_size = 1000

            plot_zonal_mean(
                "grid.nc",
                "data.nc",
                "temperature",
                line_color="darkorange",
                title="Custom Title",
            )

            _, kwargs = mock_render.call_args
            assert kwargs["line_color"] == "darkorange"
            assert kwargs["title"] == "Custom Title"

    def test_empty_data_file_raises(self):
        """plot_zonal_mean should raise ValueError for a zero-byte data file."""
        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as f:
            empty_path = f.name
        try:
            with pytest.raises(ValueError, match="empty"):
                plot_zonal_mean("healpix:2", empty_path, "temperature")
        finally:
            Path(empty_path).unlink(missing_ok=True)


# -----------------------------------------------------------------------------
# Integration Tests (Real Data — HEALPix)
# -----------------------------------------------------------------------------


class TestPlotMeshIntegration:
    """Integration tests using real HEALPix mesh."""

    def test_plot_mesh_healpix(self):
        result = plot_mesh("healpix:2")

        assert len(result) == 2
        assert result[0].type == "image"

        import json

        prov = json.loads(result[1].text)
        assert prov["image_size_bytes"] > 1000
        assert prov["grid_info"]["n_face"] == 192
        assert "_provenance" in prov

        png_bytes = base64.b64decode(result[0].data)
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_plot_mesh_healpix_custom_size(self):
        result = plot_mesh("healpix:1", width=400, height=200)
        import json

        prov = json.loads(result[1].text)
        assert prov["image_size_bytes"] > 0
        assert prov["grid_info"]["n_face"] == 48


class TestHpcPlotWrappers:
    """HPC plot wrappers should preserve the inline plot UX."""

    @patch("uxarray_mcp.tools.remote_tools._run_with_optional_hpc")
    def test_plot_mesh_hpc_returns_image_content(self, mock_run):
        mock_run.return_value = {
            "png_b64": base64.b64encode(b"\x89PNG_fake").decode("utf-8"),
            "image_size_bytes": 9,
            "grid_info": {"n_face": 192},
            "_provenance": {"execution_venue": "local", "warnings": []},
        }

        result = plot_mesh_hpc("healpix:2")

        assert len(result) == 2
        assert result[0].type == "image"
        metadata = json.loads(result[1].text)
        assert metadata["image_size_bytes"] == 9
        assert "png_b64" not in metadata

    @patch("uxarray_mcp.tools.remote_tools._run_with_optional_hpc")
    def test_plot_variable_hpc_returns_image_content(self, mock_run):
        mock_run.return_value = {
            "png_b64": base64.b64encode(b"\x89PNG_fake").decode("utf-8"),
            "image_size_bytes": 9,
            "variable_name": "temperature",
            "grid_info": {"n_face": 192},
            "_provenance": {"execution_venue": "local", "warnings": []},
        }

        result = plot_variable_hpc("grid.nc", "data.nc", "temperature")

        assert len(result) == 2
        assert result[0].type == "image"
        metadata = json.loads(result[1].text)
        assert metadata["variable_name"] == "temperature"
        assert "png_b64" not in metadata

    @patch("uxarray_mcp.tools.remote_tools._run_with_optional_hpc")
    def test_plot_zonal_mean_hpc_returns_image_content(self, mock_run):
        mock_run.return_value = {
            "png_b64": base64.b64encode(b"\x89PNG_fake").decode("utf-8"),
            "image_size_bytes": 9,
            "variable_name": "temperature",
            "latitudes": [-90.0, 0.0, 90.0],
            "zonal_mean_values": [270.0, 300.0, 270.0],
            "_provenance": {"execution_venue": "local", "warnings": []},
        }

        result = plot_zonal_mean_hpc("grid.nc", "data.nc", "temperature")

        assert len(result) == 2
        assert result[0].type == "image"
        metadata = json.loads(result[1].text)
        assert metadata["latitudes"] == [-90.0, 0.0, 90.0]
        assert "png_b64" not in metadata


class TestHpcPlotWrappersDatasetHandle:
    """Issue #25: HPC plot wrappers must accept session_id + dataset_handle and
    resolve the grid/data paths from the session before dispatching."""

    @staticmethod
    def _stub_run_result(extra: dict | None = None) -> dict:
        return {
            "png_b64": base64.b64encode(b"\x89PNG_fake").decode("utf-8"),
            "image_size_bytes": 9,
            "grid_info": {"n_face": 1},
            "_provenance": {"execution_venue": "local", "warnings": []},
            **(extra or {}),
        }

    @patch("uxarray_mcp.tools.remote_tools._run_with_optional_hpc")
    def test_plot_mesh_hpc_resolves_dataset_handle(
        self, mock_run, synthetic_mesh_with_data
    ):
        from uxarray_mcp.tools import create_session, register_dataset

        grid_file, _ = synthetic_mesh_with_data
        session = create_session("plot-mesh-hpc-handle")
        registered = register_dataset(
            session_id=session["session_id"],
            grid_path=grid_file,
            name="grid-only",
        )

        mock_run.return_value = self._stub_run_result()

        plot_mesh_hpc(
            session_id=session["session_id"],
            dataset_handle=registered["dataset_handle"],
        )

        kwargs = mock_run.call_args.kwargs
        assert kwargs["path_hint"] == grid_file

    @patch("uxarray_mcp.tools.remote_tools._run_with_optional_hpc")
    def test_plot_variable_hpc_resolves_dataset_handle(
        self, mock_run, synthetic_mesh_with_data
    ):
        from uxarray_mcp.tools import create_session, register_dataset

        grid_file, data_file = synthetic_mesh_with_data
        session = create_session("plot-variable-hpc-handle")
        registered = register_dataset(
            session_id=session["session_id"],
            grid_path=grid_file,
            data_path=data_file,
            name="grid-and-data",
        )

        mock_run.return_value = self._stub_run_result({"variable_name": "temperature"})

        plot_variable_hpc(
            variable_name="temperature",
            session_id=session["session_id"],
            dataset_handle=registered["dataset_handle"],
        )

        kwargs = mock_run.call_args.kwargs
        assert kwargs["path_hint"] == grid_file

    @patch("uxarray_mcp.tools.remote_tools._run_with_optional_hpc")
    def test_plot_zonal_mean_hpc_resolves_dataset_handle(
        self, mock_run, synthetic_mesh_with_data
    ):
        from uxarray_mcp.tools import create_session, register_dataset

        grid_file, data_file = synthetic_mesh_with_data
        session = create_session("plot-zonal-hpc-handle")
        registered = register_dataset(
            session_id=session["session_id"],
            grid_path=grid_file,
            data_path=data_file,
            name="zonal-handle",
        )

        mock_run.return_value = self._stub_run_result(
            {
                "variable_name": "temperature",
                "latitudes": [-90.0, 0.0, 90.0],
                "zonal_mean_values": [270.0, 300.0, 270.0],
            }
        )

        plot_zonal_mean_hpc(
            variable_name="temperature",
            session_id=session["session_id"],
            dataset_handle=registered["dataset_handle"],
        )

        kwargs = mock_run.call_args.kwargs
        assert kwargs["path_hint"] == grid_file

    def test_plot_mesh_hpc_handle_without_session_raises(self):
        """dataset_handle without session_id is a clear ValueError."""
        with pytest.raises(ValueError, match="session_id is required"):
            plot_mesh_hpc(dataset_handle="some-handle")

    def test_plot_mesh_hpc_no_path_no_handle_raises(self):
        """At least one of grid_path or dataset_handle must be provided."""
        with pytest.raises(ValueError, match="grid_path is required"):
            plot_mesh_hpc()
