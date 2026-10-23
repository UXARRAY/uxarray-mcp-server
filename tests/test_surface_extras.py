"""``subset_advanced`` and ``regrid_elements``.

Both close gaps found by replaying the UXARRAY/uxarray-community
notebooks through the server: a selection near a point (four uses each of
``bounding_circle`` and ``nearest_neighbor``) and node-to-face transfer
(three uses of ``topological_mean``).

The selection tests lean on the same rule as ``test_subset_coverage.py``:
a selection that kept nothing must not come back shaped like a selection
that kept something.
"""

from __future__ import annotations

import pytest

from uxarray_mcp.tools.surface_extras import (
    TOPOLOGICAL_STATISTICS,
    regrid_elements,
    subset_advanced,
)


@pytest.fixture
def global_mesh(tmp_path):
    """A global structured mesh plus a face-centred field."""
    import numpy as np
    import uxarray as ux
    import xarray as xr

    grid = ux.Grid.from_structured(
        lon=np.arange(-180, 180, 20.0), lat=np.arange(-80, 81, 20.0)
    )
    gf = tmp_path / "g.nc"
    df = tmp_path / "d.nc"
    grid.to_xarray().to_netcdf(gf)
    rng = np.random.default_rng(3)
    xr.Dataset(
        {"temperature": (["n_face"], 280 + 20 * rng.random(grid.n_face))}
    ).to_netcdf(df)
    return str(gf), str(df)


@pytest.fixture
def node_data_file(global_mesh, tmp_path):
    """A node-centred field on the same mesh.

    Node-centred output is the case the face-centred refusals exist for,
    and no shared fixture had one.
    """
    import numpy as np
    import uxarray as ux
    import xarray as xr

    gf, _ = global_mesh
    n_node = ux.open_grid(gf).n_node
    nf = tmp_path / "node.nc"
    xr.Dataset({"t_node": (["n_node"], np.linspace(250.0, 300.0, n_node))}).to_netcdf(
        nf
    )
    return str(nf)


class TestSelectingNearAPoint:
    def test_a_circle_keeps_faces_within_the_radius(self, global_mesh):
        global_grid_file, _ = global_mesh
        out = subset_advanced(
            selection="circle",
            center_lon=0.0,
            center_lat=0.0,
            radius=30.0,
            grid_path=global_grid_file,
        )
        assert out["selection"] == "circle"
        assert out["subset_grid"]["n_face"] > 0
        assert out["subset_coverage"]["selection_rule"] == "face_center_within_radius"

    def test_nearest_keeps_exactly_k_faces(self, global_mesh):
        global_grid_file, _ = global_mesh
        """The point of ``nearest``: a count, not a distance."""
        out = subset_advanced(
            selection="nearest",
            center_lon=0.0,
            center_lat=0.0,
            k=12,
            grid_path=global_grid_file,
        )
        assert out["subset_grid"]["n_face"] == 12

    def test_a_circle_that_finds_nothing_says_where_the_mesh_is(
        self, regional_mesh_files
    ):
        regional_grid_file, _ = regional_mesh_files
        """UXarray says the circle was empty. That is true and not useful.

        The caller needs to know where a circle *would* find something,
        which is what the mesh extent carries.
        """
        with pytest.raises(ValueError) as err:
            subset_advanced(
                selection="circle",
                center_lon=-170.0,
                center_lat=-80.0,
                radius=1.0,
                grid_path=regional_grid_file,
            )
        msg = str(err.value)
        assert "kept no faces" in msg
        assert "mesh covers" in msg

    def test_a_field_follows_the_selection(self, global_mesh):
        global_grid_file, global_data_file = global_mesh
        out = subset_advanced(
            selection="circle",
            center_lon=0.0,
            center_lat=0.0,
            radius=40.0,
            grid_path=global_grid_file,
            data_path=global_data_file,
            variable_name="temperature",
        )
        assert out["variable_name"] == "temperature"
        assert out["variable_summary"] is not None
        assert out["result_handle"] is not None


class TestTheArgumentsMustMatchTheSelection:
    """Each selection needs its own argument and cannot borrow the other's.

    A circle with no radius and a nearest with no k are the two mistakes
    the schema cannot prevent, since both parameters are optional.
    """

    def test_circle_without_a_radius_is_refused(self, global_mesh):
        global_grid_file, _ = global_mesh
        with pytest.raises(ValueError, match="requires radius"):
            subset_advanced(
                selection="circle",
                center_lon=0.0,
                center_lat=0.0,
                grid_path=global_grid_file,
            )

    def test_nearest_without_k_is_refused(self, global_mesh):
        global_grid_file, _ = global_mesh
        with pytest.raises(ValueError, match="requires k"):
            subset_advanced(
                selection="nearest",
                center_lon=0.0,
                center_lat=0.0,
                grid_path=global_grid_file,
            )

    def test_a_nonpositive_radius_is_refused(self, global_mesh):
        global_grid_file, _ = global_mesh
        with pytest.raises(ValueError, match="must be positive"):
            subset_advanced(
                selection="circle",
                center_lon=0.0,
                center_lat=0.0,
                radius=0.0,
                grid_path=global_grid_file,
            )

    def test_an_unknown_selection_names_the_two_that_exist(self, global_mesh):
        global_grid_file, _ = global_mesh
        with pytest.raises(ValueError, match="circle.*nearest"):
            subset_advanced(
                selection="square",
                center_lon=0.0,
                center_lat=0.0,
                grid_path=global_grid_file,
            )


class TestMovingAFieldBetweenElements:
    def test_node_data_lands_on_faces(self, global_mesh, node_data_file):
        global_grid_file, _ = global_mesh
        out = regrid_elements(
            destination="face",
            grid_path=global_grid_file,
            data_path=node_data_file,
            variable_name="t_node",
        )
        assert out["source_dims"] == ["n_node"]
        assert out["result_dims"] == ["n_face"]
        assert out["statistic"] == "mean"

    @pytest.mark.parametrize("stat", TOPOLOGICAL_STATISTICS)
    def test_every_offered_statistic_runs(self, stat, global_mesh, node_data_file):
        global_grid_file, _ = global_mesh
        """Offering a statistic the library cannot apply would be worse
        than not offering it: the failure arrives after the caller has
        chosen.
        """
        out = regrid_elements(
            destination="face",
            statistic=stat,
            grid_path=global_grid_file,
            data_path=node_data_file,
            variable_name="t_node",
        )
        assert out["result_dims"] == ["n_face"]

    def test_a_field_already_on_the_destination_is_refused(self, global_mesh):
        global_grid_file, global_data_file = global_mesh
        """Nothing to do is not the same as done."""
        with pytest.raises(ValueError, match="already on face"):
            regrid_elements(
                destination="face",
                grid_path=global_grid_file,
                data_path=global_data_file,
                variable_name="temperature",
            )

    def test_an_unknown_statistic_is_refused(self, global_mesh, node_data_file):
        global_grid_file, _ = global_mesh
        with pytest.raises(ValueError, match="Unknown statistic"):
            regrid_elements(
                destination="face",
                statistic="kurtosis",
                grid_path=global_grid_file,
                data_path=node_data_file,
                variable_name="t_node",
            )

    def test_without_data_it_says_so(self, global_mesh):
        global_grid_file, _ = global_mesh
        """A mesh alone has no field to move."""
        with pytest.raises(ValueError, match="needs data_path"):
            regrid_elements(destination="face", grid_path=global_grid_file)


class TestTheRepairIsReachable:
    """The face-centred refusals now name ``regrid_elements``.

    That advice has to work, or it is a worse dead end than saying
    nothing: the caller follows it and lands on a second error.
    """

    def test_the_advice_in_the_gradient_refusal_actually_fixes_it(
        self, global_mesh, node_data_file
    ):
        global_grid_file, _ = global_mesh
        import uxarray as ux

        from uxarray_mcp.domain.vector_calc import compute_gradient

        uxds = ux.open_dataset(global_grid_file, node_data_file)
        with pytest.raises(ValueError) as err:
            compute_gradient(uxds, "t_node")
        assert "regrid_elements(destination='face')" in str(err.value)

        moved = regrid_elements(
            destination="face",
            grid_path=global_grid_file,
            data_path=node_data_file,
            variable_name="t_node",
        )
        assert moved["result_dims"] == ["n_face"]
