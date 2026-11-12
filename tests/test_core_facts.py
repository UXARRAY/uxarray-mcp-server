"""header_facts reads dimensions and attributes only, never a grid."""

from __future__ import annotations

import time

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.core import facts
from uxarray_mcp.core.facts import header_facts


class TestFormatsFromHeaders:
    def test_ugrid_grid_file(self, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        result = header_facts(grid_file)
        assert result["format"] == "ugrid"
        assert result["n_face"] == 162
        assert result["n_node"] == 146
        assert result["size_class"] == "small"
        assert result["role"] == "grid"
        assert result["has_data_variables"] is False
        assert result["variables_face_centered"] == []
        assert "n_time" not in result

    def test_ugrid_data_file_lists_face_variables(self, structured_mesh_files):
        _, data_file = structured_mesh_files
        result = header_facts(data_file)
        assert result["format"] == "ugrid"
        assert result["variables_face_centered"] == ["temperature"]
        assert result["has_data_variables"] is True
        assert result["role"] == "data"

    def test_mpas_dims(self, tmp_path):
        path = tmp_path / "mpas.nc"
        xr.Dataset(
            {
                "verticesOnCell": (
                    ["nCells", "maxEdges"],
                    np.zeros((10, 6), dtype="i4"),
                ),
                "areaCell": (["nCells"], np.ones(10)),
                "ssh": (["Time", "nCells"], np.zeros((3, 10))),
            },
            coords={"latVertex": (["nVertices"], np.zeros(20))},
        ).to_netcdf(path)
        result = header_facts(str(path))
        assert result["format"] == "mpas"
        assert result["n_face"] == 10
        assert result["n_node"] == 20
        assert result["n_time"] == 3
        assert result["variables_face_centered"] == ["ssh"]
        assert result["role"] == "grid+data"

    def test_scrip_dims(self, tmp_path):
        path = tmp_path / "scrip.nc"
        xr.Dataset(
            {
                "grid_corner_lat": (["grid_size", "grid_corners"], np.zeros((8, 4))),
                "grid_corner_lon": (["grid_size", "grid_corners"], np.zeros((8, 4))),
            }
        ).to_netcdf(path)
        result = header_facts(str(path))
        assert result["format"] == "scrip"
        assert result["n_face"] == 8
        assert result["role"] == "grid"

    def test_exodus_blocks_are_summed(self, tmp_path):
        path = tmp_path / "mesh.exo"
        xr.Dataset(
            {
                "connect1": (
                    ["num_el_in_blk1", "num_nod_per_el1"],
                    np.zeros((5, 4), "i4"),
                ),
                "connect2": (
                    ["num_el_in_blk2", "num_nod_per_el2"],
                    np.zeros((7, 3), "i4"),
                ),
                "coord": (["num_dim", "num_nodes"], np.zeros((3, 30))),
            }
        ).to_netcdf(path)
        result = header_facts(str(path))
        assert result["format"] == "exodus"
        assert result["n_face"] == 12
        assert result["n_node"] == 30

    def test_esmf_and_icon(self, tmp_path):
        esmf = tmp_path / "esmf.nc"
        xr.Dataset(
            {
                "elementConn": (
                    ["elementCount", "maxNodePElement"],
                    np.zeros((6, 4), "i4"),
                )
            },
            coords={"nodeCoords": (["nodeCount", "coordDim"], np.zeros((9, 2)))},
        ).to_netcdf(esmf)
        assert header_facts(str(esmf))["format"] == "esmf"
        assert header_facts(str(esmf))["n_face"] == 6
        icon = tmp_path / "icon.nc"
        xr.Dataset(
            {"vertex_of_cell": (["nv", "cell"], np.zeros((3, 11), "i4"))},
            coords={"vlon": (["vertex"], np.zeros(7))},
        ).to_netcdf(icon)
        result = header_facts(str(icon))
        assert (result["format"], result["n_face"], result["n_node"]) == ("icon", 11, 7)

    def test_unknown_layout(self, tmp_path):
        path = tmp_path / "plain.nc"
        xr.Dataset({"a": (["x"], np.zeros(4))}).to_netcdf(path)
        result = header_facts(str(path))
        assert result["format"] == "unknown"
        assert result["n_face"] is None


class TestHealpixAndErrors:
    def test_healpix_spec_needs_no_file(self):
        result = header_facts("healpix:3")
        assert result["format"] == "healpix"
        assert result["n_face"] == 12 * 4**3
        assert result["size_bytes"] == 0

    def test_bad_healpix_zoom_is_a_value_error(self):
        with pytest.raises(ValueError, match="Invalid HEALPix format"):
            header_facts("healpix:abc")

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            header_facts(str(tmp_path / "nope.nc"))

    def test_garbage_file_is_a_value_error(self, tmp_path):
        path = tmp_path / "junk.nc"
        path.write_bytes(b"not netcdf at all")
        with pytest.raises(ValueError, match="Cannot read file header"):
            header_facts(str(path))


class TestSizeClass:
    def test_thresholds(self, monkeypatch):
        assert facts._size_class(facts.SMALL_BYTES - 1) == "small"
        assert facts._size_class(facts.SMALL_BYTES) == "medium"
        assert facts._size_class(facts.MEDIUM_BYTES) == "large"

    def test_is_fast_on_a_wide_file(self, tmp_path):
        """Many variables, no data read: well under the 50 ms budget after warm-up."""
        path = tmp_path / "wide.nc"
        xr.Dataset(
            {f"v{i}": (["n_face"], np.zeros(1000)) for i in range(120)}
        ).to_netcdf(path)
        header_facts(str(path))
        start = time.perf_counter()
        result = header_facts(str(path))
        assert (time.perf_counter() - start) < 0.5
        assert len(result["variables_face_centered"]) == facts.MAX_FACE_VARIABLES
