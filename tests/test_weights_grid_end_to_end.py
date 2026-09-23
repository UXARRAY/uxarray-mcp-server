"""The weights-file adapter, exercised through the code that actually runs.

``tests/test_remote_uri_support.py`` proves the domain helpers rename the
right variables. It does not prove that a weights file *on disk* opens as a
Grid, that a data file's model-specific dimension lands on ``n_face``, or
that ``remote_temporal_mean_map`` -- which bypasses ``domain/`` entirely and
carries its own inlined copy of the adapter -- reaches the same mesh. The
local, no-endpoint plot path runs that function too, so a drift between the
two copies is a laptop bug, not only a worker one.

The fixture is built from a real ``Grid.from_structured`` mesh, so
``ux.open_grid`` has genuine quadrilaterals to parse rather than jittered
random corners, and the expected face count is known exactly.
"""

from __future__ import annotations

import ast
import inspect
import re

import numpy as np
import pytest
import xarray as xr

ux = pytest.importorskip("uxarray")

from uxarray_mcp.domain.mesh import (  # noqa: E402
    WEIGHTS_DIM_RENAME,
    WEIGHTS_REQUIRED,
    WEIGHTS_VAR_RENAME,
    load_dataset,
    load_grid,
    open_grid_object,
)
from uxarray_mcp.remote import compute_functions as cf  # noqa: E402

N_LON, N_LAT = 12, 7  # 12 x 6 = 72 quads


def _structured_scrip_arrays():
    lon = np.linspace(0.0, 330.0, N_LON)
    lat = np.linspace(-60.0, 60.0, N_LAT)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    conn = np.asarray(grid.face_node_connectivity.values)
    node_lon = np.asarray(grid.node_lon.values)
    node_lat = np.asarray(grid.node_lat.values)
    corner_lon = node_lon[conn]
    corner_lat = node_lat[conn]
    center_lon = np.asarray(grid.face_lon.values)
    center_lat = np.asarray(grid.face_lat.values)
    return int(grid.n_face), center_lon, center_lat, corner_lon, corner_lat


@pytest.fixture(scope="module")
def esmf_weights_file(tmp_path_factory):
    """An ESMF ``_a``/``_b`` weights file whose source grid is a real mesh."""
    n_face, xc, yc, xv, yv = _structured_scrip_arrays()
    n_b, n_s = 5, 9
    ds = xr.Dataset(
        {
            "xc_a": ("n_a", xc),
            "yc_a": ("n_a", yc),
            "xv_a": (("n_a", "nv_a"), xv),
            "yv_a": (("n_a", "nv_a"), yv),
            "mask_a": ("n_a", np.ones(n_face, dtype="int32")),
            "area_a": ("n_a", np.full(n_face, 1.0 / n_face)),
            "src_grid_dims": ("src_grid_rank", np.array([n_face], dtype="int32")),
            # Destination grid and weights: the bulk of a real file, dropped.
            "xc_b": ("n_b", np.zeros(n_b)),
            "yc_b": ("n_b", np.zeros(n_b)),
            "S": ("n_s", np.ones(n_s)),
            "row": ("n_s", np.ones(n_s, dtype="int32")),
            "col": ("n_s", np.ones(n_s, dtype="int32")),
        },
        attrs={"source_grid": "structured_12x6"},
    )
    path = tmp_path_factory.mktemp("weights") / "map_src_to_dst.nc"
    ds.to_netcdf(path)
    return str(path), n_face


@pytest.fixture(scope="module")
def cam_style_data_file(tmp_path_factory, esmf_weights_file):
    """Monthly data on a CAM-style ``ncol`` dimension, each value = its year.

    Two years of months, values 2001.0 then 2002.0, so the temporal mean
    is 2001.5 everywhere -- a wrong slice yields a wrong number, not merely
    a wrong step count.
    """
    _, n_face = esmf_weights_file
    years = np.repeat([2001.0, 2002.0], 12)
    values = np.broadcast_to(years[:, None], (24, n_face)).copy()
    time = xr.date_range("2001-01-01", periods=24, freq="MS")
    ds = xr.Dataset(
        {"PRECT": (("time", "ncol"), values, {"units": "m/s"})},
        coords={"time": time},
    )
    path = tmp_path_factory.mktemp("data") / "PRECT.nc"
    ds.to_netcdf(path)
    return str(path)


class TestAWeightsFileOnDiskOpensAsAGrid:
    def test_open_grid_object_recovers_the_source_mesh(self, esmf_weights_file):
        path, n_face = esmf_weights_file
        grid = open_grid_object(path)
        assert int(grid.n_face) == n_face

    def test_load_grid_takes_the_same_route(self, esmf_weights_file):
        path, n_face = esmf_weights_file
        assert int(load_grid(path).n_face) == n_face

    def test_an_ordinary_grid_still_opens_directly(self, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        grid = open_grid_object(grid_file)
        assert int(grid.n_face) > 0

    def test_a_file_that_is_neither_names_its_variables(self, tmp_path):
        path = tmp_path / "not_a_grid.nc"
        xr.Dataset({"temperature": ("x", np.zeros(3))}).to_netcdf(path)
        with pytest.raises(ValueError, match="Variables present.*temperature"):
            open_grid_object(str(path))

    def test_an_unreadable_path_reports_the_direct_error(self, tmp_path):
        # xr.open_dataset fails too, so the *grid* reader's error is what
        # surfaces -- not a second, unrelated one about the peek.
        missing = tmp_path / "missing.nc"
        with pytest.raises(Exception) as excinfo:
            open_grid_object(str(missing))
        assert "Variables present" not in str(excinfo.value)


class TestDataLandsOnTheMesh:
    def test_the_model_dim_is_renamed_to_n_face(
        self, esmf_weights_file, cam_style_data_file
    ):
        path, n_face = esmf_weights_file
        uxds = load_dataset(path, cam_style_data_file)
        assert "n_face" in uxds["PRECT"].dims
        assert "ncol" not in uxds["PRECT"].dims
        assert int(uxds.uxgrid.n_face) == n_face

    def test_an_ordinary_tool_sees_the_variable_as_face_centered(
        self, state_dir, esmf_weights_file, cam_style_data_file
    ):
        """``ux.open_dataset(grid, data)`` never consulted the adapter, so a
        weights grid worked for the temporal-mean map and failed for every
        other tool. Any tool that goes through ``load_dataset`` proves the
        retry; ``inspect_variable`` is the cheapest."""
        from uxarray_mcp.tools import run_analysis

        path, n_face = esmf_weights_file
        result = run_analysis(
            operation="inspect_variable",
            grid_path=path,
            data_path=cam_style_data_file,
            variable_name="PRECT",
        )
        prect = next(v for v in result["variables"] if v["name"] == "PRECT")
        assert prect["location"] == "faces"
        assert "n_face" in prect["dims"]


class TestTheInlinedAdapterMatchesTheDomainCopy:
    """``compute_functions`` may not import ``uxarray_mcp``; it inlines.

    The inlined tables are parsed out of the source and compared to the
    domain constants, the same discipline ``test_remote_mesh_coverage``
    applies to the size guard. A rename added to one side and not the
    other would otherwise open the same file to two different meshes
    depending on which code path a request happened to take.
    """

    @staticmethod
    def _inlined_conventions() -> dict:
        source = inspect.getsource(cf.remote_temporal_mean_map)
        match = re.search(r"_CONVENTIONS = (\{.*?\n\s*\})\n", source, flags=re.S)
        assert match is not None, "inlined _CONVENTIONS table not found"
        return ast.literal_eval(match.group(1))

    def test_every_convention_agrees(self):
        inlined = self._inlined_conventions()
        assert set(inlined) == set(WEIGHTS_REQUIRED)
        for name, (required, var_map, dim_map) in inlined.items():
            assert required == WEIGHTS_REQUIRED[name], name
            assert var_map == WEIGHTS_VAR_RENAME[name], name
            assert dim_map == WEIGHTS_DIM_RENAME[name], name


class TestRemoteTemporalMeanMapUsesTheAdapter:
    """The function ``plot_dataset(plot_type="temporal_mean")`` runs locally."""

    def test_a_weights_grid_is_averaged_and_drawn(
        self, esmf_weights_file, cam_style_data_file
    ):
        path, n_face = esmf_weights_file
        result = cf.remote_temporal_mean_map(
            grid_path=path,
            data_paths=[cam_style_data_file],
            variable_name="PRECT",
            geography=False,
            width=200,
            height=120,
        )
        assert result["n_face_total"] == n_face
        assert result["n_time_steps"] == 24
        assert result["value_stats"]["mean"] == pytest.approx(2001.5)
        assert result["value_stats"]["min"] == pytest.approx(2001.5)
        assert result["image_size_bytes"] > 0
        assert result["reduced_dims"]["time"]["how"] == "mean"

    def test_a_bounding_box_reads_a_subset(
        self, esmf_weights_file, cam_style_data_file
    ):
        path, n_face = esmf_weights_file
        result = cf.remote_temporal_mean_map(
            grid_path=path,
            data_paths=[cam_style_data_file],
            variable_name="PRECT",
            lon_bounds=[0.0, 90.0],
            lat_bounds=[-30.0, 30.0],
            geography=False,
            width=200,
            height=120,
        )
        assert 0 < result["n_face_subset"] < n_face
        assert result["n_face_total"] == n_face
        assert result["value_stats"]["mean"] == pytest.approx(2001.5)

    def test_half_a_box_is_refused(self, esmf_weights_file, cam_style_data_file):
        path, _ = esmf_weights_file
        with pytest.raises(ValueError, match="both lon_bounds and lat_bounds"):
            cf.remote_temporal_mean_map(
                grid_path=path,
                data_paths=[cam_style_data_file],
                variable_name="PRECT",
                lon_bounds=[0.0, 90.0],
            )

    def test_a_grid_that_is_neither_names_its_variables(
        self, tmp_path, cam_style_data_file
    ):
        path = tmp_path / "not_a_grid.nc"
        xr.Dataset({"temperature": ("x", np.zeros(3))}).to_netcdf(path)
        with pytest.raises(ValueError, match="Variables present"):
            cf.remote_temporal_mean_map(
                grid_path=str(path),
                data_paths=[cam_style_data_file],
                variable_name="PRECT",
            )


class TestPlotDatasetReachesBothNewKinds:
    """Neither ``temporal_mean`` nor ``subset_bbox`` was reached through the
    tool layer by any test; only the worker functions underneath were."""

    def test_temporal_mean_through_the_front_door(
        self, state_dir, esmf_weights_file, cam_style_data_file
    ):
        from uxarray_mcp.tools import plot_dataset

        path, n_face = esmf_weights_file
        blocks = plot_dataset(
            plot_type="temporal_mean",
            grid_path=path,
            data_paths=[cam_style_data_file],
            variable_name="PRECT",
            coastlines=False,
            width=200,
            height=120,
        )
        assert isinstance(blocks, list) and blocks
        assert any(b.get("type") == "image" for b in blocks if isinstance(b, dict))

    def test_temporal_mean_without_data_is_refused(self, state_dir, esmf_weights_file):
        from uxarray_mcp.tools import plot_dataset

        path, _ = esmf_weights_file
        with pytest.raises(ValueError, match="requires data_paths"):
            plot_dataset(plot_type="temporal_mean", grid_path=path, variable_name="x")

    def test_subset_bbox_through_the_front_door(self, state_dir, structured_mesh_files):
        from uxarray_mcp.tools import plot_dataset

        grid_file, _ = structured_mesh_files
        blocks = plot_dataset(
            plot_type="subset_bbox",
            grid_path=grid_file,
            lon_bounds=[0.0, 90.0],
            lat_bounds=[-30.0, 30.0],
            coastlines=False,
            width=200,
            height=120,
        )
        assert isinstance(blocks, list) and blocks
        assert any(b.get("type") == "image" for b in blocks if isinstance(b, dict))

    def test_subset_bbox_without_a_box_is_refused(
        self, state_dir, structured_mesh_files
    ):
        from uxarray_mcp.tools import plot_dataset

        grid_file, _ = structured_mesh_files
        with pytest.raises(ValueError, match="requires lon_bounds and lat_bounds"):
            plot_dataset(plot_type="subset_bbox", grid_path=grid_file)
