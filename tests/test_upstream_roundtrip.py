"""Two uxarray defects that make a written grid unreadable, and our repair.

Both were found while measuring a grid cache that was ultimately dropped: of
three real meshes, only one survived a write-then-reopen. The cache is parked;
these do not depend on it. Neither defect is in ``Grid.to_xarray`` itself --
that call succeeds in both cases and hands back a dataset that cannot be
written, or can be written and not read.

The ``xfail(strict=True)`` cases below are the upstream behaviour. When
uxarray fixes either one they turn into XPASS failures, which is the signal to
delete the corresponding repair in ``state.py``.
"""

from __future__ import annotations

import numpy as np
import pytest
import xarray as xr

from tests.conftest import UXARRAY_IS_MOCKED

pytestmark = pytest.mark.skipif(
    UXARRAY_IS_MOCKED, reason="reading and writing real meshes needs a real uxarray"
)

INT64_FILL = np.iinfo(np.int64).min


@pytest.fixture(autouse=True)
def restore_topology_template():
    """Put uxarray's shared attribute template back after every test here.

    Defect B works by mutating a module-level dict, so exporting a grid in one
    test changes what a later test in the same process writes. Contained to
    this file rather than fixed globally: the leak is the thing under test.
    """
    from uxarray.conventions.ugrid import BASE_GRID_TOPOLOGY_ATTRS

    pristine = dict(BASE_GRID_TOPOLOGY_ATTRS)
    yield
    BASE_GRID_TOPOLOGY_ATTRS.clear()
    BASE_GRID_TOPOLOGY_ATTRS.update(pristine)


def _write_icon_grid(path) -> str:
    """Smallest file uxarray will recognise as ICON: two triangles.

    Four vertices, five edges, two cells. ICON stores connectivity 1-based,
    int32, and transposed relative to UGRID -- the reader subtracts one and
    transposes, and in doing so keeps the int32, which is the whole point of
    the fixture.
    """
    rad = np.pi / 180.0
    i32 = np.int32
    ds = xr.Dataset(
        {
            "vertex_of_cell": (
                ("nv", "cell"),
                np.array([[1, 2], [2, 4], [3, 3]], dtype=i32),
            ),
            "edge_of_cell": (
                ("nv", "cell"),
                np.array([[1, 4], [2, 5], [3, 2]], dtype=i32),
            ),
            "neighbor_cell_index": (
                ("nv", "cell"),
                np.array([[2, 1], [0, 0], [0, 0]], dtype=i32),
            ),
            "adjacent_cell_of_edge": (
                ("nc", "edge"),
                np.array([[1, 1, 1, 2, 2], [0, 2, 0, 0, 0]], dtype=i32),
            ),
            "edge_vertices": (
                ("nc", "edge"),
                np.array([[1, 2, 1, 2, 4], [2, 3, 3, 4, 3]], dtype=i32),
            ),
        },
        coords={
            "vlon": ("vertex", np.array([0.0, 10.0, 5.0, 15.0]) * rad),
            "vlat": ("vertex", np.array([0.0, 0.0, 10.0, 10.0]) * rad),
            "elon": ("edge", np.array([5.0, 7.5, 2.5, 12.5, 10.0]) * rad),
            "elat": ("edge", np.array([0.0, 5.0, 5.0, 5.0, 10.0]) * rad),
            "clon": ("cell", np.array([5.0, 10.0]) * rad),
            "clat": ("cell", np.array([3.3, 6.6]) * rad),
        },
    )
    target = str(path)
    ds.to_netcdf(target)
    return target


def _write_plain_ugrid(path) -> str:
    """A single triangle: nodes and faces, no edges, no face centers."""
    ds = xr.Dataset(
        {
            "mesh": xr.DataArray(
                np.int32(0),
                attrs=dict(
                    cf_role="mesh_topology",
                    topology_dimension=2,
                    node_coordinates="node_lon node_lat",
                    face_node_connectivity="face_node_connectivity",
                ),
            ),
            "face_node_connectivity": xr.DataArray(
                np.array([[0, 1, 2]], dtype=np.int64),
                dims=("n_face", "n_max_face_nodes"),
                attrs=dict(start_index=0),
            ),
        },
        coords={
            "node_lon": xr.DataArray(
                np.array([0.0, 10.0, 5.0]),
                dims="n_node",
                attrs=dict(standard_name="longitude", units="degrees_east"),
            ),
            "node_lat": xr.DataArray(
                np.array([0.0, 0.0, 10.0]),
                dims="n_node",
                attrs=dict(standard_name="latitude", units="degrees_north"),
            ),
        },
    )
    target = str(path)
    ds.to_netcdf(target)
    return target


class TestInt32ConnectivityCannotBeWritten:
    """uxarray's ICON reader pairs int32 data with an int64 fill value."""

    def test_the_reader_leaves_the_mismatch_in_place(self, tmp_path):
        import uxarray as ux

        grid = ux.open_grid(_write_icon_grid(tmp_path / "icon.nc"))

        assert grid.source_grid_spec == "ICON"
        encoded = ux.open_grid(_write_icon_grid(tmp_path / "icon2.nc")).to_xarray(
            grid_format="ugrid"
        )
        connectivity = encoded["face_node_connectivity"]
        # Every other reader normalizes to INT_DTYPE; _icon.py does not.
        assert connectivity.dtype == np.int32
        assert connectivity.attrs["_FillValue"] == INT64_FILL

    @pytest.mark.xfail(
        strict=True,
        reason="uxarray writes an int64 _FillValue onto int32 ICON connectivity",
        raises=OverflowError,
    )
    def test_upstream_write_raises_overflow(self, tmp_path):
        import uxarray as ux

        grid = ux.open_grid(_write_icon_grid(tmp_path / "icon.nc"))

        grid.to_xarray(grid_format="ugrid").to_netcdf(tmp_path / "out.nc")

    def test_our_writer_widens_the_array_instead(self, tmp_path, state_dir):
        import uxarray as ux

        from uxarray_mcp.state import write_grid_artifact

        grid = ux.open_grid(_write_icon_grid(tmp_path / "icon.nc"))

        written = write_grid_artifact(grid, "result_icon")

        # mask_and_scale=False: xarray otherwise promotes any variable carrying
        # a _FillValue to float64 on read, which would hide the stored dtype.
        reopened = xr.open_dataset(written, mask_and_scale=False)
        assert reopened["face_node_connectivity"].dtype == np.int64
        assert ux.open_grid(written).n_face == 2


class TestTopologyAttrsLeakBetweenGrids:
    """``_encode_ugrid`` mutates a module-level dict instead of copying it.

    The first grid a process exports leaves its connectivity names on the
    shared template, so a later, plainer grid is written claiming variables it
    does not have. Nothing complains until someone reopens the file, which is
    why this survived: in a fresh process the first grid always round-trips.
    """

    def test_a_plain_grid_is_encoded_claiming_variables_it_lacks(self, tmp_path):
        """The leak itself, without asserting on the shared dict.

        Asserting on ``BASE_GRID_TOPOLOGY_ATTRS`` directly would depend on
        whether anything else in the process exported a grid first, which is
        exactly the property that makes this defect hard to see.
        """
        import uxarray as ux

        ux.open_grid(_write_icon_grid(tmp_path / "icon.nc")).to_xarray(
            grid_format="ugrid"
        )
        encoded = ux.open_grid(_write_plain_ugrid(tmp_path / "plain.nc")).to_xarray(
            grid_format="ugrid"
        )

        attrs = encoded["grid_topology"].attrs
        assert attrs["face_edge_connectivity"] == "face_edge_connectivity"
        assert "face_edge_connectivity" not in encoded.variables

    @pytest.mark.xfail(
        strict=True,
        reason="uxarray leaks one grid's topology attributes onto the next",
        raises=ValueError,
    )
    def test_upstream_second_grid_cannot_be_reopened(self, tmp_path):
        import uxarray as ux

        # Order matters: the rich grid poisons the template for the plain one.
        ux.open_grid(_write_icon_grid(tmp_path / "icon.nc")).to_xarray(
            grid_format="ugrid"
        )
        plain = ux.open_grid(_write_plain_ugrid(tmp_path / "plain.nc"))
        out = tmp_path / "plain_out.nc"
        plain.to_xarray(grid_format="ugrid").to_netcdf(out)

        ux.open_grid(str(out))

    def test_our_writer_drops_what_the_grid_does_not_have(self, tmp_path, state_dir):
        import uxarray as ux

        from uxarray_mcp.state import write_grid_artifact

        ux.open_grid(_write_icon_grid(tmp_path / "icon.nc")).to_xarray(
            grid_format="ugrid"
        )
        plain = ux.open_grid(_write_plain_ugrid(tmp_path / "plain.nc"))

        written = write_grid_artifact(plain, "result_plain")

        attrs = xr.open_dataset(written)["grid_topology"].attrs
        assert "face_edge_connectivity" not in attrs
        assert "edge_dimension" not in attrs
        assert ux.open_grid(written).n_face == 1
