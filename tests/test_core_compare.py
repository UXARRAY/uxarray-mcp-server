"""Field comparison in the pure core layer."""

from __future__ import annotations

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.core.compare import (
    bias,
    compare_fields,
    normalize_units,
    pattern_correlation,
    pattern_correlation_fields,
    rmse,
)


@pytest.fixture
def latitude_banded_comparison(tmp_path):
    """+2 K in the tropics, -2 K at the poles: cell-count and area-weighted
    means disagree in sign on a lat-lon mesh."""
    grid = ux.Grid.from_structured(
        lon=np.arange(0, 360, 10.0), lat=np.arange(-85, 86, 10.0)
    )
    grid_file = tmp_path / "banded_grid.nc"
    grid.to_xarray().to_netcdf(grid_file)
    perturbed = np.where(np.abs(np.asarray(grid.face_lat)) < 30, 2.0, -2.0)
    a, b = tmp_path / "a.nc", tmp_path / "b.nc"
    xr.Dataset({"t": (["n_face"], perturbed)}).to_netcdf(a)
    xr.Dataset({"t": (["n_face"], np.zeros(grid.n_face))}).to_netcdf(b)
    return str(grid_file), str(a), str(b)


def _plain_pair(tmp_path, units_a=None, units_b=None):
    a, b = tmp_path / "pa.nc", tmp_path / "pb.nc"
    attrs_a = {"units": units_a} if units_a else {}
    attrs_b = {"units": units_b} if units_b else {}
    xr.Dataset({"t": (["n_face"], np.array([1.0, 2.0, 3.0]), attrs_a)}).to_netcdf(a)
    xr.Dataset({"t": (["n_face"], np.zeros(3), attrs_b)}).to_netcdf(b)
    return str(a), str(b)


def test_compare_fields_returns_expected_metrics(comparison_mesh_with_data):
    grid_file, data_a, data_b = comparison_mesh_with_data
    result = compare_fields("temperature", data_a, data_b, grid_file)
    assert result["metrics"]["bias"] == -2.0
    assert result["metrics"]["rmse"] == 2.0
    assert result["metrics"]["pattern_correlation"] == 0.0
    assert result["metrics"]["max_abs_difference"] == 2.0
    assert result["units"] == {"a": "K", "b": "K", "comparable": True}
    assert result["coverage"] == {"n_elements": 1, "n_elements_finite": 1}
    assert result["warning_codes"] == []
    assert isinstance(result["_payload"], xr.DataArray)
    assert float(result["_payload"].values[0]) == -2.0


def test_bias_is_area_weighted_not_cell_counted(latitude_banded_comparison):
    grid_file, a, b = latitude_banded_comparison
    result = compare_fields("t", a, b, grid_file)
    assert result["area_weighting"]["weighted"] is True
    assert result["area_weighting"]["equal_area"] is False
    assert result["area_weighting"]["area_ratio_max_over_min"] > 10
    assert 0 < result["metrics"]["bias"] < 0.05


def test_pattern_correlation_is_area_weighted(latitude_banded_comparison):
    grid_file, a, b = latitude_banded_comparison
    first = ux.open_dataset(grid_file, a)["t"].to_xarray()
    lat_field = first.copy(data=np.abs(np.asarray(ux.open_grid(grid_file).face_lat)))
    areas = xr.DataArray(
        np.asarray(ux.open_grid(grid_file).face_areas), dims=["n_face"]
    )
    weighted = pattern_correlation(first, lat_field, areas)
    unweighted = pattern_correlation(first, lat_field, None)
    assert abs(unweighted) > 0.5
    assert weighted != pytest.approx(unweighted, abs=1e-3)


def test_unweighted_comparison_discloses_it(tmp_path):
    a, b = _plain_pair(tmp_path)
    result = compare_fields("t", a, b, grid_path=None)
    assert result["area_weighting"]["weighted"] is False
    assert "AREA_WEIGHTING_UNAVAILABLE" in result["warning_codes"]
    assert "UNITS_UNDECLARED" in result["warning_codes"]
    assert result["units"] == {"a": None, "b": None, "comparable": None}


def test_single_metric_wrappers_carry_the_disclosures(tmp_path):
    a, b = _plain_pair(tmp_path)
    for fn, key, expected in (
        (bias, "bias", 2.0),
        (rmse, "rmse", np.sqrt(14.0 / 3.0)),
        (pattern_correlation_fields, "pattern_correlation", 0.0),
    ):
        result = fn("t", a, b)
        assert result[key] == pytest.approx(expected), fn.__name__
        assert "AREA_WEIGHTING_UNAVAILABLE" in result["warning_codes"]
    with pytest.raises(ValueError, match="Unknown metric"):
        compare_fields("t", a, b, metric="mae")


def test_units_mismatch_and_synonyms(tmp_path):
    a, b = _plain_pair(tmp_path, "K", "degC")
    result = compare_fields("t", a, b)
    assert result["units"] == {"a": "K", "b": "degC", "comparable": False}
    assert "UNITS_MISMATCHED" in result["warning_codes"]
    a, b = _plain_pair(tmp_path, "m/s", "m s-1")
    assert compare_fields("t", a, b)["units"]["comparable"] is True
    assert normalize_units("Kelvin") == "k" and normalize_units("  ") is None


def test_shape_mismatch_is_refused(tmp_path):
    a, b = tmp_path / "sa.nc", tmp_path / "sb.nc"
    xr.Dataset({"t": (["n_face"], np.zeros(3))}).to_netcdf(a)
    xr.Dataset({"t": (["n_face"], np.zeros(4))}).to_netcdf(b)
    with pytest.raises(ValueError, match="same-shape"):
        compare_fields("t", str(a), str(b))
