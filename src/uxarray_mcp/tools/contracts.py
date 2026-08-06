"""Tools that serve the declared response contract (#91).

Kept as two small read-only tools rather than an extra block on every
result: #83 exists because the server already sends too much, and a
schema repeated on every reply would be that mistake in a new costume.
A caller asks once, then validates its own draft before committing.
"""

from __future__ import annotations

from typing import Any, Dict

from uxarray_mcp.provenance import attach_provenance
from uxarray_mcp.response_contract import available_contracts
from uxarray_mcp.response_contract import (
    describe_response_contract as _describe,
)
from uxarray_mcp.response_contract import validate_response as _validate


def describe_response_contract(operation: str) -> Dict[str, Any]:
    """Return the response shape this server expects a caller to produce.

    Args:
        operation: Operation name, e.g. ``"calculate_area"`` or
            ``"verification"``. Aliases such as ``"area"`` and ``"verify"``
            resolve to the same contract.

    Returns:
        The declared fields (name, type, required, description), the list
        of required field names, and an ``encoding`` block stating how the
        object must be delivered -- the verification contract requires a
        fenced ``json`` block, which is where most format failures came
        from.
    """
    contract = _describe(operation)
    contract["available_operations"] = available_contracts()
    return attach_provenance(
        contract,
        tool="describe_response_contract",
        inputs={"operation": operation},
    )


def validate_response(operation: str, response: Dict[str, Any]) -> Dict[str, Any]:
    """Check a draft response against the declared contract before sending it.

    Args:
        operation: Operation whose contract to validate against.
        response: The object the caller intends to emit.

    Returns:
        ``valid``, plus ``missing_fields``, ``extra_fields`` and
        ``wrong_type``. A ``malformed_envelope`` verdict says nothing
        about whether the science is right; the two failures are reported
        separately on purpose.
    """
    verdict = _validate(operation, response)
    return attach_provenance(
        verdict,
        tool="validate_response",
        inputs={"operation": operation, "response_keys": sorted(response)},
    )
