"""The wire shape of MCP content blocks, checked against the real adapter.

These tests exist because the failure mode they guard is silent: a block the
adapter does not recognize is not rejected, it is stringified into text. So
each shape is asserted twice -- once against our own builder, and once against
``toolregistry``'s own predicate, which is the thing that actually decides.
"""

from __future__ import annotations

import pytest

from uxarray_mcp.content_blocks import (
    DEFAULT_IMAGE_MIME,
    WIRE_BLOCK_TYPES,
    block_image_data,
    block_text,
    block_uri,
    image_block,
    is_wire_blocks,
    resource_link_block,
    text_block,
)


class TestBuilders:
    def test_text_block_is_flat(self):
        assert text_block("hi") == {"type": "text", "text": "hi"}

    def test_image_mime_lives_inside_source(self):
        # The asymmetry worth a test: every other block carries its MIME on
        # the block, an image carries it in `source`.
        block = image_block("aGk=")
        assert block["type"] == "image"
        assert "mimeType" not in block
        assert block["source"] == {
            "type": "base64",
            "media_type": DEFAULT_IMAGE_MIME,
            "data": "aGk=",
        }

    def test_image_mime_is_overridable(self):
        assert image_block("aGk=", mime_type="image/jpeg")["source"][
            "media_type"
        ] == "image/jpeg"

    def test_resource_link_omits_mime_when_unknown(self):
        assert resource_link_block("file:///a.png", "a.png") == {
            "type": "resource_link",
            "uri": "file:///a.png",
            "name": "a.png",
        }

    def test_resource_link_uses_camel_case_mime_key(self):
        # `mimeType`, not `mime_type`: the adapter reads the camel-case name
        # and a snake_case key is dropped without complaint.
        block = resource_link_block("file:///a.png", "a.png", mime_type="image/png")
        assert block["mimeType"] == "image/png"


class TestGate:
    def test_our_predicate_matches_the_adapters(self):
        # If toolregistry widens or narrows its set, this fails here rather
        # than in production output.
        from toolregistry.llm import content_blocks as upstream

        assert set(upstream._CONTENT_BLOCK_TYPES) == set(WIRE_BLOCK_TYPES)

    @pytest.mark.parametrize(
        "blocks",
        [
            [text_block("hi")],
            [image_block("aGk=")],
            [resource_link_block("file:///a.png", "a.png")],
            [image_block("aGk="), text_block("meta")],
        ],
    )
    def test_every_builder_passes_the_real_gate(self, blocks):
        from toolregistry.llm.content_blocks import is_content_block_list

        assert is_content_block_list(blocks)
        assert is_wire_blocks(blocks)

    @pytest.mark.parametrize(
        "value",
        [
            [],
            {},
            "text",
            [{"type": "unknown"}],
            [{"text": "no type"}],
            [text_block("hi"), {"type": "unknown"}],
        ],
    )
    def test_non_blocks_are_rejected(self, value):
        assert not is_wire_blocks(value)

    def test_pydantic_models_do_not_pass(self):
        # The original bug in one line: an mcp.types model is not a dict, so
        # the adapter stringifies the whole list instead of converting it.
        types = pytest.importorskip("mcp.types")

        assert not is_wire_blocks([types.TextContent(type="text", text="hi")])


class TestAccessors:
    def test_round_trip_through_the_builders(self):
        assert block_image_data(image_block("aGk=")) == "aGk="
        assert block_text(text_block("hi")) == "hi"
        assert block_uri(resource_link_block("file:///a", "a")) == "file:///a"

    def test_accessors_do_not_cross_block_types(self):
        # Reading a text block as an image must return None, not raise and
        # not guess -- callers branch on None to decide delivery mode.
        assert block_image_data(text_block("hi")) is None
        assert block_uri(text_block("hi")) is None
        assert block_text(image_block("aGk=")) is None

    def test_image_block_without_a_source_is_not_an_error(self):
        assert block_image_data({"type": "image"}) is None

    def test_pydantic_models_still_readable(self):
        # Older code paths may still hand back models; the accessors fall
        # back to attributes so composition keeps working during migration.
        types = pytest.importorskip("mcp.types")

        assert block_text(types.TextContent(type="text", text="hi")) == "hi"
        assert (
            block_image_data(
                types.ImageContent(type="image", data="aGk=", mimeType="image/png")
            )
            == "aGk="
        )
