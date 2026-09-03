"""How much of a binned profile the mesh actually filled.

``calculate_zonal_mean`` and ``azimuthal_mean`` both reduce a field onto bins
the caller chooses -- latitude bands, or rings of great-circle distance from a
centre. Nothing forces those bins to intersect the mesh. A regional mesh asked
for southern-hemisphere bands, or a radial profile centred a hundred degrees
away, returns a profile of the requested length made entirely of NaN, and a
profile of the right shape is indistinguishable from one carrying an answer
unless somebody counts.

The count here is deliberately indirect. Re-deriving which faces land in which
bin would duplicate UXarray's own binning and could disagree with it, so this
measures the profile that came back instead. An empty bin is NaN -- but so is a
bin whose faces all held missing data, and the two mean different things. The
source field is therefore checked as well: when it is entirely finite, a NaN
bin is unambiguously an empty one; when it is not, the cause is reported as
ambiguous rather than guessed at.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def compute_profile_coverage(
    values: Sequence[float],
    *,
    source: Any = None,
) -> dict[str, Any]:
    """Report how many bins of a profile carry a value.

    Parameters
    ----------
    values
        The profile as returned by the operation, one entry per bin.
    source
        The field the profile was reduced from, if available. Used only to
        decide whether an empty bin can be attributed to the bins missing the
        mesh, or whether missing data in the field could explain it too.

    Returns
    -------
    dict
        ``n_bins``, ``n_bins_filled``, ``source_has_missing`` (``None`` when
        the field was not supplied) and ``cause``, which is
        ``"bins_miss_mesh"`` only when the source is known to be complete.
        No fraction: two integers carry it, and this block rides on every
        profile result under a byte budget.
    """
    profile = np.asarray(values, dtype=float)
    n_bins = int(profile.size)
    n_filled = int(np.isfinite(profile).sum())

    source_has_missing: bool | None = None
    if source is not None:
        source_values = np.asarray(getattr(source, "values", source), dtype=float)
        source_has_missing = bool(source_values.size) and bool(
            (~np.isfinite(source_values)).any()
        )

    if n_filled == n_bins:
        cause = "none"
    elif source_has_missing is False:
        cause = "bins_miss_mesh"
    else:
        # Either the field carries missing data or nobody looked, so an empty
        # bin has two possible explanations and this does not pick one.
        cause = "ambiguous"

    return {
        "n_bins": n_bins,
        "n_bins_filled": n_filled,
        "source_has_missing": source_has_missing,
        "cause": cause,
    }


def profile_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """Stable codes for a partly or wholly unfilled profile."""
    n_bins = coverage.get("n_bins", 0)
    if not n_bins:
        return []
    filled = coverage.get("n_bins_filled", 0)
    if filled == 0:
        return ["PROFILE_COVERAGE_ZERO"]
    if filled < n_bins:
        return ["PROFILE_COVERAGE_PARTIAL"]
    return []
