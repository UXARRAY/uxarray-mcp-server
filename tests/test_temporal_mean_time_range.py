"""``temporal_mean`` must be able to average a sub-range, not just the file.

Without a range the mean covers every step present. That is silently wrong
whenever the input spans more than the period of interest -- most sharply for
an ARCO (kerchunk/zarr) reference, which aggregates a whole output stream, so
asking for a decade would quietly average several.

The failure mode is the dangerous kind: a plausible number, no error.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from uxarray_mcp.tools.advanced import calculate_temporal_mean
from uxarray_mcp.tools.frontdoor import run_analysis


@pytest.fixture
def two_decade_series(tmp_path):
    """Monthly data over 1980-1999 whose value encodes its own year.

    Each step is set to its year, so the mean over a selected range is the
    midpoint of that range's years. That makes a wrong selection produce a
    wrong *number* we can assert on, rather than only a wrong step count.
    """
    time = pd.date_range("1980-01-01", "1999-12-01", freq="MS")
    years = np.asarray([t.year for t in time], dtype="float64")
    path = tmp_path / "two_decades.nc"
    xr.Dataset(
        {"PRECT": (("time", "ncol"), np.repeat(years[:, None], 3, axis=1))},
        coords={"time": time, "ncol": [0, 1, 2]},
    ).to_netcdf(path)
    return str(path)


class TestTheDefaultStillAveragesEverything:
    def test_omitting_the_range_covers_the_whole_file(self, two_decade_series):
        result = calculate_temporal_mean(
            data_path=two_decade_series, variable_name="PRECT"
        )
        # 1980..1999 inclusive, 12 steps each -> mean year 1989.5
        assert result["summary"]["mean"] == pytest.approx(1989.5)


class TestARangeRestrictsTheAverage:
    def test_a_closed_range_selects_only_those_years(self, two_decade_series):
        result = calculate_temporal_mean(
            data_path=two_decade_series,
            variable_name="PRECT",
            time_min="1980-01",
            time_max="1989-12",
        )
        assert result["summary"]["mean"] == pytest.approx(1984.5)

    def test_the_bounds_are_inclusive(self, two_decade_series):
        """A label slice is closed at both ends, unlike positional slicing.

        Worth pinning: an exclusive upper bound would drop December of the
        final year, which is exactly the kind of off-by-one that survives
        review because the answer still looks reasonable.
        """
        result = calculate_temporal_mean(
            data_path=two_decade_series,
            variable_name="PRECT",
            time_min="1990-01",
            time_max="1990-12",
        )
        assert result["summary"]["mean"] == pytest.approx(1990.0)

    def test_only_a_lower_bound_is_allowed(self, two_decade_series):
        result = calculate_temporal_mean(
            data_path=two_decade_series, variable_name="PRECT", time_min="1990-01"
        )
        assert result["summary"]["mean"] == pytest.approx(1994.5)

    def test_only_an_upper_bound_is_allowed(self, two_decade_series):
        result = calculate_temporal_mean(
            data_path=two_decade_series, variable_name="PRECT", time_max="1989-12"
        )
        assert result["summary"]["mean"] == pytest.approx(1984.5)


class TestAnEmptySelectionIsAnError:
    def test_a_range_outside_the_file_raises(self, two_decade_series):
        with pytest.raises(ValueError, match="No time steps fall in"):
            calculate_temporal_mean(
                data_path=two_decade_series,
                variable_name="PRECT",
                time_min="2050-01",
                time_max="2059-12",
            )

    def test_the_error_names_the_coverage_the_file_actually_has(
        self, two_decade_series
    ):
        """"No data" alone leaves the caller guessing whether the range or the
        file is wrong. The message must show what is there.
        """
        with pytest.raises(ValueError) as excinfo:
            calculate_temporal_mean(
                data_path=two_decade_series,
                variable_name="PRECT",
                time_min="2050-01",
                time_max="2059-12",
            )
        assert "1980" in str(excinfo.value)
        assert "1999" in str(excinfo.value)


class TestTheRangeReachesThroughTheFrontDoor:
    def test_run_analysis_forwards_both_bounds(self, two_decade_series):
        """A parameter accepted by the front door and dropped before the
        implementation is worse than one that does not exist: the caller gets
        a whole-file mean while believing they asked for a decade.
        """
        result = run_analysis(
            operation="temporal_mean",
            data_path=two_decade_series,
            variable_name="PRECT",
            time_min="1980-01",
            time_max="1989-12",
        )
        assert result["summary"]["mean"] == pytest.approx(1984.5)

    def test_the_bounds_are_recorded_in_provenance(self, two_decade_series):
        """A methods section is written from provenance, so the range that
        produced the number has to be in it.
        """
        result = calculate_temporal_mean(
            data_path=two_decade_series,
            variable_name="PRECT",
            time_min="1980-01",
            time_max="1989-12",
        )
        inputs = result["_provenance"]["inputs"]
        assert inputs["time_min"] == "1980-01"
        assert inputs["time_max"] == "1989-12"
