"""MCP typed results: outputSchema, resource_link, tools/list cache hints (#103)."""

from __future__ import annotations

import json

import pytest

from uxarray_mcp.app import (
    LIST_TOOLS_CACHE_SCOPE,
    LIST_TOOLS_TTL_MS,
    make_mcp_server,
    make_registry,
)
from uxarray_mcp.response_contract import (
    available_contracts,
    describe_response_contract,
)
from uxarray_mcp.typed_results import (
    INLINE_PAYLOAD_LIMIT_BYTES,
    attach_resource_link,
    declared_output_schemas,
    make_resource_link,
    output_schema_for,
    should_link_rather_than_inline,
    spill_png,
)


def _adapter_forwards_output_schema() -> bool:
    """Whether the installed adapter carries our schema through to a route.

    We publish the schema either way; only the hand-off to the MCP layer needs
    adapter support, which is not in the released version yet.
    """
    from toolregistry_server.route_table import RouteEntry

    return "output_schema" in getattr(RouteEntry, "__dataclass_fields__", {})


needs_schema_adapter = pytest.mark.skipif(
    not _adapter_forwards_output_schema(),
    reason="installed toolregistry-server does not forward output_schema yet",
)


class TestOutputSchema:
    def test_every_declared_contract_compiles(self):
        for operation in available_contracts():
            schema = output_schema_for(operation)
            assert schema is not None, operation
            assert schema["type"] == "object"
            # Additive by construction: a tool may grow fields without
            # breaking a client that validated against an older schema.
            assert schema["additionalProperties"] is True

    def test_undeclared_operation_returns_none_not_empty_schema(self):
        # "We never described this" and "this has no required fields" are
        # different claims and must not be conflated.
        assert output_schema_for("no_such_operation") is None

    def test_schema_matches_the_prose_contract(self):
        # One source of truth: the schema is compiled from the same table
        # describe_response_contract serves, so the two cannot drift.
        for operation in available_contracts():
            contract = describe_response_contract(operation)
            schema = output_schema_for(operation)
            for field in contract["fields"]:
                assert field["name"] in schema["properties"], (operation, field)
            assert set(schema["required"]) == set(contract["required"])

    def test_optional_fields_accept_null(self):
        # An honest abstention (units we refuse to invent) must validate.
        schema = output_schema_for("calculate_area")
        assert schema["properties"]["area_units"]["type"] == ["string", "null"]
        assert schema["properties"]["total_area"]["type"] == "number"

    def test_provenance_is_declared_on_every_schema(self):
        for operation, schema in declared_output_schemas().items():
            assert "_provenance" in schema["properties"], operation

    def test_aliases_resolve_to_the_same_schema(self):
        assert output_schema_for("area") == output_schema_for("calculate_area")

    def test_schemas_are_json_serializable(self):
        # They travel over the wire in tools/list.
        json.dumps(declared_output_schemas())


class TestAnalysisEnvelope:
    """The front-door envelope is the paper's result contract as a schema."""

    def test_refusal_is_advertised_as_a_reachable_shape(self):
        schema = output_schema_for("analyze_dataset")
        result_type = schema["properties"]["result_type"]
        assert set(result_type["enum"]) == {"complete", "input_required"}
        assert schema["required"] == ["result_type"]

    def test_contract_blocks_are_all_declared(self):
        props = output_schema_for("analyze_dataset")["properties"]
        for block in (
            "scientific_status",
            "preconditions",
            "postconditions",
            "_provenance",
        ):
            assert block in props

    def test_not_evaluated_is_distinct_from_failed(self):
        # #84: "we did not check" must not read as "the check passed".
        pre = output_schema_for("analyze_dataset")["properties"]["preconditions"]
        assert set(pre["properties"]["status"]["enum"]) == {
            "satisfied",
            "failed",
            "not_evaluated",
        }

    def test_interpretability_is_nullable(self):
        status = output_schema_for("analyze_dataset")["properties"]["scientific_status"]
        assert status["properties"]["physically_interpretable"]["type"] == [
            "boolean",
            "null",
        ]


class TestRegistryPublishesSchemas:
    @pytest.mark.parametrize("profile", ["core", "deferred-full"])
    def test_schema_reaches_tool_metadata(self, profile):
        registry = make_registry(profile=profile)
        published = {
            name
            for name in registry.list_tools()
            if "output_schema"
            in (getattr(registry.get_tool(name).metadata, "extra", None) or {})
        }
        assert "analyze_dataset" in published

    def test_deferred_profile_publishes_the_compute_tools(self):
        registry = make_registry(profile="deferred-full")
        published = {
            name
            for name in registry.list_tools()
            if "output_schema"
            in (getattr(registry.get_tool(name).metadata, "extra", None) or {})
        }
        assert "compute-calculate_area" in published
        assert "compute-calculate_zonal_mean" in published

    @needs_schema_adapter
    def test_schema_survives_the_route_table(self):
        from toolregistry_server.route_table import RouteTable

        table = RouteTable(make_registry(profile="core"))
        route = table.get_route("analyze_dataset")
        assert route.output_schema is not None
        assert "result_type" in route.output_schema["properties"]

    @needs_schema_adapter
    def test_tools_without_a_declared_shape_stay_silent(self):
        # Advertising a shape we have not committed to is worse than none.
        from toolregistry_server.route_table import RouteTable

        table = RouteTable(make_registry(profile="core"))
        assert table.get_route("get_capabilities").output_schema is None


class TestResourceLinks:
    def test_link_carries_uri_and_name_only_when_unspecified(self):
        link = make_resource_link("file:///tmp/a.png", "a.png")
        assert link == {"uri": "file:///tmp/a.png", "name": "a.png"}

    def test_optional_members_are_included_when_given(self):
        link = make_resource_link(
            "file:///tmp/a.png", "a.png", mime_type="image/png", size=10
        )
        assert link["mime_type"] == "image/png"
        assert link["size"] == 10

    def test_attach_accumulates(self):
        result: dict = {}
        attach_resource_link(result, make_resource_link("file:///a", "a"))
        attach_resource_link(result, make_resource_link("file:///b", "b"))
        assert [x["name"] for x in result["_resource_links"]] == ["a", "b"]

    def test_threshold_is_a_boundary_not_a_range(self):
        assert not should_link_rather_than_inline(INLINE_PAYLOAD_LIMIT_BYTES - 1)
        assert should_link_rather_than_inline(INLINE_PAYLOAD_LIMIT_BYTES)

    def test_small_png_stays_inline(self):
        assert spill_png(b"x" * 1024, plot_type="mesh") is None

    def test_large_png_is_written_and_linked(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path))
        payload = b"x" * (INLINE_PAYLOAD_LIMIT_BYTES + 1)
        link = spill_png(payload, plot_type="mesh")
        assert link is not None
        assert link["mime_type"] == "image/png"
        assert link["size"] == len(payload)
        assert link["uri"].startswith("file://")
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        written = url2pathname(urlparse(link["uri"]).path)
        with open(written, "rb") as handle:
            assert handle.read() == payload

    def test_spill_degrades_to_inline_when_store_unwritable(self, monkeypatch):
        # Failing to spill must never fail the call: inlining is still correct.
        from uxarray_mcp import state

        monkeypatch.setattr(
            state, "_artifacts_dir", lambda: (_ for _ in ()).throw(OSError("read-only"))
        )
        assert spill_png(b"x" * (INLINE_PAYLOAD_LIMIT_BYTES + 1), plot_type="m") is None


class TestListToolsCacheHints:
    def test_server_builds_with_cache_hints(self):
        assert make_mcp_server(profile="core") is not None

    def test_ttl_is_bounded_and_scope_is_shared(self):
        # The surface is fixed by the profile at startup, so a shared entry
        # is correct; the TTL bounds staleness if that ever changes.
        assert 0 < LIST_TOOLS_TTL_MS <= 600_000
        assert LIST_TOOLS_CACHE_SCOPE in {"public", "private"}
