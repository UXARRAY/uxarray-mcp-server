"""How much of an anomaly field the band means actually defined.

``zonal_anomaly`` subtracts, from each face, the zonal mean of the latitude
band that face falls in.  That makes it a per-face field rather than a binned
profile, so :mod:`~uxarray_mcp.domain.profile_coverage` does not apply: there
are no bins in the answer to count.  The loss happens one level down, and it is
invisible in the result's shape.

A band mean is undefined when the band holds no usable data, and every face in
that band then comes back NaN -- *including faces that carried a perfectly good
value*.  Measured on a 90-face regional mesh with 30 faces carrying data, only
18 faces received an anomaly: 12 faces had data and lost it to a band mean that
did not exist.  The returned array is still 90 long, ``min``/``max``/``mean``/
``std`` are still finite, and nothing in the result says two thirds of the field
is missing or that some of the missing part was measurable.

Two kinds of missing face are therefore counted separately.  A face that never
had data has no anomaly for an ordinary reason -- a masked ocean field would
otherwise warn on every call -- and is not worth a warning.  A face that had
data and still has no anomaly is a real loss, and it is a *deduction* rather
than a guess: the anomaly is ``value - band_mean``, so a finite value with a
non-finite anomaly means the band mean was non-finite.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def compute_anomaly_coverage(
    values: Sequence[float],
    *,
    source: Any = None,
) -> dict[str, Any]:
    """Report how many faces received an anomaly, and how many lost one.

    Parameters
    ----------
    values
        The anomaly field as returned by the operation, one entry per face.
    source
        The field the anomaly was taken from, if available. Used to separate
        a face that never had data from a face whose band mean was undefined.

    Returns
    -------
    dict
        ``n_face``, ``n_face_with_data`` (``None`` when the source was not
        supplied), ``n_face_with_anomaly``, ``n_face_data_lost`` and ``cause``.
        ``cause`` is ``"band_mean_undefined"`` only when faces that carried
        data came back without an anomaly, ``"missing_input"`` when every
        absent anomaly is explained by absent data, and ``"ambiguous"`` when
        the source was not supplied or does not line up with the result.
    """
    anomaly = np.asarray(values, dtype=float)
    anomaly_finite = np.isfinite(anomaly)
    n_face = int(anomaly.size)
    n_with_anomaly = int(anomaly_finite.sum())

    n_with_data: int | None = None
    n_lost: int | None = None
    comparable = False
    if source is not None:
        source_values = np.asarray(getattr(source, "values", source), dtype=float)
        if source_values.shape == anomaly.shape:
            source_finite = np.isfinite(source_values)
            n_with_data = int(source_finite.sum())
            n_lost = int((source_finite & ~anomaly_finite).sum())
            # An anomaly where the source had nothing is not a shape this
            # module models -- `value - band_mean` cannot be finite when
            # `value` is not -- so rather than reason from it, say so.
            comparable = not bool((~source_finite & anomaly_finite).any())

    if n_with_data is None:
        # Nobody supplied the field, so a missing anomaly has two possible
        # explanations and this does not pick one.
        cause = "none" if n_with_anomaly == n_face else "ambiguous"
    elif not comparable:
        cause = "ambiguous"
    elif n_lost:
        cause = "band_mean_undefined"
    elif n_with_anomaly == n_face:
        cause = "none"
    else:
        cause = "missing_input"

    return {
        "n_face": n_face,
        "n_face_with_data": n_with_data,
        "n_face_with_anomaly": n_with_anomaly,
        "n_face_data_lost": n_lost,
        "cause": cause,
    }


def anomaly_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """Stable codes for an anomaly field that is empty or lost measured data."""
    if not coverage.get("n_face", 0):
        return []
    if not coverage.get("n_face_with_anomaly", 0):
        return ["ANOMALY_COVERAGE_ZERO"]
    # Deliberately not `n_face_with_anomaly < n_face`. Faces that never held
    # data have no anomaly for an ordinary reason, and warning about them
    # would fire on every masked field and teach callers to ignore the code.
    if coverage.get("n_face_data_lost"):
        return ["ANOMALY_COVERAGE_PARTIAL"]
    return []
