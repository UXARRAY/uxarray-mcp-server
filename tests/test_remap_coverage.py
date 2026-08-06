"""Coverage reporting for remapping onto a target grid (issue #85)."""

import warnings

import numpy as np
import pytest

from uxarray_mcp.domain.remap_coverage import (
    compute_target_coverage,
    method_is_conservative,
)
from uxarray_mcp.tools.advanced import remap_to_rectilinear
from uxarray_mcp.tools.frontdoor import run_analysis


@pytest.fixture
def regional_grid(regional_mesh_files):
    import uxarray as ux

    grid_file, _ = regional_mesh_files
    return ux.open_grid(grid_file)


class TestComputeTargetCoverage:
    def test_global_target_over_regional_source_reports_zero(self, regional_grid):
        coverage = compute_target_coverage(
            regional_grid,
            list(np.arange(-180, 180, 72.0)),
            list(np.arange(-60, 61, 30.0)),
        )
        assert coverage["n_target_points"] == 25
        assert coverage["points_in_source"] == 0
        assert coverage["coverage_fraction"] == 0.0
        assert "REMAP_COVERAGE_ZERO" in coverage["warning_codes"]

    def test_target_inside_source_reports_full_coverage(self, regional_grid):
        coverage = compute_target_coverage(regional_grid, [42.0, 44.0], [0.0, 1.0])
        assert coverage["points_in_source"] == coverage["n_target_points"]
        assert coverage["coverage_fraction"] == 1.0
        assert "REMAP_COVERAGE_ZERO" not in coverage["warning_codes"]
        assert "REMAP_COVERAGE_PARTIAL" not in coverage["warning_codes"]

    def test_partial_coverage_gets_its_own_code(self, regional_grid):
        coverage = compute_target_coverage(regional_grid, [42.0, 200.0], [0.0, 1.0])
        assert 0 < coverage["points_in_source"] < coverage["n_target_points"]
        assert "REMAP_COVERAGE_PARTIAL" in coverage["warning_codes"]

    def test_source_bbox_is_reported(self, regional_grid):
        bbox = compute_target_coverage(regional_grid, [42.0], [0.0])["source_bbox"]
        assert bbox["lon_min"] < bbox["lon_max"]
        assert bbox["lat_min"] < bbox["lat_max"]

    def test_nearest_neighbor_is_flagged_as_non_conservative(self, regional_grid):
        coverage = compute_target_coverage(
            regional_grid, [42.0], [0.0], method="nearest_neighbor"
        )
        assert coverage["method_is_conservative"] is False
        assert "REMAP_METHOD_NOT_CONSERVATIVE" in coverage["warning_codes"]

    def test_conservative_method_is_not_flagged(self, regional_grid):
        coverage = compute_target_coverage(
            regional_grid, [42.0], [0.0], method="conservative"
        )
        assert coverage["method_is_conservative"] is True
        assert "REMAP_METHOD_NOT_CONSERVATIVE" not in coverage["warning_codes"]

    @pytest.mark.parametrize(
        "method,expected",
        [
            ("conservative", True),
            ("CONSERVATIVE_NORMED", True),
            ("nearest_neighbor", False),
            ("inverse_distance_weighted", False),
            (None, False),
        ],
    )
    def test_method_is_conservative(self, method, expected):
        assert method_is_conservative(method) is expected


class TestRemapToRectilinearCoverage:
    def test_zero_coverage_result_says_so(self, state_dir, regional_mesh_files):
        grid_file, data_file = regional_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = remap_to_rectilinear(
                "temperature",
                list(np.arange(-180, 180, 72.0)),
                list(np.arange(-60, 61, 30.0)),
                grid_path=grid_file,
                data_path=data_file,
            )
        coverage = result["source_coverage"]
        assert coverage["points_in_source"] == 0
        assert coverage["n_target_points"] == 25
        joined = " ".join(result["_provenance"]["warnings"])
        assert "REMAP_COVERAGE_ZERO" in joined
        assert "REMAP_METHOD_NOT_CONSERVATIVE" in joined

    def test_front_door_marks_zero_coverage_not_interpretable(
        self, state_dir, regional_mesh_files
    ):
        grid_file, data_file = regional_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_analysis(
                operation="remap_to_rectilinear",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
                target_lon=list(np.arange(-180, 180, 72.0)),
                target_lat=list(np.arange(-60, 61, 30.0)),
            )
        status = result["scientific_status"]
        assert status["status"] == "warning"
        assert status["physically_interpretable"] is False
        assert "REMAP_COVERAGE_ZERO" in status["warning_codes"]

    def test_full_coverage_still_flags_non_conservative(
        self, state_dir, regional_mesh_files
    ):
        grid_file, data_file = regional_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_analysis(
                operation="remap_to_rectilinear",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
                target_lon=[42.0, 44.0],
                target_lat=[0.0, 1.0],
            )
        coverage = result["source_coverage"]
        assert coverage["coverage_fraction"] == 1.0
        assert result["scientific_status"]["warning_codes"] == [
            "REMAP_METHOD_NOT_CONSERVATIVE"
        ]
