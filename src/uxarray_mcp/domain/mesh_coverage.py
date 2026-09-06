"""How much of the sphere a mesh covers, and what shape it is.

``calculate_area`` returns a regional patch's total the same way it returns
a global one. Measured on a 5-degree mesh spanning 0-40E/0-40N with
``sphere_radius=6371000.0``: ``total_area`` 22936016715559.137 m^2, which is
4.4967% of ``4*pi*R^2``, delivered with ``physically_interpretable: True``,
no warning codes, and ``postconditions: not_evaluated`` that never says why.
The same call on a global mesh returns 1.0000 of the sphere. Nothing in the
payload separated them.

Two independent measurements are reported because they answer different
questions and can honestly disagree:

``sphere_fraction``
    ``sum(face_areas) / (4*pi)`` on the unit sphere. Geometric: how much
    surface is actually covered. Reported instead of the raw steradian sum
    rather than alongside it -- the two differ by a mathematical constant,
    and this block rides on every area and inspection result under a byte
    budget (#83).
``closed`` / ``euler_characteristic``
    Topological: whether every edge is shared by exactly two faces, and
    ``V - E + F``.

A 1-degree structured global grid shows why both are needed. It reads
``sphere_fraction`` 0.999962 and ``closed`` False, ``euler_characteristic``
0 -- ``Grid.from_structured`` stops its nodes at +/-89.5 there rather than
extending to the poles, so the mesh has two small polar holes. It covers
essentially the whole sphere and is genuinely open, and a single verdict
would have had to suppress one of those facts. The 2-degree grid of the
same family does reach the poles: 1.000000 and closed, ``euler`` 2. The
regional patch is a disk: ``euler`` 1.

Cost is why the topology half is size-guarded. Counting edge incidences is
a Python loop over every face; on a 196,608-face HEALPix mesh it takes
1.43 s on top of 0.76 s for ``n_edge``, and the next zoom level -- 786,432
faces -- costs 9.7 s for the pair. ``face_areas`` is vectorized and stays
under 0.05 s across all of these, so the geometric half is always
computed and the topological half abstains above the threshold, saying so
rather than reporting ``closed: false`` for a mesh nobody looked at.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

#: How far ``sphere_fraction`` may sit from 1.0 and still count as global.
#:
#: Quadrature error is three orders of magnitude smaller than this -- a
#: 162-face global mesh integrates to 1.000002 -- so the slack is not for
#: numerical noise. It is for meshes that are global in every sense a
#: caller cares about but leave a pinhole somewhere: the 1-degree grid
#: above misses 3.8e-5 of the sphere at its poles. A mesh missing more
#: than 0.1% is missing something a caller would want named.
GLOBAL_COVERAGE_TOLERANCE = 1e-3

#: Face count above which the topology checks abstain rather than run.
#:
#: Set just above HEALPix zoom 7 (196,608 faces, 2.2 s for the pair) and
#: below zoom 8 (786,432 faces, 9.7 s). An inspection call that takes ten
#: seconds to report a boolean is not worth the boolean.
TOPOLOGY_MAX_FACES = 250_000

#: Decimal places used when matching node coordinates. Six is ~0.1 m on
#: Earth's surface, far below any mesh spacing we deal with, and coarse
#: enough to absorb the round-trip through NetCDF float64 text.
_COORD_DECIMALS = 6

#: Decimal places the reported numbers are rounded to. Full float64 repr
#: costs ~20 characters each on a block that is re-sent every turn, and
#: buys nothing a caller can use: 1e-6 of the sphere is 510 km^2, and 1e-6
#: degree is ~0.1 m.
_REPORT_DECIMALS = 6


def _canonical_node_ids(grid: Any) -> list[int]:
    """Map nodes onto identity by position, not by index.

    A structured global grid stores the 0/360 seam twice and every pole
    once per meridian, so counting edges on raw indices reports boundary
    edges on a mesh that is geometrically closed. Merging nodes that sit
    at the same point -- with all pole nodes collapsing to one, since
    longitude is meaningless there -- makes the count reflect the surface
    rather than the storage layout.
    """
    lon = np.asarray(grid.node_lon, dtype=float) % 360.0
    lat = np.asarray(grid.node_lat, dtype=float)
    seen: dict[str, int] = {}
    ids: list[int] = []
    for x, y in zip(lon, lat):
        if abs(abs(y) - 90.0) < 1e-9:
            key = f"pole{y:+.1f}"
        else:
            key = (
                f"{round(x, _COORD_DECIMALS) % 360:.6f}_{round(y, _COORD_DECIMALS):.6f}"
            )
        ids.append(seen.setdefault(key, len(seen)))
    return ids


def mesh_is_closed(grid: Any) -> bool:
    """True when every edge is shared by exactly two faces.

    A closed mesh is the precondition for the ``4*pi*R^2`` identity. The
    cheap version of this test -- comparing ``n_edge`` against Euler's
    formula -- is wrong on meshes with holes, so count edge incidences
    directly.
    """
    try:
        connectivity = np.asarray(grid.face_node_connectivity)
        node_ids = _canonical_node_ids(grid)
    except Exception:  # pragma: no cover - mocked grids in unit tests
        return False

    n_node = len(node_ids)
    incidence: dict[tuple[int, int], int] = {}
    for face in connectivity:
        nodes: list[int] = []
        for raw in face:
            index = int(raw)
            if not 0 <= index < n_node:
                continue  # fill value: a face with fewer nodes than the max
            node = node_ids[index]
            if not nodes or nodes[-1] != node:
                nodes.append(node)
        # A ring stored with a repeated first/last node is one edge, not two.
        if len(nodes) > 1 and nodes[0] == nodes[-1]:
            nodes.pop()
        if len(nodes) < 3:
            continue  # degenerate after merging coincident nodes
        for index, node in enumerate(nodes):
            other = nodes[(index + 1) % len(nodes)]
            key = (min(node, other), max(node, other))
            incidence[key] = incidence.get(key, 0) + 1
    if not incidence:
        return False
    return all(count == 2 for count in incidence.values())


def compute_mesh_coverage(
    grid: Any,
    *,
    steradians: float | None = None,
) -> dict[str, Any]:
    """Measure how much of the sphere ``grid`` covers and what shape it is.

    Parameters
    ----------
    grid : ux.Grid
        Loaded UXarray grid.
    steradians : float | None
        ``sum(face_areas)`` on the unit sphere, when the caller has already
        computed it. Passed in from ``compute_area_stats`` so the sum is not
        paid for twice; recomputed here when absent. Not itself reported --
        it becomes ``sphere_fraction``.

    Returns
    -------
    dict
        ``sphere_fraction`` (geometric), ``closed`` and
        ``euler_characteristic`` (topological, ``None`` when skipped),
        ``lon_extent`` and ``lat_extent``. ``topology_skipped`` appears only
        when the mesh was too large to check, carrying the reason, so a
        ``None`` verdict is never mistaken for a negative one.

        ``lon_extent`` describes the mesh in the grid's own longitude
        convention and is not a globality test: a global mesh stored on
        [-180, 180] with 20-degree cells reads [-170, 170]. Use
        ``sphere_fraction`` for that.
    """
    coverage: dict[str, Any] = {
        "sphere_fraction": None,
        "closed": None,
        "euler_characteristic": None,
        "lon_extent": None,
        "lat_extent": None,
    }

    if steradians is None:
        try:
            steradians = float(np.asarray(grid.face_areas).sum())
        except Exception:  # pragma: no cover - mocked grids in unit tests
            steradians = None
    if steradians is not None and math.isfinite(steradians):
        coverage["sphere_fraction"] = round(
            float(steradians) / (4.0 * math.pi), _REPORT_DECIMALS
        )

    try:
        lon = np.asarray(grid.node_lon, dtype=float)
        lat = np.asarray(grid.node_lat, dtype=float)
        if lon.size and lat.size:
            coverage["lon_extent"] = [
                round(float(lon.min()), _REPORT_DECIMALS),
                round(float(lon.max()), _REPORT_DECIMALS),
            ]
            coverage["lat_extent"] = [
                round(float(lat.min()), _REPORT_DECIMALS),
                round(float(lat.max()), _REPORT_DECIMALS),
            ]
    except Exception:  # pragma: no cover - mocked grids in unit tests
        pass

    try:
        n_face = int(grid.n_face)
    except Exception:  # pragma: no cover - mocked grids in unit tests
        return coverage

    if n_face > TOPOLOGY_MAX_FACES:
        coverage["topology_skipped"] = (
            f"{n_face} faces exceeds the {TOPOLOGY_MAX_FACES}-face limit for "
            "counting edge incidences; closure was not checked."
        )
        return coverage

    try:
        coverage["euler_characteristic"] = int(grid.n_node) - int(grid.n_edge) + n_face
    except Exception:  # pragma: no cover - mocked grids in unit tests
        pass
    coverage["closed"] = mesh_is_closed(grid)
    return coverage


def mesh_coverage_warning_codes(coverage: dict[str, Any]) -> list[str]:
    """Stable codes for a mesh that is not the whole sphere.

    Silent on a skipped topology check: not knowing whether a mesh is
    closed is not evidence that it is open, and ``topology_skipped`` in
    the block already says nobody looked.
    """
    fraction = coverage.get("sphere_fraction")
    if fraction is None:
        return []
    if fraction < 1.0 - GLOBAL_COVERAGE_TOLERANCE:
        return ["MESH_NOT_GLOBAL"]
    if fraction > 1.0 + GLOBAL_COVERAGE_TOLERANCE:
        # More surface than a sphere has means faces overlap or are stored
        # twice. Quadrature cannot produce this at 1e-3.
        return ["MESH_COVERAGE_EXCEEDS_SPHERE"]
    return []
