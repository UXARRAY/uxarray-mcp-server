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
