"""Coverage reporting for remapping onto a target grid (issue #85)."""

import warnings

import numpy as np
import pytest

from uxarray_mcp.domain.remap_coverage import (
    compute_scattered_coverage,
    compute_target_coverage,
    method_is_conservative,
)
from uxarray_mcp.preconditions import OVERRIDE_TOKEN
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


class TestComputeScatteredCoverage:
    def test_paired_points_are_not_multiplied_out(self, regional_grid):
        # One point inside the source and one far outside. As a cartesian
        # product these two longitudes and two latitudes would be four
        # points; paired they are two, and only the first is covered.
        coverage = compute_scattered_coverage(regional_grid, [42.0, 200.0], [0.0, 40.0])
        assert coverage["n_target_points"] == 2
        assert coverage["points_in_source"] == 1
        assert "REMAP_COVERAGE_PARTIAL" in coverage["warning_codes"]

    def test_target_entirely_outside_reports_zero(self, regional_grid):
        coverage = compute_scattered_coverage(
            regional_grid, [10.0, 10.5, 11.0], [0.0, 0.5, 1.0]
        )
        assert coverage["points_in_source"] == 0
        assert coverage["coverage_fraction"] == 0.0
        assert "REMAP_COVERAGE_ZERO" in coverage["warning_codes"]

    def test_mismatched_shapes_are_refused(self, regional_grid):
        # Silently broadcasting or truncating here would report coverage for
        # a point set the caller never asked about.
        with pytest.raises(ValueError, match="same shape"):
            compute_scattered_coverage(regional_grid, [42.0, 43.0], [0.0])

    def test_longitudes_are_wrapped_before_testing(self, regional_grid):
        # 402 degrees is 42 degrees, which is inside the source mesh.
        coverage = compute_scattered_coverage(regional_grid, [402.0], [0.0])
        assert coverage["points_in_source"] == 1


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

    def test_front_door_refuses_zero_coverage(self, state_dir, regional_mesh_files):
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
        assert result["outcome"] == "input_required"
        assert [c["id"] for c in result["refusal"]["failed_checks"]] == [
            "remap_coverage_nonzero"
        ]
        # No number came back, which is the whole point: a mean computed
        # entirely outside the source mesh is not a remap of anything.
        assert "stats" not in result

    def test_front_door_zero_coverage_override_returns_unverified(
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
                acknowledge=OVERRIDE_TOKEN,
            )
        status = result["scientific_status"]
        assert status["status"] == "unverified"
        assert status["physically_interpretable"] is False
        assert "REMAP_COVERAGE_ZERO" in status["warning_codes"]
        assert result["stats"]["mean"] is not None

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


@pytest.fixture
def overlapping_target_grid(tmp_path):
    """Target mesh sitting inside the regional source mesh extent."""
    import uxarray as ux

    grid = ux.Grid.from_structured(
        lon=np.arange(42, 46, 1.0), lat=np.arange(-1, 2, 1.0)
    )
    path = tmp_path / "overlapping_target.nc"
    grid.to_xarray().to_netcdf(path)
    return str(path)


class TestGridToGridCoverage:
    """A remap onto another mesh fills every target point too (issue #21).

    ``remap_target_grid`` sits at lon 10-11 and the regional source at lon
    40-47, so these calls used to return a full array of plausible numbers
    with ``outcome: complete`` and no coverage reported at all.
    """

    @pytest.mark.parametrize("operation", ["remap_variable", "regrid_dataset"])
    def test_front_door_refuses_a_target_outside_the_source(
        self, state_dir, regional_mesh_files, remap_target_grid, operation
    ):
        grid_file, data_file = regional_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_analysis(
                operation=operation,
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
                target_grid_path=remap_target_grid,
            )
        assert result["outcome"] == "input_required"
        check = result["refusal"]["failed_checks"][0]
        assert check["id"] == "remap_coverage_nonzero"
        # The repair has to name an argument this caller actually passes;
        # target_lon/target_lat belong to the rectilinear operation.
        assert "target_grid_path" in check["repair"]
        assert "target_lon" not in check["repair"]

    def test_override_returns_the_number_marked_unverified(
        self, state_dir, regional_mesh_files, remap_target_grid
    ):
        grid_file, data_file = regional_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_analysis(
                operation="remap_variable",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
                target_grid_path=remap_target_grid,
                acknowledge=OVERRIDE_TOKEN,
            )
        status = result["scientific_status"]
        assert status["status"] == "unverified"
        assert status["physically_interpretable"] is False
        assert "REMAP_COVERAGE_ZERO" in status["warning_codes"]
        assert result["source_coverage"]["points_in_source"] == 0

    def test_overlapping_target_completes_with_full_coverage(
        self, state_dir, regional_mesh_files, overlapping_target_grid
    ):
        grid_file, data_file = regional_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_analysis(
                operation="remap_variable",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
                target_grid_path=overlapping_target_grid,
            )
        assert result["outcome"] == "complete"
        assert result["source_coverage"]["coverage_fraction"] == 1.0
        assert result["preconditions"]["status"] == "satisfied"
