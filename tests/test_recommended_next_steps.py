"""Tests for the ``recommended_next_steps`` field added in issue #30.

Every result-bearing tool should suggest follow-up tool calls so an agent
can chain a workflow without already knowing the tool vocabulary.
"""

from uxarray_mcp.tools.advanced import (
    extract_cross_section,
    subset_bbox,
    subset_polygon,
)
from uxarray_mcp.tools.inspection import (
    calculate_zonal_mean,
    validate_dataset,
)


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def test_calculate_zonal_mean_recommends_next_steps(synthetic_mesh_with_data):
    grid_file, data_file = synthetic_mesh_with_data
    result = calculate_zonal_mean(grid_file, data_file, "temperature")

    steps = result["recommended_next_steps"]
    assert _is_str_list(steps) and len(steps) >= 2
    joined = " ".join(steps)
    assert "plot_zonal_mean" in joined
    assert "plot_variable" in joined


def test_validate_dataset_pass_recommends_analysis_chain(synthetic_mesh_with_data):
    grid_file, data_file = synthetic_mesh_with_data
    result = validate_dataset(grid_file, data_file)

    assert result["passed"] is True
    steps = result["recommended_next_steps"]
    assert _is_str_list(steps)
    joined = " ".join(steps)
    assert "inspect_variable" in joined
    assert "calculate_zonal_mean" in joined


def test_validate_dataset_fail_recommends_stop(synthetic_mesh_file, tmp_path):
    """Synthetic data file with NaN should trigger the failure-branch hint."""
    import xarray as xr

    bad_file = tmp_path / "bad.nc"
    xr.Dataset(
        {"temperature": (["nMesh2_face"], [float("nan")], {"units": "K"})}
    ).to_netcdf(bad_file)

    result = validate_dataset(synthetic_mesh_file, str(bad_file))

    assert result["passed"] is False
    steps = result["recommended_next_steps"]
    assert _is_str_list(steps)
    joined = " ".join(steps).lower()
    assert "validation failed" in joined


def test_subset_bbox_recommends_plot_and_export(synthetic_mesh_with_data):
    grid_file, data_file = synthetic_mesh_with_data
    result = subset_bbox(
        lon_bounds=[-180.0, 180.0],
        lat_bounds=[-90.0, 90.0],
        grid_path=grid_file,
        data_path=data_file,
        variable_name="temperature",
    )

    steps = result["recommended_next_steps"]
    assert _is_str_list(steps)
    joined = " ".join(steps)
    assert "plot_mesh" in joined
    assert "export_to_netcdf" in joined
    # When data is provided, plot_variable should lead the list.
    assert "plot_variable" in steps[0]


def test_subset_polygon_recommends_plot_and_export(synthetic_mesh_with_data):
    grid_file, data_file = synthetic_mesh_with_data
    result = subset_polygon(
        polygon_lon_lat=[
            [-180.0, -90.0],
            [180.0, -90.0],
            [180.0, 90.0],
            [-180.0, 90.0],
        ],
        grid_path=grid_file,
        data_path=data_file,
        variable_name="temperature",
    )

    steps = result["recommended_next_steps"]
    assert _is_str_list(steps)
    joined = " ".join(steps)
    assert "plot_mesh" in joined
    assert "export_to_netcdf" in joined


def test_extract_cross_section_recommends_zonal_mean(synthetic_mesh_with_data):
    grid_file, data_file = synthetic_mesh_with_data
    result = extract_cross_section(
        latitude=0.5,
        longitude=None,
        grid_path=grid_file,
        data_path=data_file,
        variable_name="temperature",
        session_id=None,
        dataset_handle=None,
        result_name=None,
    )

    steps = result["recommended_next_steps"]
    assert _is_str_list(steps)
    joined = " ".join(steps)
    assert "calculate_zonal_mean" in joined
