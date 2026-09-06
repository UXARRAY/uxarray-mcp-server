"""Whether a selection kept any of the mesh it was applied to.

``subset_bbox``, ``subset_polygon`` and ``cross_section`` all narrow a mesh to
the part a caller named.  Keeping fewer faces than the source is the *purpose*
of the operation, so unlike the coverage measures on remap and profile results
there is no partial case to warn about -- a subset that keeps three faces of
eighty-one is doing exactly what it was asked.

Keeping none is different.  A bounding box in the wrong hemisphere returns a
grid with ``n_face: 0`` and a variable summary with ``shape: [0]``, and both
are shaped like an answer: the result carries a handle, a next-steps list, and
nothing that says the selection missed.  Measured on an 81-face regional mesh,
a box at 160-170W / 70-80S returned ``outcome: complete``, no warning codes and
a persisted empty artifact.

The extent of the source mesh is carried alongside the counts because it is
what makes the repair actionable.  "No faces selected" tells a caller their box
was wrong; the longitude and latitude the mesh actually spans tells them where
to put it, and in particular whether they have the ``-180..180`` against
``0..360`` convention backwards.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def mesh_extent(grid: Any) -> dict[str, float] | None:
    """The longitude/latitude box the mesh's face centres fall in.

    Returns ``None`` rather than a guess when the grid exposes no usable face
    coordinates: an extent nobody measured would be worse than no extent, since
    the repair text quotes it as fact.
    """
    try:
        lon = np.asarray(grid.face_lon, dtype=float)
        lat = np.asarray(grid.face_lat, dtype=float)
    except (AttributeError, TypeError, ValueError):
        return None
    if lon.size == 0 or lat.size == 0:
        return None
    finite_lon = lon[np.isfinite(lon)]
    finite_lat = lat[np.isfinite(lat)]
    if finite_lon.size == 0 or finite_lat.size == 0:
        return None
    return {
        "lon_min": float(finite_lon.min()),
        "lon_max": float(finite_lon.max()),
        "lat_min": float(finite_lat.min()),
        "lat_max": float(finite_lat.max()),
    }


def compute_subset_coverage(
    n_face_source: int,
    n_face_retained: int,
    *,
    extent: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Report how much of the source mesh a selection kept.

    Parameters
    ----------
    n_face_source
        Faces in the mesh the selection was applied to.
    n_face_retained
        Faces the selection kept.
    extent
        The source mesh's face-centre bounding box, if it could be measured.
        Carried so the refusal can name where the mesh actually is.
    """
    coverage: dict[str, Any] = {
        "n_face_source": int(n_face_source),
        "n_face_retained": int(n_face_retained),
    }
    if extent is not None:
        coverage["source_extent"] = extent
    return coverage


def subset_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """A code for a selection that kept nothing.

    There is deliberately no partial code. A subset keeps fewer faces than it
    started with by definition, so warning about that would fire on every
    successful call.
    """
    if not coverage.get("n_face_source", 0):
        return []
    if not coverage.get("n_face_retained", 0):
        return ["SUBSET_COVERAGE_ZERO"]
    return []
