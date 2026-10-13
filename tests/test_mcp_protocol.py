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

    async def test_the_advertised_version_is_empty(self):
        """Characterises a real bug: clients are told our version is "".

        ``UXARRAY_IDENTITY.version`` is the package version, and the low-level
        SDK ``Server`` accepts ``version=``, but neither
        ``route_table_to_mcp_server`` nor ``MCPAdapter.__init__`` upstream
        takes one, so nothing ever forwards it. Every client sees an empty
        string where the release should be -- which breaks the usual way a
        bug report establishes what was running.

        Fixing it means passing the version through at construction; this
        test should then assert equality with ``uxarray_mcp.__version__``.
        """
        from uxarray_mcp import __version__

        async with connect() as (_session, init):
            advertised = wire(init)["serverInfo"]["version"]

        assert __version__, "the package itself must know its version"
        assert advertised == "", (
            "server version is no longer empty on the wire -- good. Change "
            f"this assertion to == {__version__!r} and drop the comment above."
        )

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


class TestToolAnnotationsAreMissing:
    """Characterises the absence of MCP tool annotations.

    ``ToolAnnotations`` carries ``readOnlyHint``, ``destructiveHint``,
    ``idempotentHint`` and ``openWorldHint``. They are how a client decides
    what to auto-approve and what to confirm, and large published servers set
    them widely. We set none, so a client cannot distinguish ``get_capabilities``
    from a tool that writes files or moves data between machines.
    """

    async def test_no_tool_declares_annotations(self):
        async with connect() as (session, _init):
            tools = (await session.list_tools()).tools

        annotated = [t.name for t in tools if t.annotations is not None]
        assert annotated == [], (
            "tools now carry annotations: "
            f"{annotated}. Replace this characterisation with per-tool "
            "assertions (read-only on inspection, destructive on transfer)."
        )

    async def test_read_only_tools_do_not_say_so(self):
        """The clearest instance: a pure capability query is not marked safe."""
        async with connect() as (session, _init):
            tools = {t.name: t for t in (await session.list_tools()).tools}

        probe = tools.get("get_capabilities")
        assert probe is not None
        assert probe.annotations is None


class TestOutputSchemaCoverage:
    async def test_almost_no_tool_publishes_an_output_schema(self):
        """``outputSchema`` lets a client parse results instead of scraping text.

        The machinery exists -- ``registry._apply_output_schema`` and
        ``typed_results.output_schema_for`` -- but is wired to one tool. This
        pins the current coverage so that extending it is a visible change.
        """
        async with connect() as (session, _init):
            tools = (await session.list_tools()).tools

        with_schema = sorted(t.name for t in tools if t.output_schema is not None)
        assert with_schema == ["run_analysis"], (
            f"outputSchema coverage changed: {with_schema}. If this grew on "
            "purpose, update the expectation."
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
        async with connect() as (session, _init):
            result = await session.call_tool("no_such_tool_exists", {})

        assert wire(result)["isError"] is True


class TestResources:
    async def test_listing_resources_works_over_the_wire(self):
        """``resource_link`` results are only honest if this answers."""
        async with connect() as (session, _init):
            result = await session.list_resources()

        # May legitimately be empty with no artifacts written yet; what
        # matters is that the method is implemented and returns the right
        # shape rather than erroring.
        assert "resources" in wire(result)
