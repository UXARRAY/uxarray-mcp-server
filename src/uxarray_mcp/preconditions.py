"""Refusable preconditions for analysis operations (issue #86).

A warning that does not stop the next step is advice. Benchmarking
measured what that costs: across four model deployments, returning
``VECTOR_COMPONENTS_UNVERIFIED`` alongside a number changed nothing --
9/20, 10/20, and 10/20 correct regardless of how much warning text came
back. Detection was never the gap. The server already knew.

This module makes the knowledge enforceable. Operations declare their
preconditions **as data** rather than prose, and a failed precondition
**refuses** by default instead of computing anyway. The caller can still
get the unphysical number, but only by asking for it explicitly.

The refusal is shaped after the MCP ``2026-07-28`` multi-round-trip
request (MRTR) flow. ``InputRequiredResult`` lets a server answer a
``tools/call`` with "I need something from you first" and an opaque
``request_state`` the client echoes back on retry. We mirror that shape
in the tool result:

- ``result_type`` is ``"input_required"`` rather than ``"complete"``
- ``input_requests`` carries an ``elicitation/create`` form request
  describing the acknowledgment we need
- ``request_state`` is an opaque token the caller passes back verbatim

Why mirror it rather than emit it: ``toolregistry-server`` serializes
tool returns into ``TextContent``, so we cannot hand a real
``InputRequiredResult`` to the transport today. Building the payload in
the spec's shape now means the day the adapter grows MRTR support this
becomes a passthrough rather than a redesign.

Note that ``not_evaluated`` (#84) and a failed precondition are
different states and stay distinct: one is "we did not check," the other
is "we checked and it fails."
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Sentinel a caller passes as ``acknowledge`` to run an operation whose
#: preconditions failed. Deliberately verbose: a model should not be able
#: to produce it by accident, and it should read as a decision in a log.
OVERRIDE_TOKEN = "i-understand-this-result-may-not-be-physical"

#: Marks a result the caller must act on before the computation will run.
RESULT_TYPE_INPUT_REQUIRED = "input_required"
RESULT_TYPE_COMPLETE = "complete"


class PreconditionRefusal(Exception):
    """Raised when a declared precondition fails and no override was given.

    Carries the full MRTR-shaped payload so the front door can return it
    as a structured result rather than a bare error string.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        summary = payload.get("refusal", {}).get("summary", "precondition failed")
        super().__init__(summary)


def _check(
    check_id: str,
    passed: bool,
    detail: str,
    repair: str,
) -> dict[str, Any]:
    """One precondition outcome, as data rather than prose."""
    return {
        "id": check_id,
        "passed": bool(passed),
        "detail": detail,
        "repair": repair,
    }


def evaluate_vector_preconditions(
    operation: str,
    u_variable: str,
    v_variable: str,
    evidence: dict[str, Any],
    scale_by_radius: bool | None,
) -> list[dict[str, Any]]:
    """Declare what must hold for ``curl``/``divergence`` to be physical.

    Three conditions, each independently checkable from metadata the
    server already reads:

    1. The two components are distinct fields.
    2. Both carry velocity-like units.
    3. Their direction identity (eastward/northward) is resolvable from
       ``standard_name`` or ``long_name``.

    ``curl`` additionally requires radius scaling, without which the
    result is a unit-sphere quantity rather than a vorticity in s^-1.
    """
    u_ev = evidence.get("u", {}) or {}
    v_ev = evidence.get("v", {}) or {}
    checks = [
        _check(
            # Unnamed components cannot be compared, so this check abstains
            # rather than failing: a missing name is a gap in what we were
            # told, not evidence that the same field was passed twice.
            "components_distinct",
            not (u_variable and v_variable) or u_variable != v_variable,
            f"u_variable={u_variable!r}, v_variable={v_variable!r}.",
            "Pass two different variables: the eastward and northward "
            "components of one vector field.",
        ),
        _check(
            "velocity_units",
            bool(evidence.get("units_supported")),
            f"units: {u_variable}={u_ev.get('units') or 'unset'!r}, "
            f"{v_variable}={v_ev.get('units') or 'unset'!r}.",
            "Use components whose 'units' attribute is velocity- or "
            "flux-like (e.g. 'm s-1'), or set the attribute on the source "
            "data if it is missing but the field really is a velocity.",
        ),
        _check(
            "component_identity",
            bool(evidence.get("component_identity_supported")),
            f"direction metadata: {u_variable} eastward="
            f"{bool(u_ev.get('eastward'))}, {v_variable} northward="
            f"{bool(v_ev.get('northward'))}.",
            "Use components whose 'standard_name' or 'long_name' names the "
            "direction (e.g. 'eastward_sea_water_velocity' and "
            "'northward_sea_water_velocity') so the pairing is unambiguous.",
        ),
    ]
    if operation == "curl":
        checks.append(
            _check(
                "radius_scaling",
                bool(scale_by_radius),
                f"scale_by_radius={bool(scale_by_radius)}.",
                "Set scale_by_radius=True so the result carries physical "
                "units instead of unit-sphere units.",
            )
        )
    return checks


def evaluate_validation_preconditions(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Declare that a dataset must validate before it is analyzed further.

    In the study, models did stop after a failed validation -- but they
    stopped because the prompt told them to, not because anything
    prevented them from continuing. That safety came from the prompt,
    which will not always be there.
    """
    passed = result.get("passed", result.get("is_valid"))
    return [
        _check(
            "dataset_valid",
            passed is not False,
            f"validate_dataset reported passed={passed!r}.",
            "Fix the reported validation failures, or select a variable "
            "that passes, before deriving quantities from this dataset.",
        )
    ]


def evaluate_remap_preconditions(coverage: dict[str, Any]) -> list[dict[str, Any]]:
    """Declare that a remap target must overlap its source mesh.

    #85 shipped ``REMAP_COVERAGE_ZERO`` as a warning printed beside the
    numbers. Zero coverage means *every* returned value is extrapolated
    from outside the source mesh, so the field is not a remap of anything
    -- that is the one coverage state worth refusing over.

    Partial coverage and a non-conservative method stay warnings: both
    describe results a caller can still reason about, and refusing on
    them would make ordinary regional remaps unusable.
    """
    codes = list(coverage.get("warning_codes", []) or [])
    n_total = coverage.get("n_target_points")
    n_in = coverage.get("points_in_source")
    bbox = coverage.get("source_bbox") or {}
    if bbox:
        extent = (
            f"lon [{bbox.get('lon_min')}, {bbox.get('lon_max')}], "
            f"lat [{bbox.get('lat_min')}, {bbox.get('lat_max')}]"
        )
    else:
        extent = "unknown (source bounding box not reported)"
    return [
        _check(
            "remap_coverage_nonzero",
            "REMAP_COVERAGE_ZERO" not in codes,
            f"{n_in} of {n_total} target points fall inside the source mesh; "
            f"the source covers {extent}.",
            "Choose target_lon/target_lat ranges that overlap the source "
            "mesh extent reported above, so at least some target points "
            "are interpolated rather than extrapolated.",
        )
    ]


def _request_state(operation: str, failed: list[dict[str, Any]]) -> str:
    """An opaque token identifying exactly this refusal.

    The MRTR flow has the client echo ``request_state`` back verbatim on
    retry. Deriving it from the operation and the failed check ids means
    a token cannot be replayed against a different refusal.
    """
    material = json.dumps(
        {"operation": operation, "failed": sorted(c["id"] for c in failed)},
        sort_keys=True,
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"precondition:{operation}:{digest}"


def _elicitation(operation: str, failed: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the ``elicitation/create`` request embedded in the refusal.

    Shaped as an MCP ``InputRequest``: a form-mode elicitation whose
    schema has exactly the fields we need back. Only top-level
    properties, no nesting, per the spec's restricted JSON Schema subset.
    """
    names = ", ".join(c["id"] for c in failed)
    return {
        "method": "elicitation/create",
        "params": {
            "mode": "form",
            "message": (
                f"{operation!r} was refused because these declared "
                f"preconditions failed: {names}. Apply one of the listed "
                "repairs and call again, or confirm you want the "
                "unverified result anyway."
            ),
            "requestedSchema": {
                "type": "object",
                "properties": {
                    "acknowledge": {
                        "type": "string",
                        "const": OVERRIDE_TOKEN,
                        "description": (
                            "Pass this exact string as the 'acknowledge' "
                            "argument to run the operation anyway. The "
                            "result will be labeled unverified."
                        ),
                    }
                },
                "required": ["acknowledge"],
            },
        },
    }


def enforce(
    operation: str,
    checks: list[dict[str, Any]],
    acknowledge: str | None,
) -> dict[str, Any]:
    """Apply declared preconditions, refusing by default on failure.

    Returns the ``preconditions`` block to attach to a successful result.
    Raises :class:`PreconditionRefusal` when a check fails and the caller
    did not supply the override token.

    After a refusal we return *only* the repairs that would make the call
    valid. A bounded set of next steps is more useful to a model than
    free rein, and it is the difference between "something is wrong" and
    "do one of these three things."
    """
    failed = [c for c in checks if not c["passed"]]
    overridden = bool(failed) and acknowledge == OVERRIDE_TOKEN

    if failed and not overridden:
        if acknowledge is not None:
            # A wrong token is a failed override, not a silent pass. Say so,
            # otherwise a model that guesses a plausible-looking string gets
            # the number it was refused.
            hint = (
                f"acknowledge={acknowledge!r} is not the override token. "
                f"The exact value is {OVERRIDE_TOKEN!r}."
            )
        else:
            hint = (
                "No override was supplied, so the operation did not run and "
                "no number was produced."
            )
        raise PreconditionRefusal(
            {
                "result_type": RESULT_TYPE_INPUT_REQUIRED,
                "operation": operation,
                "refusal": {
                    "summary": (
                        f"{operation!r} refused: "
                        f"{len(failed)} of {len(checks)} preconditions failed."
                    ),
                    "failed_checks": failed,
                    "repairs": [c["repair"] for c in failed],
                    "override": {
                        "parameter": "acknowledge",
                        "value": OVERRIDE_TOKEN,
                        "effect": (
                            "Runs the operation and returns the number with "
                            "preconditions.status='overridden' and "
                            "physically_interpretable=False."
                        ),
                    },
                    "hint": hint,
                },
                "input_requests": {
                    "acknowledge_unverified": _elicitation(operation, failed)
                },
                "request_state": _request_state(operation, failed),
            }
        )

    if overridden:
        status = "overridden"
    elif failed:  # pragma: no cover - unreachable; kept for explicitness
        status = "failed"
    else:
        status = "satisfied"

    return {
        "status": status,
        "checks": checks,
        "failed_checks": [c["id"] for c in failed],
        "override_used": overridden,
    }
