"""MCP content blocks in the shape the adapter actually recognizes.

``toolregistry-server`` converts a tool result into MCP content only when the
result is a list of **plain dicts** whose ``type`` is one that
``toolregistry.llm.content_blocks.is_content_block_list`` knows. A list of
``mcp.types`` models fails that test, so the whole result is JSON-serialized
into a single ``TextContent`` and the image reaches the caller as a Python
``repr`` inside a string -- no error, just a picture that is no longer a
picture. The wire shape is therefore built here, once, instead of at each
call site.

Two asymmetries in the adapter are easy to get wrong and are encoded here so
no caller has to remember them:

* an ``image`` carries its MIME type *inside* ``source``, while every other
  block carries it on the block itself;
* the adapter reads only ``uri``, ``name`` and the MIME type off a
  ``resource_link`` -- a title, description or size passed on the block is
  silently dropped, so those belong in the accompanying metadata instead.

Recognized types are ``text``, ``image``, ``audio``, ``resource_link`` and
``resource`` as of ``toolregistry`` 0.16.0; on 0.15.0 the last three are not
recognized and degrade to stringified text, which is why the floor moved.
"""

from typing import Any

#: Block types the adapter converts natively. Kept local rather than imported
#: from toolregistry so that a version skew shows up as a failing test here
#: rather than as silently stringified output in production.
WIRE_BLOCK_TYPES = frozenset({"text", "image", "audio", "resource_link", "resource"})

DEFAULT_IMAGE_MIME = "image/png"


def text_block(text: str) -> dict[str, Any]:
    """Build a ``text`` content block."""
    return {"type": "text", "text": text}


def image_block(
    data_b64: str, *, mime_type: str = DEFAULT_IMAGE_MIME
) -> dict[str, Any]:
    """Build an ``image`` content block from base64-encoded bytes.

    The MIME type goes inside ``source``: that is where the adapter looks
    for an image, and it is mandatory in practice because ``ImageContent``
    declares ``mime_type`` with no default.
    """
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime_type, "data": data_b64},
    }


def resource_link_block(
    uri: str, name: str, *, mime_type: str | None = None
) -> dict[str, Any]:
    """Build a ``resource_link`` content block.

    ``uri`` and ``name`` are required -- the adapter subscripts both, so a
    missing key surfaces as an opaque internal error rather than a
    validation message.
    """
    block: dict[str, Any] = {"type": "resource_link", "uri": uri, "name": name}
    if mime_type is not None:
        block["mimeType"] = mime_type
    return block


def is_wire_blocks(value: Any) -> bool:
    """Whether *value* is a list the adapter will treat as content blocks.

    Mirrors ``is_content_block_list``: a non-empty list in which every
    element is a dict carrying a recognized ``type``.
    """
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, dict) and item.get("type") in WIRE_BLOCK_TYPES
            for item in value
        )
    )


def block_image_data(block: Any) -> str | None:
    """Read base64 image bytes back out of a block, or None.

    Tools that compose other tools' output (the orchestrator, the
    benchmarks) need to unpack a block without re-deriving its layout.
    """
    if isinstance(block, dict) and block.get("type") == "image":
        source = block.get("source")
        if isinstance(source, dict):
            return source.get("data")
        return None
    # An mcp.types model may still arrive from an older code path.
    return getattr(block, "data", None)


def block_uri(block: Any) -> str | None:
    """Read a ``resource_link`` URI back out of a block, or None."""
    if isinstance(block, dict):
        return block.get("uri") if block.get("type") == "resource_link" else None
    uri = getattr(block, "uri", None)
    return None if uri is None else str(uri)


def block_text(block: Any) -> str | None:
    """Read the text back out of a ``text`` block, or None."""
    if isinstance(block, dict):
        return block.get("text") if block.get("type") == "text" else None
    return getattr(block, "text", None)
