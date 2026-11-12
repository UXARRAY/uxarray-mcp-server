"""Spatial selection ops in the pure core layer."""

from __future__ import annotations

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.core.subset import (
    cross_section,
    regrid_elements,
    subset_bbox,
    subset_near_point,
    subset_polygon,
)

OFF_MESH_LON = [-170.0, -160.0]
OFF_MESH_LAT = [-80.0, -70.0]


@pytest.fixture
def regional_files(tmp_path):
    """An 81-face regional mesh of 5-degree cells centred on multiples of 5."""
    grid = ux.Grid.from_structured(
        lon=np.arange(0.0, 41.0, 5.0), lat=np.arange(0.0, 41.0, 5.0)
    )
    grid_file, data_file = tmp_path / "g.nc", tmp_path / "d.nc"
    grid.to_xarray().to_netcdf(grid_file)
    xr.Dataset({"t": (["n_face"], np.arange(grid.n_face, dtype=float))}).to_netcdf(
        data_file
    )
    return str(grid_file), str(data_file), grid


def test_bbox_keeps_fewer_faces_than_it_has_centres(regional_files):
    grid_file, data_file, grid = regional_files
    result = subset_bbox(grid_file, [5.0, 15.0], [5.0, 15.0], data_file, "t")
    coverage = result["subset_coverage"]
    assert coverage["n_face_source"] == grid.n_face
    assert coverage["n_face_centers_in_bounds"] == 6
    assert coverage["n_face_retained"] == 1
    assert coverage["selection_rule"] == "face_bounds_within"
    assert result["warning_codes"] == []
    assert result["variable_summary"]["shape"] == [1]
    assert isinstance(result["_payload"], ux.UxDataArray)


def test_bbox_off_the_mesh_is_zero_coverage_with_extent(regional_files):
    grid_file, _, grid = regional_files
    result = subset_bbox(grid_file, OFF_MESH_LON, OFF_MESH_LAT)
    assert result["warning_codes"] == ["SUBSET_COVERAGE_ZERO"]
    assert result["coverage"]["n_face_retained"] == 0
    assert result["coverage"]["source_extent"]["lon_max"] == pytest.approx(40.0)
    assert isinstance(result["_payload"], ux.Grid)
    assert result["_payload"].n_face == 0


def test_polygon_selects_by_face_centre(regional_files):
    grid_file, data_file, _ = regional_files
    result = subset_polygon(
        grid_file,
        [[-1.0, -1.0], [11.0, -1.0], [11.0, 11.0], [-1.0, 11.0]],
        data_file,
        "t",
    )
    assert result["selected_face_count"] == 9
    assert result["subset_coverage"]["selection_rule"] == "face_center_inside"
    assert isinstance(result["_payload"], ux.UxDataArray)
    empty = subset_polygon(
        grid_file, [[-170.0, -80.0], [-160.0, -80.0], [-160.0, -70.0]]
    )
    assert empty["warning_codes"] == ["SUBSET_COVERAGE_ZERO"]
    assert empty["_payload"]["selected_face_indices"] == []
    with pytest.raises(ValueError, match="three points"):
        subset_polygon(grid_file, [[0.0, 0.0], [1.0, 1.0]])


def test_cross_section_on_and_off_the_mesh(regional_files):
    grid_file, data_file, grid = regional_files
    result = cross_section(
        grid_file, latitude=10.0, data_path=data_file, variable_name="t"
    )
    assert result["selection_type"] == "constant_latitude"
    assert result["subset_coverage"]["selection_rule"] == "face_intersects_line"
    assert result["coverage"]["n_face_retained"] == 9
    assert isinstance(result["_payload"], ux.UxDataArray)
    missed = cross_section(grid_file, latitude=-70.0)
    assert missed["warning_codes"] == ["SUBSET_COVERAGE_ZERO"]
    assert missed["subset_grid"] is None and missed["_payload"] is None
    with pytest.raises(ValueError, match="exactly one"):
        cross_section(grid_file)


def test_near_point_circle_and_nearest(structured_mesh_files):
    grid_file, data_file = structured_mesh_files
    nearest = subset_near_point(grid_file, "nearest", 0.0, 0.0, k=12)
    assert nearest["subset_grid"]["n_face"] == 12
    assert nearest["subset_coverage"]["selection_rule"] == "k_nearest_faces"
    assert isinstance(nearest["_payload"], ux.Grid)
    circle = subset_near_point(
        grid_file,
        "circle",
        0.0,
        0.0,
        radius=25.0,
        data_path=data_file,
        variable_name="temperature",
    )
    assert circle["subset_grid"]["n_face"] > 0
    assert circle["subset_coverage"]["selection_rule"] == "face_center_within_radius"
    assert circle["variable_name"] == "temperature"
    assert isinstance(circle["_payload"], ux.UxDataArray)


def test_near_point_refuses_bad_arguments_and_empty_circles(regional_files):
    grid_file, _, _ = regional_files
    with pytest.raises(ValueError, match="requires radius"):
        subset_near_point(grid_file, "circle", 0.0, 0.0)
    with pytest.raises(ValueError, match="requires k"):
        subset_near_point(grid_file, "nearest", 0.0, 0.0)
    with pytest.raises(ValueError, match="expected 'circle' or 'nearest'"):
        subset_near_point(grid_file, "ring", 0.0, 0.0)
    with pytest.raises(ValueError, match="kept no faces"):
        subset_near_point(grid_file, "circle", -170.0, -80.0, radius=1.0)


def test_regrid_elements_moves_node_data_onto_faces(structured_mesh_files, tmp_path):
    grid_file, _ = structured_mesh_files
    n_node = ux.open_grid(grid_file).n_node
    node_file = tmp_path / "node.nc"
    xr.Dataset({"t_node": (["n_node"], np.linspace(250.0, 300.0, n_node))}).to_netcdf(
        node_file
    )
    result = regrid_elements(grid_file, str(node_file), "face", "t_node")
    assert result["source_dims"] == ["n_node"]
    assert result["result_dims"] == ["n_face"]
    assert 250.0 <= result["variable_summary"]["mean"] <= 300.0
    assert isinstance(result["_payload"], ux.UxDataArray)
    with pytest.raises(ValueError, match="already on node"):
        regrid_elements(grid_file, str(node_file), "node", "t_node")
    with pytest.raises(ValueError, match="Unknown statistic"):
        regrid_elements(grid_file, str(node_file), "face", "t_node", statistic="prod")
