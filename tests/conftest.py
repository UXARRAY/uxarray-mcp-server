import importlib.util
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

#: True when the suite is running against stand-ins rather than the real
#: libraries. Asserted on below so a mocked run can never report green.
UXARRAY_IS_MOCKED = False


def _install_stubs() -> None:
    """Swap in MagicMocks so the pure-logic tests can still run."""
    global UXARRAY_IS_MOCKED, ux, xr
    ux = MagicMock()
    xr = MagicMock()
    sys.modules["uxarray"] = ux
    sys.modules["xarray"] = xr
    UXARRAY_IS_MOCKED = True


# Mock uxarray if it is not installed, so the logic tests can run without the
# heavy dependencies. "Not installed" and "installed but broken" are different
# situations and only the first one may be mocked: an ImportError raised from
# *inside* uxarray -- a moved optional import, a binary built against the wrong
# NumPy -- would otherwise be answered by substituting a MagicMock that returns
# a MagicMock for every call, and the whole suite would pass while exercising
# nothing. find_spec separates the two, and the guard test below refuses to let
# a mocked run be mistaken for a real one either way.
if importlib.util.find_spec("uxarray") is None:
    _install_stubs()
else:
    import uxarray as ux
    import xarray as xr


@pytest.fixture
def base_grid():
    """Returns a basic mocked uxarray Grid object."""
    grid = MagicMock()
    grid.n_face = 100
    grid.n_node = 200
    grid.n_edge = 300
    grid.n_max_face_nodes = 4
    return grid


@pytest.fixture
def mpas_grid(base_grid):
    """Returns a mocked MPAS grid."""
    base_grid.source_grid_spec = "MPAS"
    return base_grid


@pytest.fixture
def ugrid_grid(base_grid):
    """Returns a mocked UGRID grid."""
    base_grid.source_grid_spec = "UGRID"
    return base_grid


@pytest.fixture
def scrip_grid(base_grid):
    """Returns a mocked SCRIP grid."""
    base_grid.source_grid_spec = "SCRIP"
    return base_grid


@pytest.fixture
def csu_grid(base_grid):
    """Returns a mocked CSU grid."""
    base_grid.source_grid_spec = "CSU"
    return base_grid


@pytest.fixture
def synthetic_mesh_file(tmp_path):
    """Creates a small valid UGRID NetCDF file for integration testing."""
    # Simple 1-triangle mesh
    ds = xr.Dataset(
        {
            # UGRID required variable
            "Mesh2": (
                [],
                0,
                {
                    "cf_role": "mesh_topology",
                    "topology_dimension": 2,
                    "node_coordinates": "Mesh2_node_x Mesh2_node_y",
                    "face_node_connectivity": "Mesh2_face_nodes",
                },
            ),
            "Mesh2_node_x": (["nMesh2_node"], [0.0, 1.0, 0.5]),
            "Mesh2_node_y": (["nMesh2_node"], [0.0, 0.0, 1.0]),
            "Mesh2_face_nodes": (
                ["nMesh2_face", "nMaxMesh2_face_nodes"],
                [[0, 1, 2]],
                {"cf_role": "face_node_connectivity", "start_index": 0},
            ),
        }
    )

    file_path = tmp_path / "synthetic_ugrid.nc"
    ds.to_netcdf(file_path)
    return str(file_path)


@pytest.fixture
def synthetic_mesh_with_data(tmp_path):
    """Creates a synthetic mesh with grid and data files for testing inspect_variable."""
    # Create grid file
    grid_ds = xr.Dataset(
        {
            "Mesh2": (
                [],
                0,
                {
                    "cf_role": "mesh_topology",
                    "topology_dimension": 2,
                    "node_coordinates": "Mesh2_node_x Mesh2_node_y",
                    "face_node_connectivity": "Mesh2_face_nodes",
                },
            ),
            "Mesh2_node_x": (["nMesh2_node"], [0.0, 1.0, 0.5]),
            "Mesh2_node_y": (["nMesh2_node"], [0.0, 0.0, 1.0]),
            "Mesh2_face_nodes": (
                ["nMesh2_face", "nMaxMesh2_face_nodes"],
                [[0, 1, 2]],
                {"cf_role": "face_node_connectivity", "start_index": 0},
            ),
        }
    )

    # Create data file with variables
    data_ds = xr.Dataset(
        {
            "temperature": (
                ["nMesh2_face"],
                [288.15],
                {"units": "K", "long_name": "Temperature"},
            ),
            "pressure": (
                ["nMesh2_face"],
                [101325.0],
                {"units": "Pa", "long_name": "Pressure"},
            ),
        }
    )

    grid_file = tmp_path / "grid.nc"
    data_file = tmp_path / "data.nc"

    grid_ds.to_netcdf(grid_file)
    data_ds.to_netcdf(data_file)

    return str(grid_file), str(data_file)


@pytest.fixture
def state_dir(monkeypatch, tmp_path):
    """Redirect persistent tool state into a temporary test directory."""
    state_path = tmp_path / "state"
    monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(state_path))
    return state_path


def _write_simple_grid(path, *, node_x, node_y, face_nodes):
    """Write a compact UGRID mesh for integration-style tool tests."""
    ds = xr.Dataset(
        {
            "Mesh2": (
                [],
                0,
                {
                    "cf_role": "mesh_topology",
                    "topology_dimension": 2,
                    "node_coordinates": "Mesh2_node_x Mesh2_node_y",
                    "face_node_connectivity": "Mesh2_face_nodes",
                },
            ),
            "Mesh2_node_x": (["nMesh2_node"], node_x),
            "Mesh2_node_y": (["nMesh2_node"], node_y),
            "Mesh2_face_nodes": (
                ["nMesh2_face", "nMaxMesh2_face_nodes"],
                face_nodes,
                {"cf_role": "face_node_connectivity", "start_index": 0},
            ),
        }
    )
    ds.to_netcdf(path)


@pytest.fixture
def comparison_mesh_with_data(tmp_path):
    """Create one grid and two same-grid data files for comparison tests."""
    grid_file = tmp_path / "grid.nc"
    data_a = tmp_path / "data_a.nc"
    data_b = tmp_path / "data_b.nc"

    _write_simple_grid(
        grid_file,
        node_x=[0.0, 1.0, 1.0, 0.0],
        node_y=[0.0, 0.0, 1.0, 1.0],
        face_nodes=[[0, 1, 2, 3]],
    )

    xr.Dataset(
        {
            "temperature": (["nMesh2_face"], [280.0], {"units": "K"}),
            "pressure": (["nMesh2_face"], [1000.0], {"units": "hPa"}),
        }
    ).to_netcdf(data_a)
    xr.Dataset(
        {
            "temperature": (["nMesh2_face"], [282.0], {"units": "K"}),
            "pressure": (["nMesh2_face"], [1005.0], {"units": "hPa"}),
        }
    ).to_netcdf(data_b)

    return str(grid_file), str(data_a), str(data_b)


@pytest.fixture
def remap_target_grid(tmp_path):
    """Create a small target grid for remapping tests."""
    grid_file = tmp_path / "target_grid.nc"
    _write_simple_grid(
        grid_file,
        node_x=[10.0, 11.0, 10.5],
        node_y=[0.0, 0.0, 1.0],
        face_nodes=[[0, 1, 2]],
    )
    return str(grid_file)


@pytest.fixture
def time_series_dataset(tmp_path):
    """Create a time-aware dataset for temporal mean and anomaly tests."""
    data_file = tmp_path / "time_series.nc"
    xr.Dataset(
        {
            "temperature": (
                ["time", "sample"],
                [[280.0, 281.0], [282.0, 283.0], [284.0, 285.0]],
                {"units": "K"},
            )
        },
        coords={"time": [0, 1, 2], "sample": [0, 1]},
    ).to_netcdf(data_file)
    return str(data_file)


@pytest.fixture
def ensemble_data_files(tmp_path):
    """Create multiple files with a common variable for ensemble statistics."""
    first = tmp_path / "member_1.nc"
    second = tmp_path / "member_2.nc"
    xr.Dataset(
        {"temperature": (["sample"], [280.0, 282.0], {"units": "K"})},
        coords={"sample": [0, 1]},
    ).to_netcdf(first)
    xr.Dataset(
        {"temperature": (["sample"], [284.0, 286.0], {"units": "K"})},
        coords={"sample": [0, 1]},
    ).to_netcdf(second)
    return [str(first), str(second)]


@pytest.fixture
def healpix_field_dataset():
    """HEALPix UxDataset with face-centered u, v, and a temperature field."""
    grid = ux.Grid.from_healpix(zoom=2)
    n = grid.n_face
    rng = np.random.default_rng(7)
    return ux.UxDataset(
        {
            "u": ux.UxDataArray(
                xr.DataArray(rng.standard_normal(n), dims=["n_face"]), uxgrid=grid
            ),
            "v": ux.UxDataArray(
                xr.DataArray(rng.standard_normal(n), dims=["n_face"]), uxgrid=grid
            ),
            "temperature": ux.UxDataArray(
                xr.DataArray(250 + 30 * rng.standard_normal(n), dims=["n_face"]),
                uxgrid=grid,
            ),
        },
        uxgrid=grid,
    )


@pytest.fixture
def structured_mesh_files(tmp_path):
    """Coarse global UGRID grid + face-centered data written to disk.

    ``Grid.from_structured`` produces node coordinates that survive a NetCDF
    round-trip, making it a reliable file-based fixture for remapping.
    """
    lon = np.arange(0, 360, 20.0)
    lat = np.arange(-80, 81, 20.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "grid.nc"
    data_file = tmp_path / "data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    rng = np.random.default_rng(11)
    xr.Dataset(
        {"temperature": (["n_face"], 250 + 30 * rng.random(grid.n_face))}
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file)


@pytest.fixture
def regional_mesh_files(tmp_path):
    """Small regional UGRID mesh (~40-47E, +/-2.5 lat) plus face-centered data.

    Deliberately covers only a sliver of the globe so remap coverage checks
    have something that a global target grid falls entirely outside of.
    """
    lon = np.arange(40, 48, 2.0)
    lat = np.arange(-2, 3, 1.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "regional_grid.nc"
    data_file = tmp_path / "regional_data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    rng = np.random.default_rng(7)
    xr.Dataset(
        {"temperature": (["n_face"], 0.1 + 0.06 * rng.random(grid.n_face))}
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file)


@pytest.fixture
def earth_radius_mesh_files(tmp_path):
    """Closed global mesh that declares a physical Earth radius (#92).

    Every other mesh fixture here sits on a unit sphere, where scaling by
    R is invisible and the area identity happens to be ``4*pi``. That
    hides a whole class of bug -- #87 was exactly a unit-sphere blind
    spot -- so at least one fixture has to carry a real radius.
    """
    lon = np.arange(0, 360, 20.0)
    lat = np.arange(-80, 81, 20.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "earth_grid.nc"
    data_file = tmp_path / "earth_data.nc"

    grid_ds = grid.to_xarray()
    grid_ds.attrs["sphere_radius"] = 6371000.0
    grid_ds.to_netcdf(grid_file)

    rng = np.random.default_rng(23)
    xr.Dataset(
        {
            "u": (["n_face"], 10 * rng.standard_normal(grid.n_face)),
            "v": (["n_face"], 10 * rng.standard_normal(grid.n_face)),
        }
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file)


@pytest.fixture
def multi_level_mesh_files(tmp_path):
    """Mesh plus a field with four vertical levels (#92).

    Level selection is untested against any fixture where picking the
    wrong level produces a plausible-looking wrong number, so the levels
    here are separated far enough that a mis-selection is unmistakable.
    """
    lon = np.arange(0, 360, 30.0)
    lat = np.arange(-75, 76, 30.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "level_grid.nc"
    data_file = tmp_path / "level_data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    n_level = 4
    # Level k is centered on 100*(k+1), so a mean of ~200 can only come
    # from level 1 and nothing else.
    values = np.stack([np.full(grid.n_face, 100.0 * (k + 1)) for k in range(n_level)])
    xr.Dataset(
        {"temperature": (["n_level", "n_face"], values)},
        coords={"n_level": np.arange(n_level)},
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file)


@pytest.fixture
def time_level_mesh_files(tmp_path):
    """Mesh plus a field with three times AND four vertical levels.

    ``multi_level_mesh_files`` cannot catch a dropped ``time_index`` because
    it has no time axis. Here the value is ``1000*t + 100*(level+1)``, so the
    magnitude alone identifies which slice was taken: picking the wrong time
    is off by a thousand, the wrong level by a hundred.
    """
    lon = np.arange(0, 360, 30.0)
    lat = np.arange(-75, 76, 30.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "time_level_grid.nc"
    data_file = tmp_path / "time_level_data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    n_time, n_level = 3, 4
    values = np.stack(
        [
            np.stack(
                [
                    np.full(grid.n_face, 1000.0 * t + 100.0 * (k + 1))
                    for k in range(n_level)
                ]
            )
            for t in range(n_time)
        ]
    )
    xr.Dataset(
        {"temperature": (["time", "n_level", "n_face"], values)},
        coords={"time": np.arange(n_time), "n_level": np.arange(n_level)},
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file)


@pytest.fixture
def masked_mesh_files(tmp_path):
    """Mesh plus a field whose southern half is missing (#92).

    Nothing else in the suite exercises masked data, so no operation is
    checked for whether it quietly averages over a mask. Here the unmasked
    cells are all exactly 1.0: any mean other than 1.0 means NaNs were
    folded in.
    """
    lon = np.arange(0, 360, 30.0)
    lat = np.arange(-75, 76, 30.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "masked_grid.nc"
    data_file = tmp_path / "masked_data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    values = np.ones(grid.n_face)
    face_lat = np.asarray(grid.face_lat)
    masked = face_lat < 0
    values[masked] = np.nan
    xr.Dataset(
        {"salinity": (["n_face"], values)},
        attrs={"n_masked_faces": int(masked.sum())},
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file)
