import sys
from unittest.mock import MagicMock

import pytest

# Mock uxarray if it's not installed, so we can run logic tests without heavy dependencies
try:
    import uxarray as ux
    import xarray as xr
except ImportError:
    ux = MagicMock()
    xr = MagicMock()
    sys.modules["uxarray"] = ux
    sys.modules["xarray"] = xr


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
