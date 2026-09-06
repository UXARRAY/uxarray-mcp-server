"""Server-side postcondition checks for analysis results (#84, #90).

A precondition asks whether an operation *should* run. A postcondition
asks whether the number it produced is consistent with something already
known. Benchmarking showed what the second one is worth: on a task where
every interface computed the identical total area, adding a block stating
reference, residual, tolerance, and verdict took correct answers from
11/20 to 20/20, and every model deployment reached 5/5.

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

from uxarray_mcp.domain.mesh_coverage import mesh_is_closed

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
    ``area_identity_abstention`` turns that silence into a stated reason.
    """
    total_area = result.get("total_area")
    if total_area is None or grid_loader is None:
        return []

    try:
        grid = grid_loader()
    except Exception:  # pragma: no cover - a load failure is the caller's error
        return []

    # ``mesh_coverage`` already counted edge incidences, and on a large mesh
    # that is seconds rather than milliseconds. Fall back to counting again
    # only for a remote worker on an older build, which sends no block.
    coverage = result.get("mesh_coverage") or {}
    closed = coverage.get("closed") if "closed" in coverage else mesh_is_closed(grid)
    if not closed:
        return []

    basis = result.get("area_basis") or {}
    declared_radius = basis.get("sphere_radius", getattr(grid, "sphere_radius", None))
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
    # ``area_basis`` says outright whether the radius was applied. Falling
    # back to the presence of a units string keeps a remote worker on an
    # older build, which sends no basis, reading the way it always did.
    scaled = (
        bool(basis["scaled"]) if "scaled" in basis else bool(result.get("area_units"))
    )
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


def area_identity_abstention(result: dict[str, Any]) -> str | None:
    """Say why ``sum(face_areas) == 4*pi*R^2`` was not evaluated.

    Read off the ``mesh_coverage`` block rather than the grid, so naming
    the reason costs no second traversal of a mesh that may have taken
    seconds to traverse once. Returns ``None`` when the abstention has no
    explanation this function can give -- an unloadable grid, or a result
    from a worker old enough to send no coverage -- because inventing one
    would be worse than the silence it replaces.

    Kept to one sentence on purpose: the block is re-sent on every later
    turn of a conversation, so every word here is paid for repeatedly
    (#83).
    """
    coverage = result.get("mesh_coverage")
    if not coverage:
        return None

    if coverage.get("topology_skipped"):
        return (
            "The 4*pi*R^2 identity holds only on a closed mesh and closure "
            f"was not checked: {coverage['topology_skipped']}"
        )

    if coverage.get("closed") is False:
        fraction = coverage.get("sphere_fraction")
        extent = (
            f" It covers {fraction:.4%} of the sphere."
            if isinstance(fraction, (int, float))
            else ""
        )
        return (
            "The 4*pi*R^2 identity holds only on a closed mesh, and this one "
            f"has at least one boundary edge.{extent}"
        )

    return None


def postcondition_block(
    checks: list[dict[str, Any]],
    policy: VerdictPolicy,
    *,
    not_evaluated_reason: str | None = None,
) -> dict[str, Any]:
    """Assemble the block attached to every analysis result.

    Present even when nothing was checked: #84's point is that an
    explicit ``not_evaluated`` costs almost nothing and stops a caller
    implying more confidence than the computation supports.

    ``not_evaluated`` on its own turned out to be half the disclosure. A
    regional mesh came back with ``{"status": "not_evaluated",
    "checks": []}`` because the area identity abstains on an open mesh,
    and the payload never said that was why -- indistinguishable from a
    deployment that had checking switched off. ``not_evaluated_because``
    carries the reason when the caller can be told one.
    """
    if not checks or policy == "off":
        block: dict[str, Any] = {
            "status": STATUS_NOT_EVALUATED,
            "checks": [],
            "independent_verification": False,
        }
        reason = (
            f"{VERDICT_POLICY_ENV.lower()}={policy}: no check was run."
            if policy == "off"
            else not_evaluated_reason
        )
        if reason:
            block["not_evaluated_because"] = reason
        return block

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
