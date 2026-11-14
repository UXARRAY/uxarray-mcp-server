"""Temporal and ensemble ops in the pure core layer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from uxarray_mcp.core.temporal import (
    anomaly,
    ensemble_mean,
    ensemble_spread,
    temporal_mean,
)

N_ELEMENT = 6


def _write(tmp_path, name, n_time, mode="full"):
    times = pd.date_range("2000-01-01", periods=n_time, freq="MS")
    values = np.arange(n_time * N_ELEMENT, dtype=float).reshape(n_time, N_ELEMENT)
    if mode == "all_nan":
        values[:] = np.nan
    elif mode == "ragged":
        values[1:, 0] = np.nan
        values[2:, 1] = np.nan
    path = tmp_path / name
    xr.Dataset({"t2m": (("time", "n_face"), values)}, coords={"time": times}).to_netcdf(
        path
    )
    return str(path)


def test_temporal_mean_over_a_full_series(time_series_dataset):
    result = temporal_mean(time_series_dataset, "temperature")
    assert result["summary"]["shape"] == [2]
    assert result["summary"]["mean"] == pytest.approx(282.5)
    coverage = result["temporal_coverage"]
    assert coverage["n_time"] == 3
    assert coverage["samples_min"] == coverage["samples_max"] == 3
    assert result["warning_codes"] == []
    assert isinstance(result["_payload"], xr.DataArray)
    assert result["_payload"].dims == ("sample",)


def test_temporal_mean_over_nothing_is_zero_coverage(tmp_path):
    result = temporal_mean(_write(tmp_path, "nan.nc", 12, "all_nan"), "t2m")
    assert result["coverage"]["n_time"] == 12
    assert result["coverage"]["n_elements_with_value"] == 0
    assert result["warning_codes"] == ["TEMPORAL_COVERAGE_ZERO"]
    assert result["summary"]["mean"] is None


def test_temporal_mean_ragged_grouped_and_sliced(tmp_path):
    path = _write(tmp_path, "ragged.nc", 12, "ragged")
    ragged = temporal_mean(path, "t2m")
    assert ragged["warning_codes"] == ["TEMPORAL_SAMPLES_RAGGED"]
    assert (ragged["coverage"]["samples_min"], ragged["coverage"]["samples_max"]) == (
        1,
        12,
    )
    grouped = temporal_mean(path, "t2m", groupby="month")
    assert grouped["coverage"]["n_bins"] == 12
    assert "TEMPORAL_BINS_SINGLE_SAMPLE" in grouped["warning_codes"]
    assert grouped["_payload"].dims == ("month", "n_face")
    sliced = temporal_mean(path, "t2m", time_min="2000-03", time_max="2000-03")
    assert sliced["coverage"]["n_time"] == 1
    assert sliced["warning_codes"] == ["TEMPORAL_SINGLE_SAMPLE"]
    with pytest.raises(ValueError, match="No time steps fall"):
        temporal_mean(path, "t2m", time_min="2010-01", time_max="2010-12")


def test_anomaly_keeps_time_and_measures_the_baseline(time_series_dataset):
    result = anomaly(time_series_dataset, "temperature")
    assert result["summary"]["shape"] == [3, 2]
    assert result["summary"]["mean"] == pytest.approx(0.0)
    assert result["summary"]["max"] == pytest.approx(2.0)
    assert result["temporal_coverage"]["n_time"] == 3
    assert result["warning_codes"] == []
    assert isinstance(result["_payload"], xr.DataArray)
    with pytest.raises(ValueError, match="baseline"):
        anomaly(time_series_dataset, "temperature", baseline="climatology")


def test_anomaly_over_nothing_is_zero_coverage(tmp_path):
    result = anomaly(_write(tmp_path, "nan.nc", 4, "all_nan"), "t2m")
    assert result["warning_codes"] == ["TEMPORAL_COVERAGE_ZERO"]


def test_missing_variable_or_time_dimension_is_refused(tmp_path):
    path = tmp_path / "flat.nc"
    xr.Dataset({"x": (["n_face"], np.ones(3))}).to_netcdf(path)
    with pytest.raises(ValueError, match="not found"):
        temporal_mean(str(path), "y")
    with pytest.raises(ValueError, match="'time' dimension"):
        temporal_mean(str(path), "x")


def test_ensemble_mean_and_spread(ensemble_data_files):
    mean = ensemble_mean("temperature", ensemble_data_files)
    assert mean["member_count"] == 2
    assert mean["summary"]["mean"] == pytest.approx(283.0)
    assert mean["member_evidence"]["units_consistent"] is True
    assert mean["member_evidence"]["grid_evidence"] == "dims_and_shape_only"
    assert mean["coverage"] == {
        "member_count": 2,
        "n_elements": 2,
        "n_elements_with_value": 2,
    }
    assert mean["warning_codes"] == ["ENSEMBLE_GRID_UNVERIFIED"]
    assert isinstance(mean["_payload"], xr.DataArray)
    spread = ensemble_spread("temperature", ensemble_data_files)
    assert spread["summary"]["mean"] == pytest.approx(2.0)
    assert spread["_payload"].dims == ("sample",)


def test_ensemble_over_nothing_and_mismatched_units(tmp_path):
    a, b = tmp_path / "a.nc", tmp_path / "b.nc"
    xr.Dataset(
        {"t": (["n_face"], np.full(3, np.nan), {"units": "K"})},
        coords={"lon": (["n_face"], [0.0, 1.0, 2.0])},
    ).to_netcdf(a)
    xr.Dataset(
        {"t": (["n_face"], np.full(3, np.nan), {"units": "degC"})},
        coords={"lon": (["n_face"], [0.0, 1.0, 2.0])},
    ).to_netcdf(b)
    result = ensemble_mean("t", [str(a), str(b)])
    assert result["coverage"]["n_elements_with_value"] == 0
    assert result["member_evidence"]["grids_consistent"] is True
    assert result["warning_codes"] == [
        "ENSEMBLE_COVERAGE_ZERO",
        "ENSEMBLE_UNITS_MISMATCHED",
    ]
    with pytest.raises(ValueError, match="At least one"):
        ensemble_mean("t", [])
