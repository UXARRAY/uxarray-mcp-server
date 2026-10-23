"""What a client actually receives, asserted on the wire.

The rest of the suite calls tool functions directly. That proves the analysis
is right; it proves nothing about the protocol surface in front of it. These
tests run the real server through ``tests/mcp_harness.connect`` and assert on
``model_dump(by_alias=True)`` output, so a break in serialisation, schema
validity, capability advertisement or error mapping fails here rather than in
somebody's client.

Several tests below are written as characterisations: they pin behaviour that
is currently wrong, with the assertion stated as what a client sees today and
a comment naming what it should be. That is deliberate. A test asserting the
fixed behaviour would be red on main and tell us nothing new; a test asserting
today's behaviour turns red the moment someone fixes it, which is when we want
to revisit the surrounding claims.
"""

from __future__ import annotations

import json

import pytest
from mcp_harness import connect, wire

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    # asyncio only. The server has no trio-specific code and running both
    # backends would double the cost of every test here for no new coverage.
    return "asyncio"


class TestTheHandshake:
    async def test_a_client_can_initialize_and_gets_our_identity(self):
        async with connect() as (_session, init):
            payload = wire(init)

            assert payload["serverInfo"]["name"] == "UXarray MCP"
            assert payload["protocolVersion"]

    async def test_the_advertised_version_is_our_release(self):
        """Clients are told which release they are talking to.

        This was empty for every client until ``_stamp_version``: the SDK
        ``Server`` defaults ``version`` to ``""`` and neither upstream
        constructor forwards our ``ServerIdentity``. An empty version breaks
        the ordinary way a bug report establishes what was running, which is
        the first thing anyone asks.
        """
        from uxarray_mcp import __version__

        async with connect() as (_session, init):
            advertised = wire(init)["serverInfo"]["version"]

        assert advertised == __version__ != ""

    async def test_we_advertise_the_capabilities_we_implement(self):
        async with connect() as (_session, init):
            caps = wire(init)["capabilities"]

        # Tools and resources are both served: resources back the
        # ``resource_link`` returned for large figures, which is only honest
        # if ``resources/read`` answers.
        assert "tools" in caps
        assert "resources" in caps
        assert caps["tools"].get("listChanged") is True


class TestTheToolList:
    async def test_every_tool_survives_serialisation(self):
        """A tool whose schema cannot be built never reaches the client.

        ``list_tools`` going through the SDK is what proves each entry is a
        valid ``Tool``: a bad annotation or an unserialisable default would
        raise here, not at import time.
        """
        async with connect() as (session, _init):
            result = await session.list_tools()

        assert result.tools, "the core profile must expose at least one tool"
        for tool in result.tools:
            payload = wire(tool)
            assert payload["name"]
            assert payload["description"], f"{payload['name']} has no description"
            assert payload["inputSchema"]["type"] == "object"

    async def test_tool_names_are_unique(self):
        async with connect() as (session, _init):
            names = [t.name for t in (await session.list_tools()).tools]

        assert len(names) == len(set(names)), "duplicate tool names on the wire"

    async def test_every_input_schema_is_valid_json_schema(self):
        """Clients validate arguments against these before calling.

        A schema the client's validator rejects makes the tool uncallable
        from that client while our own tests, which never build one, stay
        green.
        """
        jsonschema = pytest.importorskip("jsonschema")

        async with connect() as (session, _init):
            tools = (await session.list_tools()).tools

        validator_for = jsonschema.validators.validator_for
        for tool in tools:
            schema = wire(tool)["inputSchema"]
            cls = validator_for(schema)
            cls.check_schema(schema)

    async def test_schemas_are_json_round_trippable(self):
        """stdio frames are JSON, so anything unencodable breaks the call."""
        async with connect() as (session, _init):
            tools = (await session.list_tools()).tools

        for tool in tools:
            encoded = json.dumps(wire(tool))
            assert json.loads(encoded)["name"] == tool.name


class TestToolAnnotations:
    """``readOnlyHint`` and friends, as a client receives them.

    These are what a client uses to decide what to auto-approve. A wrong hint
    is worse than none -- a tool marked read-only that writes gets approved
    silently -- so the assertions below check both that the hints arrive and
    that the risky tools are *not* claiming to be safe.
    """

    async def test_a_pure_query_is_marked_read_only(self):
        async with connect() as (session, _init):
            tools = {t.name: t for t in (await session.list_tools()).tools}

        hints = wire(tools["get_capabilities"])["annotations"]
        assert hints["readOnlyHint"] is True
        assert hints["destructiveHint"] is False
        assert hints["idempotentHint"] is True

    async def test_transfer_is_marked_destructive_and_open_world(self, monkeypatch):
        """Uploading lands a file on another machine, over whatever is there.

        The transfer tools register only when an endpoint declares a
        ``globus_transfer`` block, and they are deferred rather than listed,
        so this asserts on the annotation the registry would publish for them
        rather than on a ``tools/list`` entry that will not be there.
        ``tests/test_tool_annotations.py`` covers the map directly.
        """
        from uxarray_mcp.annotations import annotations_for

        monkeypatch.setattr(
            "uxarray_mcp.registry._transfers_are_configured", lambda: True
        )

        hints = annotations_for("transfer-transfer_put")
        assert hints is not None
        assert hints["destructiveHint"] is True
        assert hints["readOnlyHint"] is False
        assert hints["openWorldHint"] is True

    async def test_no_tool_that_writes_claims_to_be_read_only(self):
        """The failure mode that matters: a false safe-to-run claim.

        Checked against the names rather than the annotation map so that a
        tool added to ``_READ_ONLY`` by mistake is caught here rather than by
        a user whose client auto-approved it.
        """
        writes = ("transfer_put", "transfer_get", "export_to", "write_result")

        async with connect(profile="deferred-full") as (session, _init):
            tools = (await session.list_tools()).tools

        for tool in tools:
            if not any(marker in tool.name for marker in writes):
                continue
            hints = wire(tool).get("annotations") or {}
            assert hints.get("readOnlyHint") is not True, (
                f"{tool.name} is advertised read-only but its name says it "
                "writes; a client will auto-approve it"
            )

    async def test_unclassified_tools_carry_no_annotation_at_all(self):
        """Absence is the honest answer for anything not deliberately rated.

        An empty ``annotations`` object would read as "classified, no hints
        apply", which is a different and stronger claim.
        """
        from uxarray_mcp.annotations import annotations_for

        async with connect() as (session, _init):
            tools = (await session.list_tools()).tools

        for tool in tools:
            if annotations_for(tool.name) is None:
                assert tool.annotations is None, (
                    f"{tool.name} is unclassified but carries annotations"
                )


class TestOutputSchemaCoverage:
    """``outputSchema`` lets a client parse a result instead of scraping text.

    Five operations declare one (``run_analysis`` plus the four contracts in
    ``typed_results``), and the registry does attach all five -- checked
    below on the route table. Only ``run_analysis`` reaches ``tools/list``
    because the other four are deferred: they are reached through
    ``call_deferred`` rather than listed, so a client never sees their
    schema during tool selection.

    That is a real gap, but it is a property of the deferral design rather
    than of the schema plumbing, and widening it means deciding which tools
    are worth their place in the context window. Pinned here so the decision
    is visible rather than implicit.
    """

    async def test_the_listed_tool_with_a_contract_publishes_its_schema(self):
        async with connect() as (session, _init):
            tools = {t.name: t for t in (await session.list_tools()).tools}

        schema = wire(tools["run_analysis"])["outputSchema"]
        assert schema["type"] == "object"
        assert schema["properties"], "an empty schema promises nothing"

    async def test_deferred_contract_tools_still_carry_their_schema(self):
        """The plumbing works; the tools are simply not listed.

        Asserted on the route table rather than the wire, because that is
        where the schema is attached and the point is to show it is not lost
        before deferral hides the tool.
        """
        from toolregistry_server.route_table import RouteTable

        from uxarray_mcp.app import make_registry

        routes = {
            r.tool_name: r
            for r in RouteTable(make_registry(profile="deferred-full")).list_routes()
        }
        for name in (
            "inspect-inspect_mesh",
            "inspect-validate_dataset",
            "compute-calculate_area",
            "compute-calculate_zonal_mean",
        ):
            assert routes[name].output_schema is not None, (
                f"{name} declares a response contract but carries no schema"
            )


class TestCallingTools:
    async def test_a_bad_argument_is_a_tool_error_not_a_crash(self):
        """Validation failures must come back as ``isError``, not an exception.

        A protocol-level exception kills the session; a tool error is
        something the model can read and correct. The distinction is invisible
        to a direct function call, which raises either way.
        """
        async with connect() as (session, _init):
            result = await session.call_tool("get_capabilities", {})

        payload = wire(result)
        assert payload["isError"] is True
        assert payload["content"], "an error must carry a message for the model"

    async def test_the_error_text_names_what_was_missing(self):
        async with connect() as (session, _init):
            result = await session.call_tool("get_capabilities", {})

        text = " ".join(
            block.get("text", "") for block in wire(result).get("content", [])
        )
        assert "grid_path" in text, f"unhelpful validation error: {text!r}"

    async def test_a_missing_file_is_reported_as_a_tool_error(self):
        """The common first-run failure: a path that is not there.

        It must arrive as a readable tool error rather than a traceback, since
        this is the single most likely thing to happen to a new user.
        """
        async with connect() as (session, _init):
            result = await session.call_tool(
                "get_capabilities", {"grid_path": "/nonexistent/mesh.nc"}
            )

        payload = wire(result)
        assert payload["isError"] is True
        text = " ".join(b.get("text", "") for b in payload["content"])
        assert "not found" in text.lower() or "no such file" in text.lower()

    async def test_calling_an_unknown_tool_is_handled(self):
        """A name that does not exist is a protocol error, not a result.

        toolregistry-server 0.7.0 changed this: it used to come back as a
        ``CallToolResult`` with ``isError``, and now raises JSON-RPC
        ``-32602`` (invalid params). The new behaviour is the correct one
        -- ``isError`` is for a tool that ran and failed, while an unknown
        name means nothing ran -- so this asserts the new contract rather
        than pinning the old one.
        """
        from mcp.shared.exceptions import MCPError

        async with connect() as (session, _init):
            with pytest.raises(MCPError) as err:
                await session.call_tool("no_such_tool_exists", {})

        assert "no_such_tool_exists" in str(err.value)


class TestResources:
    async def test_listing_resources_works_over_the_wire(self):
        """``resource_link`` results are only honest if this answers."""
        async with connect() as (session, _init):
            result = await session.list_resources()

        # May legitimately be empty with no artifacts written yet; what
        # matters is that the method is implemented and returns the right
        # shape rather than erroring.
        assert "resources" in wire(result)
