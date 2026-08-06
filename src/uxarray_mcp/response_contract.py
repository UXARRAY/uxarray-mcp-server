"""Declared response shapes a caller can validate against (#91).

The server describes what a tool *does* in prose but never declares the
shape of the answer it expects back. That gap cost real measurement: in a
480-run evaluation of this server, 119 runs had to be re-scored by hand
because the scorer could not tell a formatting failure from a scientific
one, and all seven disputed runs on the verification task failed *only*
on JSON formatting -- five of them a single model emitting bare JSON
instead of a fenced block. The numbers underneath were right.

The fix is to make "right answer, wrong envelope" a separately
detectable state:

- each operation family declares its expected response fields as data
- ``describe_response_contract`` serves that declaration on request
- ``validate_response`` lets a caller check its own draft before
  committing to it, and returns which fields are missing, extra, or of
  the wrong type

Deliberately *not* attached to every result. #83 exists because the
server already sends a tool catalog as 74% of its payload, and a schema
repeated on every reply would be the same mistake in a new costume. The
contract is a separate, cheap call that a caller makes once.
"""

from __future__ import annotations

from typing import Any

#: JSON type names we accept in a field declaration, mapped to the Python
#: types they validate against. ``number`` accepts ``int`` because JSON
#: does not distinguish them and a caller emitting ``0`` for a float field
#: is not making a mistake worth reporting.
_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def _field(
    name: str,
    json_type: str,
    description: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": json_type,
        "required": required,
        "description": description,
    }


#: Fields every operation's response carries, whatever it computed.
_COMMON_FIELDS: list[dict[str, Any]] = [
    _field("operation", "string", "The operation that was run."),
    _field(
        "physically_interpretable",
        "boolean",
        "Whether the server considers the number physically meaningful.",
        required=False,
    ),
]

#: Per-family declarations. Keyed by operation name so a caller can ask
#: about exactly the call it is about to make.
_CONTRACTS: dict[str, dict[str, Any]] = {
    "calculate_area": {
        "summary": "Total and per-face mesh area statistics.",
        "fields": [
            _field("total_area", "number", "Sum of all face areas."),
            _field("mean_area", "number", "Mean face area."),
            _field(
                "area_units",
                "string",
                "Units of the reported areas, or null when the source file "
                "declares none. Do not invent a default.",
                required=False,
            ),
            _field("n_face", "integer", "Number of faces summed."),
        ],
    },
    "inspect_mesh": {
        "summary": "Mesh topology counts and source format.",
        "fields": [
            _field("n_face", "integer", "Number of faces."),
            _field("n_node", "integer", "Number of nodes."),
            _field("n_edge", "integer", "Number of edges."),
        ],
    },
    "calculate_zonal_mean": {
        "summary": "Latitude-banded mean of one face-centered variable.",
        "fields": [
            _field("variable_name", "string", "Variable that was averaged."),
            _field("latitudes", "array", "Latitude band centers, in degrees."),
            _field(
                "zonal_mean_values",
                "array",
                "One mean per latitude band, same length as `latitudes`.",
            ),
        ],
    },
    "validate_dataset": {
        "summary": "Whether a grid/data pair is self-consistent and finite.",
        "fields": [
            _field("passed", "boolean", "True when every check passed."),
            _field(
                "checks", "array", "One entry per validation check.", required=False
            ),
        ],
    },
    "verification": {
        "summary": (
            "A caller-produced verification of a computed value against a "
            "known reference. This is the shape the 480-run study asked "
            "for and could not reliably parse."
        ),
        "fields": [
            _field("computed", "number", "The value the server returned."),
            _field("reference", "number", "The known value it is compared against."),
            _field(
                "residual",
                "number",
                "Absolute or relative difference; say which in "
                "`residual_kind` if ambiguous.",
            ),
            _field(
                "tolerance", "number", "The threshold the residual is judged against."
            ),
            _field(
                "verification_passed",
                "boolean",
                "True when the residual is within tolerance.",
            ),
        ],
        "encoding": {
            "format": "json",
            "delivery": (
                "Emit the object inside a fenced ```json block. Bare JSON "
                "with no fence was the single most common formatting "
                "failure in the study and is not accepted."
            ),
        },
    },
}

#: Operations that share another operation's declared shape.
_ALIASES: dict[str, str] = {
    "area": "calculate_area",
    "mesh": "inspect_mesh",
    "zonal_mean": "calculate_zonal_mean",
    "verify": "verification",
    "check": "verification",
}


def _normalize(operation: str) -> str:
    name = operation.strip().lower().replace("-", "_")
    return _ALIASES.get(name, name)


def available_contracts() -> list[str]:
    """Operation names that declare a response shape."""
    return sorted(_CONTRACTS)


def describe_response_contract(operation: str) -> dict[str, Any]:
    """Return the declared response shape for one operation.

    Raises ``ValueError`` for an operation with no declaration, rather
    than returning an empty contract: "no fields are required" and "we
    never said" are different claims, and a caller should not read the
    second as the first.
    """
    name = _normalize(operation)
    contract = _CONTRACTS.get(name)
    if contract is None:
        raise ValueError(
            f"No response contract declared for {operation!r}. "
            f"Declared operations: {available_contracts()}."
        )
    fields = list(contract["fields"]) + _COMMON_FIELDS
    return {
        "operation": name,
        "summary": contract["summary"],
        "fields": fields,
        "required": [f["name"] for f in fields if f["required"]],
        "encoding": contract.get(
            "encoding",
            {"format": "json", "delivery": "Emit the object as JSON."},
        ),
    }


def validate_response(operation: str, response: dict[str, Any]) -> dict[str, Any]:
    """Check a caller's draft response against the declared shape.

    Returns a verdict rather than raising, because the point is to let a
    caller fix its own envelope before committing to it. Extra fields are
    reported but do not fail: a caller adding context is not the failure
    mode this exists to catch.
    """
    contract = describe_response_contract(operation)
    declared = {f["name"]: f for f in contract["fields"]}

    missing = [
        name
        for name, field in declared.items()
        if field["required"] and name not in response
    ]
    extra = [name for name in response if name not in declared]

    wrong_type: list[dict[str, Any]] = []
    for name, value in response.items():
        field = declared.get(name)
        if field is None or value is None:
            continue
        accepted = _TYPE_MAP.get(field["type"])
        if accepted is None:  # pragma: no cover - guarded by _field callers
            continue
        # bool is a subclass of int, so a boolean passed where a number is
        # declared would otherwise validate silently.
        if isinstance(value, bool) and field["type"] in {"number", "integer"}:
            wrong_type.append(
                {"name": name, "expected": field["type"], "got": "boolean"}
            )
        elif not isinstance(value, accepted):
            wrong_type.append(
                {
                    "name": name,
                    "expected": field["type"],
                    "got": type(value).__name__,
                }
            )

    valid = not missing and not wrong_type
    return {
        "operation": contract["operation"],
        "valid": valid,
        "missing_fields": missing,
        "extra_fields": extra,
        "wrong_type": wrong_type,
        "verdict": ("well_formed" if valid else "malformed_envelope"),
        "note": (
            "A malformed envelope says nothing about whether the science is "
            "right; report it separately from a scientific failure."
        ),
    }
