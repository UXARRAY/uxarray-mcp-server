"""Pure coverage measurements and their warning codes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from uxarray_mcp.core.coverage import (
    anomaly_coverage_warning_codes,
    compute_anomaly_coverage,
    compute_mesh_coverage,
    compute_profile_coverage,
    compute_scattered_coverage,
    compute_subset_coverage,
    compute_target_coverage,
    compute_temporal_coverage,
    count_face_centers_in_bounds,
    export_fidelity_warning_codes,
    mesh_coverage_warning_codes,
    mesh_extent,
    method_is_conservative,
    profile_coverage_warning_codes,
    subset_coverage_warning_codes,
    temporal_coverage_warning_codes,
)


@pytest.fixture
def regional_grid():
    import uxarray as ux

    return ux.Grid.from_structured(
        lon=np.arange(40, 48, 2.0), lat=np.arange(-2, 3, 1.0)
    )


# --- mesh ---------------------------------------------------------------------


def test_global_mesh_is_closed_and_covers_the_sphere(earth_radius_mesh_files):
    import uxarray as ux

    grid = ux.open_grid(earth_radius_mesh_files[0])
    coverage = compute_mesh_coverage(grid)
    assert coverage["sphere_fraction"] == pytest.approx(1.0, abs=1e-3)
    assert coverage["closed"] is True
    assert coverage["euler_characteristic"] == 2
    assert mesh_coverage_warning_codes(coverage) == []


def test_regional_mesh_is_not_global(regional_grid):
    coverage = compute_mesh_coverage(regional_grid)
    assert coverage["sphere_fraction"] < 0.01
    assert coverage["closed"] is False
    assert mesh_coverage_warning_codes(coverage) == ["MESH_NOT_GLOBAL"]


# --- profile / anomaly --------------------------------------------------------


def test_profile_coverage_separates_empty_bins_from_missing_data():
    full = compute_profile_coverage([1.0, 2.0], source=np.ones(4))
    assert full["cause"] == "none" and profile_coverage_warning_codes(full) == []
    empty = compute_profile_coverage([np.nan, np.nan], source=np.ones(4))
    assert empty["cause"] == "bins_miss_mesh"
    assert profile_coverage_warning_codes(empty) == ["PROFILE_COVERAGE_ZERO"]
    partial = compute_profile_coverage([1.0, np.nan], source=[1.0, np.nan])
    assert partial["cause"] == "ambiguous"
    assert profile_coverage_warning_codes(partial) == ["PROFILE_COVERAGE_PARTIAL"]


def test_anomaly_coverage_counts_lost_data_not_masked_faces():
    lost = compute_anomaly_coverage([1.0, np.nan], source=[1.0, 2.0])
    assert lost["n_face_data_lost"] == 1
    assert anomaly_coverage_warning_codes(lost) == ["ANOMALY_COVERAGE_PARTIAL"]
    masked = compute_anomaly_coverage([1.0, np.nan], source=[1.0, np.nan])
    assert masked["cause"] == "missing_input"
    assert anomaly_coverage_warning_codes(masked) == []
    assert anomaly_coverage_warning_codes(compute_anomaly_coverage([np.nan])) == [
        "ANOMALY_COVERAGE_ZERO"
    ]


# --- subset -------------------------------------------------------------------


def test_subset_coverage_reports_counts_rule_and_extent(regional_grid):
    extent = mesh_extent(regional_grid)
    assert extent["lon_min"] == pytest.approx(40.0)
    coverage = compute_subset_coverage(
        regional_grid.n_face,
        0,
        extent=extent,
        selection_rule="face_bounds_within",
        n_face_centers_in_bounds=count_face_centers_in_bounds(
            regional_grid, [40.0, 44.0], [-2.5, 2.5]
        ),
    )
    assert coverage["n_face_centers_in_bounds"] == 15
    assert coverage["selection_rule"] == "face_bounds_within"
    assert subset_coverage_warning_codes(coverage) == ["SUBSET_COVERAGE_ZERO"]
    assert subset_coverage_warning_codes(compute_subset_coverage(81, 1)) == []
    assert subset_coverage_warning_codes(compute_subset_coverage(0, 0)) == []


# --- remap --------------------------------------------------------------------


def test_rectilinear_target_off_the_mesh_is_zero_coverage(regional_grid):
    coverage = compute_target_coverage(
        regional_grid, np.arange(-180, 180, 72.0), np.arange(-60, 61, 30.0)
    )
    assert coverage["n_target_points"] == 25
    assert coverage["points_in_source"] == 0
    assert coverage["coverage_fraction"] == 0.0
    assert "REMAP_COVERAGE_ZERO" in coverage["warning_codes"]


def test_scattered_target_wraps_longitude_and_flags_partial(regional_grid):
    coverage = compute_scattered_coverage(regional_grid, [402.0, 100.0], [0.0, 0.0])
    assert coverage["points_in_source"] == 1
    assert "REMAP_COVERAGE_PARTIAL" in coverage["warning_codes"]
    with pytest.raises(ValueError, match="same shape"):
        compute_scattered_coverage(regional_grid, [42.0, 43.0], [0.0])


@pytest.mark.parametrize(
    ("method", "expected"),
    [("nearest_neighbor", False), ("conservative", True), (None, False)],
)
def test_conservation_is_judged_by_method_name(method, expected):
    assert method_is_conservative(method) is expected


# --- temporal -----------------------------------------------------------------


def _series(values):
    array = np.asarray(values, dtype=float)
    times = pd.date_range("2000-01-01", periods=array.shape[0], freq="MS")
    return xr.DataArray(array, dims=("time", "n_face"), coords={"time": times})


def test_temporal_coverage_reports_ragged_samples_and_bins():
    source = _series([[1.0, 1.0], [np.nan, 2.0], [np.nan, 3.0]])
    coverage = compute_temporal_coverage(source, source.mean("time"))
    assert (coverage["n_time"], coverage["samples_min"], coverage["samples_max"]) == (
        3,
        1,
        3,
    )
    assert temporal_coverage_warning_codes(coverage) == ["TEMPORAL_SAMPLES_RAGGED"]
    grouped = compute_temporal_coverage(
        source, source.groupby("time.month").mean(), groupby="month"
    )
    assert grouped["n_bins"] == 3 and grouped["bin_occupancy_min"] == 1
    assert "TEMPORAL_BINS_SINGLE_SAMPLE" in temporal_coverage_warning_codes(grouped)


def test_temporal_coverage_zero_and_single_sample_codes():
    empty = _series([[np.nan, np.nan]] * 3)
    assert temporal_coverage_warning_codes(
        compute_temporal_coverage(empty, empty.mean("time"))
    ) == ["TEMPORAL_COVERAGE_ZERO"]
    single = _series([[1.0, 2.0]])
    assert temporal_coverage_warning_codes(
        compute_temporal_coverage(single, single.mean("time"))
    ) == ["TEMPORAL_SINGLE_SAMPLE"]


# --- export -------------------------------------------------------------------


def test_export_fidelity_codes():
    assert export_fidelity_warning_codes({}) == []
    assert export_fidelity_warning_codes({"bytes_written": 0}) == ["EXPORT_EMPTY_FILE"]
    assert export_fidelity_warning_codes(
        {"bytes_written": 10, "rows_written": 8, "rows_expected": 9}
    ) == ["EXPORT_ROW_COUNT_MISMATCH"]
