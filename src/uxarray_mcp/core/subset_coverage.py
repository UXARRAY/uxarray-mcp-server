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

The three operations do not select the same way, which is why the rule is
reported rather than assumed.  ``subset_polygon`` keeps a face when its centre
falls inside the polygon.  ``cross_section`` keeps a face when the line crosses
it.  ``subset_bbox`` keeps a face only when the face's whole spherical
footprint fits inside the box, which is much stricter than a caller reading
"bounding box" expects.  Measured on an 81-face mesh of 5-degree cells centred
on multiples of 5, a box of lon 5..15 / lat 5..15 holds six face centres and
``bounding_box`` returns one.  The footprint is spherical, not the node
rectangle: the surviving face spans latitude 7.5000..12.5115, the extra 0.0115
being the great-circle edge bulging poleward of the nodes it joins.  On a mesh
whose nodes sit exactly on the requested bound, that bulge alone is enough --
a 5-degree quad mesh built on nodes at 5, 10 and 15 keeps two of the four faces
whose centres are inside, the other two reaching 15.0136 against a bound of 15.

That is correct spherical geometry, not a defect, so it carries no warning
code -- dropping boundary faces is what a bounding box does on every call, and
a code that fires every time teaches callers to ignore it.  The count of face
centres inside the box is reported instead, so the gap is visible to a caller
who cares.  It matters in one case beyond bookkeeping: a box small enough that
no face fits entirely inside returns nothing while sitting squarely on the
mesh, and telling that caller to "move the box onto the mesh" would send them
away from the fix.
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


def count_face_centers_in_bounds(
    grid: Any,
    lon_bounds: list[float],
    lat_bounds: list[float],
) -> int | None:
    """How many face centres fall inside a longitude/latitude box.

    This is the number a caller expects ``subset_bbox`` to return, so it is
    worth reporting next to the number it actually returns.  ``None`` when the
    grid exposes no usable face coordinates, for the same reason
    :func:`mesh_extent` returns ``None``: an unmeasured count would be quoted
    as fact.
    """
    try:
        lon = np.asarray(grid.face_lon, dtype=float)
        lat = np.asarray(grid.face_lat, dtype=float)
        lon_lo, lon_hi = float(lon_bounds[0]), float(lon_bounds[1])
        lat_lo, lat_hi = float(lat_bounds[0]), float(lat_bounds[1])
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    if lon.size == 0 or lat.size == 0 or lon.shape != lat.shape:
        return None
    inside = (lon >= lon_lo) & (lon <= lon_hi) & (lat >= lat_lo) & (lat <= lat_hi)
    return int(inside.sum())


def compute_subset_coverage(
    n_face_source: int,
    n_face_retained: int,
    *,
    extent: dict[str, float] | None = None,
    selection_rule: str | None = None,
    n_face_centers_in_bounds: int | None = None,
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
    selection_rule
        Which test decided each face: ``"face_bounds_within"``,
        ``"face_center_inside"`` or ``"face_intersects_line"``.  Reported
        because the three operations answer different questions and a caller
        comparing their counts has no other way to know that.
    n_face_centers_in_bounds
        Face centres inside the requested box, for ``subset_bbox`` only.  The
        gap between this and ``n_face_retained`` is the boundary faces whose
        spherical footprint did not fit.
    """
    coverage: dict[str, Any] = {
        "n_face_source": int(n_face_source),
        "n_face_retained": int(n_face_retained),
    }
    if selection_rule is not None:
        coverage["selection_rule"] = selection_rule
    if n_face_centers_in_bounds is not None:
        coverage["n_face_centers_in_bounds"] = int(n_face_centers_in_bounds)
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
