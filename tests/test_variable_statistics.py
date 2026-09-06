"""A variable's statistics must say what they were taken over.

Measured before the change, on a 162-face global grid (20-degree cells,
lat -80 to 80) carrying three float fields:

    sst          {'min': 0.0,   'max': 161.0, 'mean': 80.5}
    sst_masked   {'min': 145.0, 'max': 161.0, 'mean': 153.0}
    sst_allnan   {'min': nan,   'max': nan,   'mean': nan}

``sst_masked`` holds a value on 17 of 162 faces. 153.0 is the true mean of
those seventeen, and the payload said nothing to distinguish it from the
mean of the field -- which is 80.5, forty percent lower. Land masks are
ordinary in this data, so this was most fields.

``sst_allnan`` was worse in two ways: three ``RuntimeWarning``s went to
stderr (``All-NaN slice encountered`` twice, ``Mean of empty slice`` once),
and ``nan`` is not a JSON number, so a strict decoder loses the response
rather than the field.

``state.summarize_array`` already had this right; the contract here is
copied from it deliberately, so the two cannot drift.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import xarray as xr

from uxarray_mcp.domain.variable import compute_variable_info

ux = pytest.importorskip("uxarray")


@pytest.fixture(scope="module")
def masked_dataset():
    """A global mesh with a whole field, a mostly-absent one, and an empty one."""
    grid = ux.Grid.from_structured(
        lon=np.arange(0, 360, 20.0), lat=np.arange(-80, 81, 20.0)
    )
    n = int(grid.n_face)
    whole = np.arange(n, dtype=float)
    masked = whole.copy()
    masked[: n - 17] = np.nan
    return ux.UxDataset(
        xr.Dataset(
            {
                "sst": (("n_face",), whole),
                "sst_masked": (("n_face",), masked),
                "sst_allnan": (("n_face",), np.full(n, np.nan)),
                "flags": (("n_face",), np.arange(n, dtype="int32")),
            }
        ),
        uxgrid=grid,
    )


def _stats(dataset, name):
    info = compute_variable_info(dataset, name)
    return info["variables"][0]["statistics"]


class TestStatisticsSayWhatTheyCovered:
    def test_a_masked_field_reports_how_much_of_it_was_there(self, masked_dataset):
        stats = _stats(masked_dataset, "sst_masked")
        assert stats["n_finite"] == 17
        assert stats["n_total"] == 162
        # The value itself is unchanged and still correct: 153.0 is the mean
        # of the seventeen faces that hold one. Only the silence was wrong.
        assert stats["mean"] == pytest.approx(153.0)

    def test_the_masked_mean_differs_from_the_whole_field_mean(self, masked_dataset):
        whole = _stats(masked_dataset, "sst")
        masked = _stats(masked_dataset, "sst_masked")
        assert whole["mean"] == pytest.approx(80.5)
        assert masked["mean"] == pytest.approx(153.0)
        # Nearly double. A caller who reads one as the other is wrong about
        # the field by more than any rounding this server does.
        assert masked["mean"] > whole["mean"] * 1.5

    def test_a_whole_field_is_not_charged_for_the_two_extra_keys(self, masked_dataset):
        stats = _stats(masked_dataset, "sst")
        assert "n_finite" not in stats
        assert "n_total" not in stats

    def test_an_integer_field_is_not_charged_either(self, masked_dataset):
        stats = _stats(masked_dataset, "flags")
        assert "n_finite" not in stats
        assert stats["min"] == 0.0
        assert stats["max"] == 161.0


class TestAnAbsentFieldReportsAbsence:
    def test_nothing_finite_reports_null_rather_than_nan(self, masked_dataset):
        stats = _stats(masked_dataset, "sst_allnan")
        assert stats["min"] is None
        assert stats["max"] is None
        assert stats["mean"] is None
        assert stats["n_finite"] == 0
        assert stats["n_total"] == 162

    def test_the_result_survives_a_strict_json_encoder(self, masked_dataset):
        import json

        info = compute_variable_info(masked_dataset)
        # allow_nan=False is what a decoder in any other language enforces.
        # Before the change this raised: Out of range float values are not
        # JSON compliant: nan.
        json.dumps(
            [v["statistics"] for v in info["variables"]],
            allow_nan=False,
        )

    def test_an_empty_field_emits_no_runtime_warning(self, masked_dataset):
        # Recorded rather than raised. ``simplefilter("error")`` turns the
        # warning into an exception that ``compute_variable_info``'s own
        # ``except Exception`` swallows into ``statistics: None``, so the
        # test would pass against the old code for the wrong reason.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            stats = _stats(masked_dataset, "sst_allnan")
        runtime = [w for w in caught if issubclass(w.category, RuntimeWarning)]
        assert runtime == [], [str(w.message) for w in runtime]
        assert stats is not None


class TestTheStatisticsStayOptional:
    def test_a_non_numeric_field_still_reports_none(self):
        grid = ux.Grid.from_structured(
            lon=np.arange(0, 360, 40.0), lat=np.arange(-60, 61, 40.0)
        )
        n = int(grid.n_face)
        dataset = ux.UxDataset(
            xr.Dataset({"label": (("n_face",), np.array(["x"] * n))}),
            uxgrid=grid,
        )
        assert _stats(dataset, "label") is None
