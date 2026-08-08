"""Compile declared response shapes into MCP ``outputSchema`` (#103).

``response_contract`` already states, as data, what each operation family
returns.  Until now that declaration was only reachable by *asking* --
a caller had to invoke ``describe_response_contract`` before it could
know the shape of the answer it was about to receive.

The July 2026 MCP revision lets a server publish that same information
in the tool listing as ``outputSchema``, and return the object itself as
``structuredContent`` beside the human-readable text.  A client can then
validate the reply without a second round trip, and an agent no longer
has to infer the return shape from prose.

Two things matter about how this is done here:

* **One source of truth.**  The JSON Schema is *compiled* from the same
  ``_CONTRACTS`` table that ``describe_response_contract`` serves.  A
  schema maintained separately from the prose contract would drift, and
  a schema that disagrees with the documentation is worse than none.
* **Additive, never load-bearing.**  Every schema sets
  ``additionalProperties: true`` and declares only the fields we are
  willing to promise.  A tool that grows a field does not break a client
  that validated against the older schema.

The complementary half is ``resource_link``: results that carry a large
opaque payload (a rendered PNG, a full zonal profile) can hand back a
URI instead of inlining bytes into the conversation.
"""

from __future__ import annotations

from typing import Any

from .response_contract import (
    _COMMON_FIELDS,
    _CONTRACTS,
    _normalize,
    available_contracts,
)

#: The ``_provenance`` block every operation attaches.  Declared once and
#: referenced by each schema so the promise is uniform: an agent that
#: learns to read provenance on one tool can read it on all of them.
_PROVENANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Worker-observed execution record: where the call actually ran, "
        "what it read, and what it produced. Populated by the worker, not "
        "asserted by the caller."
    ),
    "properties": {
        "tool": {"type": "string", "description": "Operation that ran."},
        "venue": {
            "type": "string",
            "description": (
                "Execution venue as the worker observed it, e.g. 'local' or "
                "'hpc:<endpoint-name>'. Compare against the venue requested."
            ),
        },
        "inputs": {"type": "object", "description": "Arguments as resolved."},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array", "items": {"type": "object"}},
    },
    "additionalProperties": True,
}


def _json_schema_for_field(field: dict[str, Any]) -> dict[str, Any]:
    """Translate one declared field into a JSON Schema property."""
    node: dict[str, Any] = {"description": field["description"]}
    json_type = field["type"]
    # A field that may legitimately be absent-but-present-as-null (units we
    # refuse to invent, for instance) must accept null, or a client that
    # validates strictly would reject an honest abstention.
    if not field["required"]:
        node["type"] = [json_type, "null"]
    else:
        node["type"] = json_type
    if json_type == "array":
        node["items"] = {}
    return node


def output_schema_for(operation: str) -> dict[str, Any] | None:
    """Return the MCP ``outputSchema`` for one operation, if declared.

    Returns ``None`` rather than an empty schema for an undeclared
    operation: publishing ``{}`` would claim we had described the result
    when we had not.
    """
    name = _normalize(operation)
    if name in _FRONTDOOR_SCHEMAS:
        return _FRONTDOOR_SCHEMAS[name]
    contract = _CONTRACTS.get(name)
    if contract is None:
        return None

    fields = list(contract["fields"]) + _COMMON_FIELDS
    properties = {f["name"]: _json_schema_for_field(f) for f in fields}
    properties["_provenance"] = _PROVENANCE_SCHEMA

    return {
        "type": "object",
        "title": f"{name} result",
        "description": contract["summary"],
        "properties": properties,
        # Only fields we are willing to promise on every successful call.
        # A refusal is a different shape and is not validated against this.
        "required": [f["name"] for f in fields if f["required"]],
        "additionalProperties": True,
    }


def declared_output_schemas() -> dict[str, dict[str, Any]]:
    """Every operation that publishes an ``outputSchema``, keyed by name."""
    schemas: dict[str, dict[str, Any]] = dict(_FRONTDOOR_SCHEMAS)
    for name in available_contracts():
        schema = output_schema_for(name)
        if schema is not None:
            schemas[name] = schema
    return schemas


#: The envelope ``analyze_dataset`` wraps every successful analysis in.
#: This is the paper's result contract expressed as a schema rather than as
#: prose: an agent reading ``tools/list`` learns that a result may refuse
#: (``result_type`` is ``input_required``), may abstain (a postcondition with
#: verdict ``not_evaluated``), and always says where it ran.
_ANALYSIS_ENVELOPE: dict[str, Any] = {
    "type": "object",
    "title": "analysis result",
    "description": (
        "Result of one analysis operation. Two shapes share this schema: a "
        "completed analysis (result_type='complete') carrying the operation's "
        "own fields, and a refusal (result_type='input_required') carrying the "
        "failed checks and the repair that would satisfy them, with no number."
    ),
    "properties": {
        "result_type": {
            "type": "string",
            "enum": ["complete", "input_required"],
            "description": (
                "'complete' means a number was produced. 'input_required' "
                "means a physical precondition failed and the value was "
                "deliberately withheld -- read 'preconditions.failed_checks' "
                "and the named repair rather than retrying unchanged."
            ),
        },
        "scientific_status": {
            "type": "object",
            "description": (
                "Whether the server considers the number physically "
                "meaningful, and why not when it does not."
            ),
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["complete", "warning", "unverified", "invalid"],
                },
                "physically_interpretable": {
                    "type": ["boolean", "null"],
                    "description": (
                        "null means the server did not judge. Do not read null as true."
                    ),
                },
                "warning_codes": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
        "preconditions": {
            "type": "object",
            "description": (
                "Physical conditions checked before computing. Status "
                "'not_evaluated' means no check ran -- distinct from 'failed'."
            ),
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["satisfied", "failed", "not_evaluated"],
                },
                "checks": {"type": "array", "items": {"type": "object"}},
                "failed_checks": {"type": "array", "items": {"type": "string"}},
                "override_used": {
                    "type": "boolean",
                    "description": (
                        "True when a caller forced past a failed check. An "
                        "overridden result never claims interpretability."
                    ),
                },
            },
            "additionalProperties": True,
        },
        "postconditions": {
            "type": "object",
            "description": (
                "Checks on the value after computing. A check may report "
                "'not_evaluated', which is an explicit abstention rather "
                "than a pass."
            ),
            "additionalProperties": True,
        },
        "_provenance": _PROVENANCE_SCHEMA,
    },
    "required": ["result_type"],
    "additionalProperties": True,
}

#: Front-door tools and the envelope they return.  Keyed by the registered
#: tool name because front doors are registered at top level without a
#: namespace.
_FRONTDOOR_SCHEMAS: dict[str, dict[str, Any]] = {
    "analyze_dataset": _ANALYSIS_ENVELOPE,
}


# ---------------------------------------------------------------------------
# resource_link
# ---------------------------------------------------------------------------

#: Results at or above this many bytes are worth handing back by reference
#: rather than inlining.  Chosen to sit below a typical model's per-message
#: budget while still letting small plots come back inline, which keeps the
#: common interactive case a single round trip.
INLINE_PAYLOAD_LIMIT_BYTES = 256 * 1024


def make_resource_link(
    uri: str,
    name: str,
    *,
    title: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
    size: int | None = None,
) -> dict[str, Any]:
    """Build one ``_resource_links`` entry.

    The adapter turns each entry into an MCP ``resource_link`` content
    block.  ``uri`` and ``name`` are the only required members; the rest
    are advisory and are dropped when unset.
    """
    link: dict[str, Any] = {"uri": uri, "name": name}
    if title is not None:
        link["title"] = title
    if description is not None:
        link["description"] = description
    if mime_type is not None:
        link["mime_type"] = mime_type
    if size is not None:
        link["size"] = int(size)
    return link


def attach_resource_link(
    result: dict[str, Any], link: dict[str, Any]
) -> dict[str, Any]:
    """Append one resource link to a result, creating the list if needed."""
    links = result.setdefault("_resource_links", [])
    links.append(link)
    return result


def should_link_rather_than_inline(size_bytes: int) -> bool:
    """Whether a payload of this size should be referenced, not inlined."""
    return size_bytes >= INLINE_PAYLOAD_LIMIT_BYTES


def spill_png(png_bytes: bytes, *, plot_type: str) -> dict[str, Any] | None:
    """Write a large PNG to the artifact store and describe it as a link.

    Returns ``None`` when the image is small enough to inline, which keeps
    the ordinary interactive case a single round trip with no file to clean
    up. Above the threshold the bytes go to the same artifact directory
    result handles already use, and the caller gets a ``file://`` URI.

    Never raises: if the artifact store is not writable, inlining is still
    correct behaviour, so a failure here degrades to the old path.
    """
    if not should_link_rather_than_inline(len(png_bytes)):
        return None
    try:
        from .state import _artifacts_dir, _new_id

        result_id = _new_id("plot")
        path = _artifacts_dir() / f"{result_id}.png"
        path.write_bytes(png_bytes)
    except Exception:  # pragma: no cover - defensive, falls back to inline
        return None
    return make_resource_link(
        uri=path.as_uri(),
        name=f"{result_id}.png",
        title=f"{plot_type} plot",
        description=(
            f"Rendered {plot_type} PNG, {len(png_bytes)} bytes. Held out of "
            "the conversation because inlining it would cost more context "
            "than the figure is worth."
        ),
        mime_type="image/png",
        size=len(png_bytes),
    )
