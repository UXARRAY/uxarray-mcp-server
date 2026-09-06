"""How much time a temporal mean or a temporal anomaly actually averaged over.

``calculate_temporal_mean`` and ``calculate_anomaly`` both reduce along
``time`` and both return an array shaped like an answer no matter what went
in. Measured on a 6-face, 12-step file: a variable that is NaN at every step
returns ``outcome: complete``, ``status: complete``, no warning codes, and a
full-length field of NaN. A one-step file returns a "temporal mean" that is
the single value, and a "temporal anomaly" that is exactly zero at every
face -- zero by construction, not zero because the field sat on its baseline,
and there is nothing in the result that distinguishes the two.

Between those extremes the sample count itself is a claim. ``mean(dim="time")``
skips missing values, so a face with one usable step and a face with all twelve
both come back as a plain number, and the summary that follows mixes them. On
the probe file with one face holding a single step and another holding two, the
result reported a finite min/max/mean over faces averaged across 1, 2 and 12
samples.

So this module reports three separate things: how many steps the source had,
how many of them each element could actually use, and -- when the caller
grouped -- how many steps landed in each bin. A ``groupby="month"`` over three
months is a twelve-bin climatology in name and three single-sample bins in
fact.

Elements that hold no data at all are counted but kept out of the sample-count
range. A land-masked field has faces that never carried a value, and folding
their zero into the minimum would make every masked field look ragged.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def compute_temporal_coverage(
    source: Any,
    result: Any,
    *,
    groupby: str | None = None,
) -> dict[str, Any]:
    """Measure what the reduction along ``time`` had to work with.

    ``source`` is the variable as it was read, still carrying its time
    dimension; ``result`` is what the reduction returned. Anything that cannot
    be read is reported as ``None`` rather than guessed, since an unknown
    sample count must not be presented as a full one.
    """
    coverage: dict[str, Any] = {
        "n_time": None,
        "samples_min": None,
        "samples_max": None,
        "n_elements": 0,
        "n_elements_with_value": 0,
        "n_series": None,
        "n_series_with_data": None,
        "groupby": groupby,
    }

    result_values = _as_float(result)
    if result_values is not None:
        coverage["n_elements"] = int(result_values.size)
        coverage["n_elements_with_value"] = int(np.isfinite(result_values).sum())

    source_values = _as_float(source)
    axis = _time_axis(source)
    if source_values is not None and axis is not None:
        coverage["n_time"] = int(source_values.shape[axis])
        # One series per element of the non-time dimensions. Deliberately not
        # counted against ``n_elements``: a grouped result has one entry per
        # bin per element, so the two populations are different sizes and
        # comparing them would read as a loss that did not happen.
        per_series = np.isfinite(source_values).sum(axis=axis)
        with_data = per_series > 0
        coverage["n_series"] = int(per_series.size)
        coverage["n_series_with_data"] = int(with_data.sum())
        coverage["samples_max"] = int(per_series.max()) if per_series.size else None
        # Elements that never carried data are deliberately excluded: their
        # zero is ordinary masking, not an uneven average.
        coverage["samples_min"] = (
            int(per_series[with_data].min()) if bool(with_data.any()) else None
        )

    if groupby is not None:
        occupancy = _bin_occupancy(source, groupby)
        if occupancy is not None:
            coverage["n_bins"] = len(occupancy)
            coverage["bin_occupancy_min"] = min(occupancy) if occupancy else None
            coverage["bin_occupancy_max"] = max(occupancy) if occupancy else None

    return coverage


def temporal_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """Codes for a temporal reduction, worst first."""
    if not coverage.get("n_elements", 0):
        return []
    if not coverage.get("n_elements_with_value", 0):
        return ["TEMPORAL_COVERAGE_ZERO"]

    codes: list[str] = []
    n_time = coverage.get("n_time")
    if n_time == 1:
        codes.append("TEMPORAL_SINGLE_SAMPLE")

    samples_min = coverage.get("samples_min")
    samples_max = coverage.get("samples_max")
    if (
        samples_min is not None
        and samples_max is not None
        and samples_min != samples_max
    ):
        codes.append("TEMPORAL_SAMPLES_RAGGED")

    # A single-step file already reported TEMPORAL_SINGLE_SAMPLE, and every bin
    # it produced holds that one step; saying so twice would add nothing.
    if coverage.get("bin_occupancy_min") == 1 and n_time != 1:
        codes.append("TEMPORAL_BINS_SINGLE_SAMPLE")
    return codes


def _as_float(data: Any) -> np.ndarray | None:
    """The values as float, or None when they cannot be read as numbers."""
    if data is None:
        return None
    try:
        return np.asarray(getattr(data, "values", data), dtype=float)
    except (AttributeError, TypeError, ValueError):
        return None


def _time_axis(data: Any) -> int | None:
    """Position of the time dimension, or None when there is not one."""
    dims = getattr(data, "dims", None)
    if dims is None:
        return None
    try:
        return list(dims).index("time")
    except ValueError:
        return None


def _bin_occupancy(source: Any, groupby: str) -> list[int] | None:
    """How many time steps landed in each group, or None if ungroupable.

    Counted from the time coordinate rather than from the grouped result,
    which is per-element and would report the usable-sample count instead of
    the bin size. The two differ exactly where data is missing, and both are
    worth having separately.
    """
    try:
        counts = source["time"].groupby(f"time.{groupby}").count()
        return [int(value) for value in np.asarray(counts.values).ravel()]
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
