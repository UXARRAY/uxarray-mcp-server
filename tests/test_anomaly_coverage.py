"""An anomaly field emptied by undefined band means must not look answered.

Before this gate, a 90-face mesh whose variable held one missing value per
latitude band returned `outcome: complete`, `status: complete`, no warning
codes, and `stats` of `{min: None, max: None, mean: None, std: None}` -- 85
faces carried data, every band mean was undefined, and nothing said so. The
partial case was quieter still: 30 faces with data, 18 anomalies returned, 12
measurable faces silently dropped, and finite min/max/mean/std computed from
the survivors.

Two kinds of empty face are separated here. A face that never had data has no
anomaly for an ordinary reason -- masked ocean fields would otherwise warn on
every call -- and the tests below pin that down so the warning stays worth
reading.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.domain.anomaly_coverage import (
    anomaly_coverage_warning_codes,
    compute_anomaly_coverage,
)
from uxarray_mcp.preconditions import OVERRIDE_TOKEN
from uxarray_mcp.tools.frontdoor import run_analysis

NAN = float("nan")

#: Faces per latitude band on the fixture mesh below: 18 longitudes wide.
FACES_PER_BAND = 18


@pytest.fixture
def regional_grid(tmp_path):
    """A mesh spanning 0-40N in five 18-face latitude rows."""
    lon = np.arange(0.0, 360.0, 20.0)
    lat = np.arange(0.0, 41.0, 10.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "regional.nc"
    grid.to_xarray().to_netcdf(grid_file)
    return grid_file, grid.n_face


def _write(tmp_path, name, values):
    path = tmp_path / f"{name}.nc"
    xr.Dataset({"t": (["n_face"], values, {"units": "K"})}).to_netcdf(path)
    return path


def _analyze(grid_file, data_file, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_analysis(
            operation="zonal_anomaly",
            grid_path=str(grid_file),
            data_path=str(data_file),
            variable_name="t",
            **kwargs,
        )


def _field(n_face, seed=3):
    rng = np.random.default_rng(seed)
    return 250.0 + 30.0 * rng.random(n_face)


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


def test_a_complete_field_reports_full_coverage():
    coverage = compute_anomaly_coverage([1.0, -1.0, 2.0], source=[10.0, 8.0, 11.0])
    assert coverage == {
        "n_face": 3,
        "n_face_with_data": 3,
        "n_face_with_anomaly": 3,
        "n_face_data_lost": 0,
        "cause": "none",
    }


def test_a_face_that_never_had_data_is_not_counted_as_lost():
    coverage = compute_anomaly_coverage([1.0, NAN], source=[10.0, NAN])
    assert coverage["n_face_with_data"] == 1
    assert coverage["n_face_data_lost"] == 0
    assert coverage["cause"] == "missing_input"


def test_a_face_that_had_data_and_lost_its_anomaly_is_counted():
    coverage = compute_anomaly_coverage([1.0, NAN], source=[10.0, 8.0])
    assert coverage["n_face_data_lost"] == 1
    assert coverage["cause"] == "band_mean_undefined"


def test_coverage_without_a_source_does_not_guess():
    coverage = compute_anomaly_coverage([1.0, NAN])
    assert coverage["n_face_with_data"] is None
    assert coverage["n_face_data_lost"] is None
    assert coverage["cause"] == "ambiguous"


def test_a_source_of_a_different_shape_is_not_compared():
    coverage = compute_anomaly_coverage([1.0, NAN], source=[10.0, 8.0, 6.0])
    assert coverage["n_face_with_data"] is None
    assert coverage["cause"] == "ambiguous"


def test_an_anomaly_where_the_source_had_nothing_is_not_reasoned_from():
    # `value - band_mean` cannot be finite when `value` is not, so this is a
    # shape the module does not model and must not explain away.
    coverage = compute_anomaly_coverage([1.0, 2.0], source=[10.0, NAN])
    assert coverage["cause"] == "ambiguous"
    assert coverage["n_face_with_data"] == 1


# ---------------------------------------------------------------------------
# The codes
# ---------------------------------------------------------------------------


def test_full_coverage_warns_about_nothing():
    assert (
        anomaly_coverage_warning_codes(compute_anomaly_coverage([1.0], source=[2.0]))
        == []
    )


def test_an_empty_field_is_zero_coverage():
    codes = anomaly_coverage_warning_codes(
        compute_anomaly_coverage([NAN, NAN], source=[1.0, 2.0])
    )
    assert codes == ["ANOMALY_COVERAGE_ZERO"]


def test_lost_data_is_partial_coverage():
    codes = anomaly_coverage_warning_codes(
        compute_anomaly_coverage([1.0, NAN], source=[10.0, 8.0])
    )
    assert codes == ["ANOMALY_COVERAGE_PARTIAL"]


def test_a_masked_field_that_lost_nothing_does_not_warn():
    # The whole point of counting lost faces rather than empty ones: an
    # ordinary land-masked field must not warn on every call.
    codes = anomaly_coverage_warning_codes(
        compute_anomaly_coverage([1.0, NAN], source=[10.0, NAN])
    )
    assert codes == []


def test_an_empty_measurement_yields_no_codes():
    assert anomaly_coverage_warning_codes({"n_face": 0}) == []


# ---------------------------------------------------------------------------
# End to end through the front door
# ---------------------------------------------------------------------------


def test_a_complete_field_is_interpretable(tmp_path, regional_grid):
    grid_file, n_face = regional_grid
    data_file = _write(tmp_path, "full", _field(n_face))
    result = _analyze(grid_file, data_file)

    assert result["outcome"] == "complete"
    assert result["anomaly_coverage"]["n_face_data_lost"] == 0
    assert result["scientific_status"]["physically_interpretable"] is True
    assert result["scientific_status"]["warning_codes"] == []


def test_faces_that_lose_their_anomaly_are_reported(tmp_path, regional_grid):
    """The measured case: data present, most of it dropped, stats still finite."""
    grid_file, n_face = regional_grid
    values = _field(n_face)
    values[:60] = NAN
    data_file = _write(tmp_path, "partial", values)
    result = _analyze(grid_file, data_file)

    coverage = result["anomaly_coverage"]
    assert coverage["n_face_with_data"] == 30
    assert coverage["n_face_with_anomaly"] == 18
    assert coverage["n_face_data_lost"] == 12
    assert coverage["cause"] == "band_mean_undefined"
    # The number still comes back -- this is a warning, not a refusal -- but
    # it no longer comes back claiming to describe the whole field.
    assert result["outcome"] == "complete"
    assert result["stats"]["mean"] is not None
    assert result["scientific_status"]["physically_interpretable"] is False
    assert "ANOMALY_COVERAGE_PARTIAL" in result["scientific_status"]["warning_codes"]


def test_one_gap_per_band_refuses_rather_than_returning_nulls(tmp_path, regional_grid):
    """85 of 90 faces carry data and every band mean is still undefined."""
    grid_file, n_face = regional_grid
    values = _field(n_face)
    for band in range(n_face // FACES_PER_BAND):
        values[band * FACES_PER_BAND] = NAN
    data_file = _write(tmp_path, "poisoned", values)
    result = _analyze(grid_file, data_file)

    assert result["outcome"] == "input_required"
    assert "stats" not in result
    failed = result["refusal"]["failed_checks"]
    assert [check["id"] for check in failed] == ["anomaly_coverage_nonzero"]
    assert "85 faces carried data" in failed[0]["detail"]
    # The bands are not the thing to move here, so the repair must not say so
    # first: no band can be placed to avoid a gap that is in every band.
    assert "missing" in failed[0]["repair"]


def test_an_entirely_missing_variable_is_refused_with_its_own_repair(
    tmp_path, regional_grid
):
    grid_file, n_face = regional_grid
    data_file = _write(tmp_path, "allnan", np.full(n_face, NAN))
    result = _analyze(grid_file, data_file)

    assert result["outcome"] == "input_required"
    repair = result["refusal"]["failed_checks"][0]["repair"]
    # Nothing was measurable, so pointing at lat_spec would be a wrong lead.
    assert "lat_spec" not in repair
    assert "no usable values" in repair


def test_an_ordinary_masked_field_neither_refuses_nor_warns(tmp_path, regional_grid):
    """A band left entirely empty is not a defect: it simply has no faces."""
    grid_file, n_face = regional_grid
    values = _field(n_face)
    values[:FACES_PER_BAND] = NAN
    data_file = _write(tmp_path, "masked", values)
    result = _analyze(grid_file, data_file)

    coverage = result["anomaly_coverage"]
    assert coverage["n_face_with_data"] == n_face - FACES_PER_BAND
    assert coverage["n_face_data_lost"] == 0
    assert coverage["cause"] == "missing_input"
    assert result["outcome"] == "complete"
    assert result["scientific_status"]["warning_codes"] == []


def test_the_override_returns_the_number_without_claiming_it(tmp_path, regional_grid):
    grid_file, n_face = regional_grid
    data_file = _write(tmp_path, "allnan_override", np.full(n_face, NAN))
    result = _analyze(grid_file, data_file, acknowledge=OVERRIDE_TOKEN)

    assert result["outcome"] == "complete"
    assert result["preconditions"]["status"] == "overridden"
    assert result["preconditions"]["override_used"] is True
    assert result["scientific_status"]["physically_interpretable"] is False
    # There is no number to hand back, and the override does not invent one.
    assert result["stats"] == {"min": None, "max": None, "mean": None, "std": None}
