"""Array summaries describe the values that are there, in valid JSON.

``summarize_array`` used plain ``min``/``max``/``mean``, which propagate NaN,
so one missing value emptied all three statistics. Measured on a temporal mean
of a field masked over half its faces: three faces held finite means and the
summary reported ``min``, ``max`` and ``mean`` all NaN, as ``outcome:
complete``. Land masks are ordinary in this data, so that was most fields.

``json.dumps`` writes NaN as the bare token ``NaN``, which is not JSON, so the
same payloads were also unparseable by a strict client.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.state import summarize_array


def _array(values, dims=("n_face",), **kwargs) -> xr.DataArray:
    return xr.DataArray(np.asarray(values), dims=dims, **kwargs)


def _strict_json(payload) -> str:
    """Serialise, refusing the non-JSON constants ``json`` emits by default."""

    def reject(constant: str) -> None:
        raise AssertionError(f"payload carries the non-JSON constant {constant}")

    text = json.dumps(payload)
    json.loads(text, parse_constant=reject)
    return text


def test_a_complete_field_summarises_as_before():
    summary = summarize_array(_array([1.0, 2.0, 3.0]))
    assert summary["min"] == pytest.approx(1.0)
    assert summary["max"] == pytest.approx(3.0)
    assert summary["mean"] == pytest.approx(2.0)
    assert summary["shape"] == [3]
    # Nothing was skipped, so no count is added to every payload in the server.
    assert "n_finite" not in summary
    assert "n_total" not in summary


def test_a_masked_field_reports_the_values_it_has():
    summary = summarize_array(_array([1.0, np.nan, 3.0]))
    assert summary["min"] == pytest.approx(1.0)
    assert summary["max"] == pytest.approx(3.0)
    assert summary["mean"] == pytest.approx(2.0)
    assert summary["n_finite"] == 2
    assert summary["n_total"] == 3


def test_an_infinity_counts_as_missing_rather_than_as_an_extreme():
    # A max of inf is not a measurement, and letting it through would make the
    # range meaningless wherever a division by zero reached the field.
    summary = summarize_array(_array([1.0, np.inf, 3.0]))
    assert summary["max"] == pytest.approx(3.0)
    assert summary["n_finite"] == 2


def test_a_field_with_nothing_finite_reports_none_not_nan():
    summary = summarize_array(_array([np.nan, np.nan]))
    assert summary["min"] is None
    assert summary["max"] is None
    assert summary["mean"] is None
    assert summary["n_finite"] == 0
    assert summary["n_total"] == 2


def test_a_masked_summary_is_valid_json():
    _strict_json(summarize_array(_array([1.0, np.nan])))


def test_an_empty_summary_is_valid_json():
    _strict_json(summarize_array(_array([np.nan])))


def test_an_empty_array_carries_no_statistics():
    summary = summarize_array(_array(np.array([], dtype=float)))
    assert "min" not in summary
    assert summary["shape"] == [0]


def test_an_integer_field_is_summarised_without_a_finite_mask():
    # Integers carry no missing value to skip, so the counts stay off.
    summary = summarize_array(_array(np.array([1, 2, 3], dtype="int64")))
    assert summary["min"] == pytest.approx(1.0)
    assert summary["mean"] == pytest.approx(2.0)
    assert "n_finite" not in summary


def test_a_datetime_field_keeps_the_epoch_numbers_it_always_reported():
    # numpy casts datetime64 straight to nanoseconds since the epoch, so these
    # statistics were already being returned and are left alone here. Pinning
    # them keeps a later decision about what a time summary should say from
    # happening by accident inside a NaN fix.
    values = np.array(["2000-01-01", "2000-01-02"], dtype="datetime64[ns]")
    summary = summarize_array(_array(values))
    assert summary["dtype"].startswith("datetime64")
    assert summary["min"] == pytest.approx(9.466848e17)
    assert "n_finite" not in summary


def test_a_multidimensional_field_counts_every_element():
    summary = summarize_array(
        _array([[1.0, np.nan], [3.0, 4.0]], dims=("time", "n_face"))
    )
    assert summary["shape"] == [2, 2]
    assert summary["n_finite"] == 3
    assert summary["n_total"] == 4
    assert summary["mean"] == pytest.approx(8.0 / 3.0)
