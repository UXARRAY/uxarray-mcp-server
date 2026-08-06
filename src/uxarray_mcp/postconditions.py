"""Server-side postcondition checks for analysis results (#84, #90).

A precondition asks whether an operation *should* run. A postcondition
asks whether the number it produced is consistent with something already
known. The eScience study measured what the second one is worth: on a
task where every interface computed the identical total area, adding a
block stating reference, residual, tolerance, and verdict took correct
answers from 11/20 to 20/20, and every deployment reached 5/5.

Two design constraints come straight out of that result.

**Keep it small.** The block that worked was 257 bytes. #83 exists
because the server already sends too much, so a postcondition block that
grows into a report undoes its own benefit. Budget below, enforced in
``tests/test_payload_budget.py``.

**Do not always hand over the verdict.** #90's objection is that a block
supplying ``verification_passed`` lets a caller echo a verdict it never
computed, and that a caller which never computes a residual cannot
notice when the server's own check is wrong or inapplicable. So the
verdict is a policy, not a fixed shape:

``full``
    reference, residual, tolerance, and verdict. The measured-win shape,
    and the default, because it is what removes the arithmetic errors.
``reference_only``
    reference and tolerance, no residual and no verdict. The caller must
    do the comparison and say so. A deployment that wants to know
    whether its callers actually verify sets this.
``off``
    no checks evaluated at all; the block reports ``not_evaluated``.

The three ``status`` values stay legible and distinct, per #84 and #90:
``not_evaluated`` (we did not check), ``checked`` (we checked, here is
the verdict), ``reference_supplied`` (we gave you what you need, you
check).
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable, Literal

#: Verdict policies, in order of decreasing generosity to the caller.
VerdictPolicy = Literal["full", "reference_only", "off"]

VERDICT_POLICIES: tuple[str, ...] = ("full", "reference_only", "off")

#: Deployment-wide default, overridable per request via ``verdict_policy``.
#: Named after the study condition it reproduces.
DEFAULT_VERDICT_POLICY: VerdictPolicy = "full"

#: Environment override so an operator can enforce ``reference_only``
#: server-wide without touching call sites.
VERDICT_POLICY_ENV = "UXARRAY_MCP_VERDICT_POLICY"

#: Status values. Kept as constants because downstream policy code keys
#: off them and a typo would silently read as "no check ran."
STATUS_NOT_EVALUATED = "not_evaluated"
STATUS_CHECKED = "checked"
STATUS_REFERENCE_SUPPLIED = "reference_supplied"

#: Earth's mean radius, used only when a grid declares no ``sphere_radius``
#: *and* the caller asked for a physical reference. Never assumed silently:
#: the check records which radius it used and where it came from.
UNIT_SPHERE_RADIUS = 1.0

#: Relative tolerance for the closed-mesh area identity. UXarray integrates
#: spherical polygons with a 4th-order triangular quadrature, so the residual
#: is discretization error, not floating-point error; 1e-6 relative sits
#: comfortably above the ~2e-6 absolute seen on a 162-face structured grid
#: while still catching a genuinely wrong area by orders of magnitude.
AREA_RELATIVE_TOLERANCE = 1e-5


def resolve_verdict_policy(requested: str | None) -> VerdictPolicy:
    """Pick the effective policy: per-request, then env, then default.

    An unrecognized value raises rather than silently downgrading -- a
    deployment that meant to withhold verdicts should not discover a
    typo by finding verdicts in its logs.
    """
    for candidate in (requested, os.getenv(VERDICT_POLICY_ENV)):
        if candidate is None:
            continue
        normalized = str(candidate).strip().lower().replace("-", "_")
        if normalized not in VERDICT_POLICIES:
            raise ValueError(
                f"verdict_policy must be one of {list(VERDICT_POLICIES)}, "
                f"got {candidate!r}."
            )
        return normalized  # type: ignore[return-value]
    return DEFAULT_VERDICT_POLICY


def _relative_residual(computed: float, reference: float) -> float:
    """Residual normalized by the reference, or absolute when it is zero."""
    if reference == 0.0:
        return abs(computed)
    return abs(computed - reference) / abs(reference)


def _postcondition(
    check_id: str,
    computed: float,
    reference: float,
    tolerance: float,
    *,
    identity: str,
    reference_source: str,
    policy: VerdictPolicy,
) -> dict[str, Any]:
    """One postcondition, shaped by the verdict policy.

    Under ``reference_only`` the residual is withheld along with the
    verdict. Supplying the residual but not the verdict would still let a
    caller answer without comparing anything -- it is one ``<`` away from
    the verdict -- so the honest strict shape gives the caller only the
    two inputs it needs and requires it to produce both outputs.
    """
    check: dict[str, Any] = {
        "id": check_id,
        "identity": identity,
        "computed": float(computed),
        "reference": float(reference),
        "reference_source": reference_source,
        "tolerance": float(tolerance),
    }
    if policy == "full":
        residual = _relative_residual(computed, reference)
        check["residual"] = residual
        check["residual_kind"] = "relative"
        check["passed"] = bool(math.isfinite(residual) and residual <= tolerance)
    else:
        check["residual"] = None
        check["residual_kind"] = "relative"
        check["passed"] = None
        check["caller_must_supply"] = ["residual", "passed"]
    return check


def evaluate_area_postconditions(
    result: dict[str, Any],
    grid_loader: Callable[[], Any] | None = None,
    *,
    policy: VerdictPolicy = DEFAULT_VERDICT_POLICY,
) -> list[dict[str, Any]]:
    """Check a closed mesh's total area against ``4*pi*R^2``.

    Two things make this a real check rather than a tautology. The
    reference radius is read from the grid rather than assumed, and it is
    reported, so a unit-sphere answer cannot pass by being compared
    against a unit-sphere reference the caller did not know about (#92).
    The check abstains entirely when the mesh is not closed, because on
    an open regional mesh ``4*pi*R^2`` is not the right number and a
    failing verdict there would be the server being wrong, not the mesh.
    """
    total_area = result.get("total_area")
    if total_area is None or grid_loader is None:
        return []

    try:
        grid = grid_loader()
    except Exception:  # pragma: no cover - a load failure is the caller's error
        return []

    if not mesh_is_closed(grid):
        return []

    declared_radius = getattr(grid, "sphere_radius", None)
    declared = declared_radius is not None
    radius = (
        float(declared_radius) if declared_radius is not None else UNIT_SPHERE_RADIUS
    )

    # UXarray integrates face areas on the unit sphere unless the caller
    # already scaled them, so an unscaled sum is compared against 4*pi even
    # on a grid that correctly declares an Earth radius (#92). Saying which
    # radius was seen and whether it was applied is the point: a unit-sphere
    # answer must not pass by being silently compared against a unit-sphere
    # reference the caller never knew about.
    scaled = bool(result.get("area_units"))
    reference = 4.0 * math.pi * (radius**2 if scaled else 1.0)
    identity = "sum(face_areas) == 4*pi*R^2" if scaled else "sum(face_areas) == 4*pi"
    # Kept terse on purpose: the block is re-sent on every later turn, so
    # every word here is paid for repeatedly (#83).
    if scaled:
        source = f"sphere_radius={radius:g}" if declared else "R=1 assumed"
    else:
        source = (
            f"unit sphere; grid sphere_radius={radius:g} not applied"
            if declared
            else "unit sphere"
        )

    return [
        _postcondition(
            "closed_mesh_total_area",
            float(total_area),
            reference,
            AREA_RELATIVE_TOLERANCE,
            identity=identity,
            reference_source=source,
            policy=policy,
        )
    ]


#: Decimal places used when matching node coordinates. Six is ~0.1 m on
#: Earth's surface, far below any mesh spacing we deal with, and coarse
#: enough to absorb the round-trip through NetCDF float64 text.
_COORD_DECIMALS = 6


def _canonical_node_ids(grid: Any) -> list[int]:
    """Map nodes onto identity by position, not by index.

    A structured global grid stores the 0/360 seam twice and every pole
    once per meridian, so counting edges on raw indices reports boundary
    edges on a mesh that is geometrically closed. Merging nodes that sit
    at the same point -- with all pole nodes collapsing to one, since
    longitude is meaningless there -- makes the count reflect the surface
    rather than the storage layout.
    """
    import numpy as np

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
    directly. Meshes here are small enough for that to be free.
    """
    try:
        import numpy as np

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


def postcondition_block(
    checks: list[dict[str, Any]],
    policy: VerdictPolicy,
) -> dict[str, Any]:
    """Assemble the block attached to every analysis result.

    Present even when nothing was checked: #84's point is that an
    explicit ``not_evaluated`` costs almost nothing and stops a caller
    implying more confidence than the computation supports.
    """
    if not checks or policy == "off":
        return {
            "status": STATUS_NOT_EVALUATED,
            "checks": [],
            "independent_verification": False,
        }

    if policy == "reference_only":
        return {
            "status": STATUS_REFERENCE_SUPPLIED,
            "checks": checks,
            "independent_verification": True,
            "caller_action": (
                "Compute the relative residual against the reference and "
                "state whether it is within tolerance. This server "
                "deliberately withheld the verdict."
            ),
        }

    return {
        "status": STATUS_CHECKED,
        "checks": checks,
        "independent_verification": False,
    }
