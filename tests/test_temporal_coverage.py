"""A temporal mean and a temporal anomaly say how much time they averaged.

Both operations reduce along ``time`` and both return a full-length array
whatever went in, so the degenerate cases are shaped exactly like answers.
Measured before this gate existed, on a 6-element, 12-step file: an all-NaN
variable returned ``outcome: complete`` with a field of NaN, a one-step file
returned an "anomaly" of exactly 0.0 everywhere, and a file with 1, 2 and 12
usable steps at different elements returned one finite mean over all of them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from uxarray_mcp.domain.temporal_coverage import (
    compute_temporal_coverage,
    temporal_coverage_warning_codes,
)
from uxarray_mcp.preconditions import (
    OVERRIDE_TOKEN,
    PreconditionRefusal,
    evaluate_temporal_anomaly_preconditions,
)
from uxarray_mcp.tools.frontdoor import run_analysis

N_ELEMENT = 6


def _write(
    tmp_path,
    name: str,
    n_time: int,
    *,
    mode: str = "full",
    freq: str = "MS",
) -> str:
    """A face-dimensioned variable over ``n_time`` monthly steps."""
    times = pd.date_range("2000-01-01", periods=n_time, freq=freq)
    values = np.arange(n_time * N_ELEMENT, dtype=float).reshape(n_time, N_ELEMENT)
    if mode == "all_nan":
        values[:] = np.nan
    elif mode == "half_masked":
        values[:, N_ELEMENT // 2 :] = np.nan
    elif mode == "ragged":
        # Element 0 keeps one step and element 1 keeps two; the rest keep all
        # of them, so a single mean mixes 1-, 2- and n_time-sample estimates.
        values[1:, 0] = np.nan
        values[2:, 1] = np.nan
    path = tmp_path / name
    xr.Dataset({"t2m": (("time", "n_face"), values)}, coords={"time": times}).to_netcdf(
        path
    )
    return str(path)


def _series(values, times=None) -> xr.DataArray:
    array = np.asarray(values, dtype=float)
    if times is None:
        times = pd.date_range("2000-01-01", periods=array.shape[0], freq="MS")
    return xr.DataArray(array, dims=("time", "n_face"), coords={"time": times})


# --- the measurement -------------------------------------------------------


def test_a_complete_series_reports_every_step_at_every_element():
    source = _series([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    coverage = compute_temporal_coverage(source, source.mean(dim="time"))
    assert coverage["n_time"] == 3
    assert coverage["samples_min"] == 3
    assert coverage["samples_max"] == 3
    assert coverage["n_elements"] == 2
    assert coverage["n_elements_with_value"] == 2
    assert coverage["n_series_with_data"] == 2


def test_an_element_that_never_held_data_is_kept_out_of_the_sample_range():
    # Left column full, right column entirely missing. The minimum must not
    # collapse to zero, or every land-masked field would look ragged.
    source = _series([[1.0, np.nan], [2.0, np.nan], [3.0, np.nan]])
    coverage = compute_temporal_coverage(source, source.mean(dim="time"))
    assert coverage["samples_min"] == 3
    assert coverage["samples_max"] == 3
    assert coverage["n_series"] == 2
    assert coverage["n_series_with_data"] == 1
    assert coverage["n_elements_with_value"] == 1


def test_uneven_sample_counts_are_reported_as_a_range():
    source = _series([[1.0, 1.0], [np.nan, 2.0], [np.nan, 3.0]])
    coverage = compute_temporal_coverage(source, source.mean(dim="time"))
    assert coverage["samples_min"] == 1
    assert coverage["samples_max"] == 3


def test_a_source_with_no_time_dimension_leaves_the_counts_unknown():
    source = xr.DataArray(np.array([1.0, 2.0]), dims=("n_face",))
    coverage = compute_temporal_coverage(source, source)
    assert coverage["n_time"] is None
    assert coverage["samples_min"] is None
    assert coverage["n_series_with_data"] is None
    # The result was still readable, so its own size is known.
    assert coverage["n_elements"] == 2


def test_bin_occupancy_counts_time_steps_not_usable_values():
    # Three monthly steps, one entirely missing. The bin still holds a step.
    source = _series([[1.0, 1.0], [np.nan, np.nan], [3.0, 3.0]])
    coverage = compute_temporal_coverage(
        source, source.groupby("time.month").mean(), groupby="month"
    )
    assert coverage["n_bins"] == 3
    assert coverage["bin_occupancy_min"] == 1
    assert coverage["bin_occupancy_max"] == 1


def test_a_season_grouping_over_a_year_fills_each_bin_three_times():
    times = pd.date_range("2000-01-01", periods=12, freq="MS")
    source = _series(np.ones((12, 2)), times=times)
    coverage = compute_temporal_coverage(
        source, source.groupby("time.season").mean(), groupby="season"
    )
    assert coverage["n_bins"] == 4
    assert coverage["bin_occupancy_min"] == 3
    assert coverage["bin_occupancy_max"] == 3


def test_an_ungroupable_source_omits_the_bin_block_rather_than_guessing():
    source = xr.DataArray(np.ones((2, 2)), dims=("time", "n_face"))
    coverage = compute_temporal_coverage(source, source, groupby="month")
    assert "n_bins" not in coverage
    assert coverage["groupby"] == "month"


# --- the codes -------------------------------------------------------------


def test_a_full_series_earns_no_code():
    coverage = {
        "n_elements": 6,
        "n_elements_with_value": 6,
        "n_time": 12,
        "samples_min": 12,
        "samples_max": 12,
    }
    assert temporal_coverage_warning_codes(coverage) == []


def test_an_empty_result_reports_zero_coverage_alone():
    coverage = {
        "n_elements": 6,
        "n_elements_with_value": 0,
        "n_time": 1,
        "samples_min": None,
        "samples_max": None,
    }
    assert temporal_coverage_warning_codes(coverage) == ["TEMPORAL_COVERAGE_ZERO"]


def test_a_single_step_is_flagged():
    coverage = {
        "n_elements": 6,
        "n_elements_with_value": 6,
        "n_time": 1,
        "samples_min": 1,
        "samples_max": 1,
    }
    assert temporal_coverage_warning_codes(coverage) == ["TEMPORAL_SINGLE_SAMPLE"]


def test_a_single_step_does_not_also_report_its_bins():
    # Every bin of a one-step file holds that one step; the single-sample code
    # already said so and repeating it per bin adds nothing.
    coverage = {
        "n_elements": 6,
        "n_elements_with_value": 6,
        "n_time": 1,
        "samples_min": 1,
        "samples_max": 1,
        "bin_occupancy_min": 1,
    }
    assert temporal_coverage_warning_codes(coverage) == ["TEMPORAL_SINGLE_SAMPLE"]


def test_uneven_samples_are_flagged():
    coverage = {
        "n_elements": 6,
        "n_elements_with_value": 6,
        "n_time": 12,
        "samples_min": 1,
        "samples_max": 12,
    }
    assert temporal_coverage_warning_codes(coverage) == ["TEMPORAL_SAMPLES_RAGGED"]


def test_a_bin_holding_one_step_is_flagged():
    coverage = {
        "n_elements": 18,
        "n_elements_with_value": 18,
        "n_time": 3,
        "samples_min": 3,
        "samples_max": 3,
        "bin_occupancy_min": 1,
    }
    assert temporal_coverage_warning_codes(coverage) == ["TEMPORAL_BINS_SINGLE_SAMPLE"]


def test_an_empty_array_earns_no_code():
    assert temporal_coverage_warning_codes({"n_elements": 0}) == []


# --- temporal_mean end to end ---------------------------------------------


def test_a_full_series_is_interpretable(tmp_path):
    result = run_analysis(
        operation="temporal_mean",
        data_path=_write(tmp_path, "full.nc", 12),
        variable_name="t2m",
    )
    assert result["outcome"] == "complete"
    status = result["scientific_status"]
    assert status["status"] == "complete"
    assert status["physically_interpretable"] is True
    assert status["warning_codes"] == []
    assert result["temporal_coverage"]["n_time"] == 12


def test_a_mean_over_nothing_refuses(tmp_path):
    result = run_analysis(
        operation="temporal_mean",
        data_path=_write(tmp_path, "nan.nc", 12, mode="all_nan"),
        variable_name="t2m",
    )
    assert result["outcome"] == "input_required"
    failed = result["refusal"]["failed_checks"]
    assert [check["id"] for check in failed] == ["temporal_coverage_nonzero"]
    assert "12 time steps" in failed[0]["detail"]
    assert "summary" not in result


def test_a_mean_over_one_step_warns_and_still_answers(tmp_path):
    # The value is real; calling it a climatology is what is wrong, so this
    # returns the number with a code rather than refusing.
    result = run_analysis(
        operation="temporal_mean",
        data_path=_write(tmp_path, "one.nc", 1),
        variable_name="t2m",
    )
    assert result["outcome"] == "complete"
    status = result["scientific_status"]
    assert status["status"] == "warning"
    assert status["physically_interpretable"] is False
    assert "TEMPORAL_SINGLE_SAMPLE" in status["warning_codes"]
    assert result["summary"]["mean"] == pytest.approx(2.5)


def test_uneven_samples_warn(tmp_path):
    result = run_analysis(
        operation="temporal_mean",
        data_path=_write(tmp_path, "ragged.nc", 12, mode="ragged"),
        variable_name="t2m",
    )
    assert result["scientific_status"]["warning_codes"] == ["TEMPORAL_SAMPLES_RAGGED"]
    coverage = result["temporal_coverage"]
    assert coverage["samples_min"] == 1
    assert coverage["samples_max"] == 12


def test_an_ordinary_masked_field_neither_refuses_nor_warns(tmp_path):
    # Half the elements never carried data. That is a land mask, not a defect,
    # and a code that fires here would be ignored everywhere else.
    result = run_analysis(
        operation="temporal_mean",
        data_path=_write(tmp_path, "half.nc", 12, mode="half_masked"),
        variable_name="t2m",
    )
    assert result["outcome"] == "complete"
    assert result["scientific_status"]["warning_codes"] == []
    coverage = result["temporal_coverage"]
    assert coverage["n_series_with_data"] == N_ELEMENT // 2
    assert coverage["samples_min"] == 12


def test_a_monthly_climatology_from_one_year_says_each_month_is_one_sample(tmp_path):
    result = run_analysis(
        operation="temporal_mean",
        data_path=_write(tmp_path, "three.nc", 3),
        variable_name="t2m",
        groupby="month",
    )
    assert result["scientific_status"]["warning_codes"] == [
        "TEMPORAL_BINS_SINGLE_SAMPLE"
    ]
    assert result["temporal_coverage"]["bin_occupancy_min"] == 1


def test_a_seasonal_mean_over_a_full_year_is_quiet(tmp_path):
    result = run_analysis(
        operation="temporal_mean",
        data_path=_write(tmp_path, "year.nc", 12),
        variable_name="t2m",
        groupby="season",
    )
    assert result["scientific_status"]["warning_codes"] == []
    assert result["temporal_coverage"]["n_bins"] == 4


def test_the_override_returns_the_empty_mean_marked_uninterpretable(tmp_path):
    result = run_analysis(
        operation="temporal_mean",
        data_path=_write(tmp_path, "nan2.nc", 12, mode="all_nan"),
        variable_name="t2m",
        acknowledge=OVERRIDE_TOKEN,
    )
    assert result["outcome"] == "complete"
    assert result["preconditions"]["status"] == "overridden"
    assert result["scientific_status"]["physically_interpretable"] is False
    assert (
        "PRECONDITION_FAILED_TEMPORAL_COVERAGE_NONZERO"
        in (result["scientific_status"]["warning_codes"])
    )


# --- anomaly end to end ----------------------------------------------------


def test_an_anomaly_over_a_full_series_is_interpretable(tmp_path):
    result = run_analysis(
        operation="anomaly",
        data_path=_write(tmp_path, "afull.nc", 12),
        variable_name="t2m",
    )
    assert result["outcome"] == "complete"
    assert result["scientific_status"]["physically_interpretable"] is True
    assert result["temporal_coverage"]["n_time"] == 12


def test_an_anomaly_against_a_one_step_baseline_refuses(tmp_path):
    # Every value would be exactly zero, whatever the data said.
    result = run_analysis(
        operation="anomaly",
        data_path=_write(tmp_path, "aone.nc", 1),
        variable_name="t2m",
    )
    assert result["outcome"] == "input_required"
    failed = result["refusal"]["failed_checks"]
    assert [check["id"] for check in failed] == ["anomaly_baseline_multisample"]
    assert "zero by construction" in failed[0]["repair"]


def test_an_anomaly_with_no_data_refuses_on_coverage(tmp_path):
    result = run_analysis(
        operation="anomaly",
        data_path=_write(tmp_path, "anan.nc", 12, mode="all_nan"),
        variable_name="t2m",
    )
    assert [check["id"] for check in result["refusal"]["failed_checks"]] == [
        "temporal_coverage_nonzero"
    ]


def test_the_anomaly_gate_keeps_both_checks():
    checks = evaluate_temporal_anomaly_preconditions(
        "anomaly",
        {"n_elements": 6, "n_elements_with_value": 6, "n_time": 12},
    )
    assert [check["id"] for check in checks] == [
        "temporal_coverage_nonzero",
        "anomaly_baseline_multisample",
    ]
    assert all(check["passed"] for check in checks)


def test_an_unknown_step_count_does_not_refuse_the_baseline_check():
    # A worker that could not report `n_time` leaves the count unknown, and
    # unknown must not be treated as one.
    checks = evaluate_temporal_anomaly_preconditions(
        "anomaly",
        {"n_elements": 6, "n_elements_with_value": 6, "n_time": None},
    )
    assert all(check["passed"] for check in checks)


def test_the_override_returns_the_zero_anomaly_marked_uninterpretable(tmp_path):
    result = run_analysis(
        operation="anomaly",
        data_path=_write(tmp_path, "aone2.nc", 1),
        variable_name="t2m",
        acknowledge=OVERRIDE_TOKEN,
    )
    assert result["outcome"] == "complete"
    assert result["preconditions"]["status"] == "overridden"
    assert result["summary"]["max"] == pytest.approx(0.0)
    assert result["scientific_status"]["physically_interpretable"] is False


def test_a_variable_without_a_time_dimension_still_fails_on_its_own_terms(tmp_path):
    # The gate must not swallow the pre-existing error for a variable that has
    # no time axis at all; that is a different problem with a different fix.
    path = tmp_path / "notime.nc"
    xr.Dataset({"t2m": (("n_face",), np.arange(N_ELEMENT, dtype=float))}).to_netcdf(
        path
    )
    with pytest.raises((ValueError, PreconditionRefusal), match="time"):
        run_analysis(
            operation="temporal_mean", data_path=str(path), variable_name="t2m"
        )
