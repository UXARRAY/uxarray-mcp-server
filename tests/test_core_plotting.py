"""Pure render functions return PNG bytes plus render_info."""

from __future__ import annotations

import pytest

from uxarray_mcp.core import plotting
from uxarray_mcp.core.mesh import load_grid

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
RASTER_MODES = {"rasterized", "centers"}


def _assert_info(info, mode, width, height):
    assert info["render_mode"] == mode
    assert info["width"] == width and info["height"] == height
    assert info["n_faces_total"] >= info["n_faces_rendered"] > 0


class TestRenderMesh:
    def test_small_mesh_draws_polygons(self, structured_mesh_files):
        grid = load_grid(structured_mesh_files[0])
        png, info = plotting.render_mesh(grid, width=320, height=160)
        assert png.startswith(PNG_MAGIC)
        _assert_info(info, "polygons", 320, 160)
        assert info["n_faces_rendered"] == 162
        assert info["region"] == "global"

    def test_title_is_accepted(self, structured_mesh_files):
        grid = load_grid(structured_mesh_files[0])
        png, _ = plotting.render_mesh(grid, width=200, height=100, title="A mesh")
        assert png.startswith(PNG_MAGIC)

    def test_crop_reduces_rendered_faces(self, structured_mesh_files):
        grid = load_grid(structured_mesh_files[0])
        _, info = plotting.render_mesh(
            grid, width=200, height=100, lon_bounds=(0, 90), lat_bounds=(-30, 30)
        )
        assert info["region"] == "regional"
        assert 0 < info["n_faces_rendered"] < info["n_faces_total"] == 162

    def test_force_raster_uses_pixel_bounded_path(self, structured_mesh_files):
        grid = load_grid(structured_mesh_files[0])
        png, info = plotting.render_mesh(grid, width=256, height=128, force_raster=True)
        assert png.startswith(PNG_MAGIC)
        assert info["render_mode"] in RASTER_MODES
        if plotting.DATASHADER_AVAILABLE:
            assert info["render_mode"] == "rasterized"
        assert info["n_faces_total"] == 162

    def test_threshold_constant(self):
        assert plotting.RASTERIZE_ABOVE_FACES == 200_000
        assert plotting._wants_raster(plotting.RASTERIZE_ABOVE_FACES, False) is False
        assert plotting._wants_raster(plotting.RASTERIZE_ABOVE_FACES + 1, False) is True


class TestRenderVariable:
    def test_polygons_for_small_field(self, healpix_field_dataset):
        png, info = plotting.render_variable(
            healpix_field_dataset["temperature"], width=320, height=160, title="T"
        )
        assert png.startswith(PNG_MAGIC)
        _assert_info(info, "polygons", 320, 160)
        assert info["n_faces_total"] == 192
        assert info["reduced_dims"] == {}

    def test_force_raster(self, healpix_field_dataset):
        png, info = plotting.render_variable(
            healpix_field_dataset["temperature"],
            width=256,
            height=128,
            force_raster=True,
        )
        assert png.startswith(PNG_MAGIC)
        assert info["render_mode"] in RASTER_MODES

    def test_one_sided_clim_does_not_raise(self, healpix_field_dataset):
        png, _ = plotting.render_variable(
            healpix_field_dataset["u"], width=200, height=100, vmin=0.0, cmap="RdBu_r"
        )
        assert png.startswith(PNG_MAGIC)


class TestOtherRenders:
    def test_zonal_mean_profile(self):
        png, info = plotting.render_zonal_mean([-60, 0, 60], [1.0, 2.0, 1.5], "t")
        assert png.startswith(PNG_MAGIC)
        assert info["render_mode"] == "line" and info["n_points"] == 3

    @pytest.mark.filterwarnings("ignore")
    def test_mesh_geo_reports_what_it_drew(self, structured_mesh_files):
        pytest.importorskip("cartopy")
        grid = load_grid(structured_mesh_files[0])
        png, info = plotting.render_mesh_geo(grid, width=300, height=200, borders=False)
        assert png.startswith(PNG_MAGIC)
        assert info["render_mode"] == "polygons"
        assert info["n_faces_total"] == 162
        assert "coastlines" in info["features_drawn"]
        assert info["boundary_status"] == "disabled"
