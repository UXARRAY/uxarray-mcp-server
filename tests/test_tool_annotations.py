"""The annotation map itself, independent of what any profile exposes.

``tests/test_mcp_protocol.py`` checks the hints that reach a client. Most
tools never do: ``deferred-full`` publishes 35 of its 72 and reaches the rest
through ``call_deferred``, so the transfer and export tools -- the ones whose
classification matters most -- are invisible to a wire test.

These tests hold the map to its own rules directly, so a wrong entry is
caught whether or not a profile happens to advertise that tool today.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from uxarray_mcp.annotations import (
    _DESTRUCTIVE,
    _OPEN_WORLD,
    _READ_ONLY,
    annotations_for,
)
from uxarray_mcp.app import make_registry


class TestTheRulesHoldInternally:
    def test_nothing_is_both_read_only_and_destructive(self):
        assert _READ_ONLY & _DESTRUCTIVE == frozenset()

    def test_read_only_implies_non_destructive_and_idempotent(self):
        for name in sorted(_READ_ONLY):
            hints = annotations_for(name)
            assert hints is not None
            assert hints["readOnlyHint"] is True
            assert hints["destructiveHint"] is False
            assert hints["idempotentHint"] is True

    def test_destructive_tools_never_claim_read_only(self):
        for name in sorted(_DESTRUCTIVE):
            hints = annotations_for(name)
            assert hints is not None
            assert hints["destructiveHint"] is True
            assert hints["readOnlyHint"] is False

    def test_an_unclassified_tool_gets_nothing(self):
        """``None``, not ``{}``: absence and "no hints apply" differ."""
        assert annotations_for("a_tool_that_does_not_exist") is None

    def test_open_world_alone_still_produces_hints(self):
        """A remote tool that is neither read-only nor destructive.

        ``hpc-check_remote_yac`` probes a cluster: it writes nothing the user
        owns, but its answer depends on a machine we cannot see.
        """
        hints = annotations_for("hpc-check_remote_yac")
        assert hints == {"openWorldHint": True}


@pytest.fixture
def with_transfers(monkeypatch):
    """Register the conditional transfer tools.

    They appear only when an endpoint declares a ``globus_transfer`` block,
    which is a property of whoever runs the tests rather than of the code --
    and the suite's autouse offline config deliberately declares none. Their
    classification is exactly what these tests exist to check, so force them
    on the same way ``test_transfer_tools.py`` does.
    """
    monkeypatch.setattr("uxarray_mcp.registry._transfers_are_configured", lambda: True)


class TestTheMapMatchesTheRealToolSurface:
    """A name that no longer exists annotates nothing, silently.

    Tools get renamed. An entry left behind in the map is dead weight that
    still reads as a deliberate safety claim, so it is worth failing on.
    """

    @pytest.fixture
    def known_tools(self, with_transfers) -> frozenset[str]:
        return frozenset(make_registry(profile="deferred-full").list_tools())

    @pytest.mark.parametrize("group", ["read_only", "destructive", "open_world"])
    def test_every_entry_names_a_tool_that_exists(self, group, known_tools):
        mapping = {
            "read_only": _READ_ONLY,
            "destructive": _DESTRUCTIVE,
            "open_world": _OPEN_WORLD,
        }[group]
        unknown = sorted(name for name in mapping if name not in known_tools)
        assert unknown == [], (
            f"{group} names tools that no longer exist: {unknown}. "
            "Rename or remove them; a stale entry annotates nothing."
        )

    def test_the_transfer_tools_are_all_classified(self, with_transfers):
        """These move data between machines; none may go out unclassified."""
        transfer = sorted(
            t
            for t in make_registry(profile="deferred-full").list_tools()
            if t.startswith("transfer-")
        )
        assert transfer, "expected the transfer tools in deferred-full"
        for name in transfer:
            assert annotations_for(name) is not None, f"{name} is unclassified"

    def test_writing_tools_are_destructive_not_read_only(self, with_transfers):
        """Anything whose name says it writes must not be advertised safe."""
        for name in make_registry(profile="deferred-full").list_tools():
            if not any(
                marker in name
                for marker in (
                    "transfer_put",
                    "transfer_get",
                    "export_to",
                    "write_result",
                )
            ):
                continue
            hints = annotations_for(name) or {}
            assert hints.get("readOnlyHint") is not True, f"{name} claims read-only"


class TestTheShimFindsTheHandlerOnEitherSDK:
    """``apply_tool_annotations`` must locate ``tools/list`` on mcp 1.x too.

    mcp 2.x keys ``_request_handlers`` by method string; mcp 1.x, our declared
    floor, keys it by request type. The shim looked up only the string, so on
    the floor it found nothing and returned the server untouched -- every tool
    went out unannotated, and the hints a client uses to decide what to
    auto-approve were missing precisely where we document them as present.

    These use a stand-in server rather than a real one so both keying schemes
    are exercised whichever SDK is installed; the weekly floor job is the only
    place the type-keyed branch is otherwise reachable.
    """

    @staticmethod
    def _fake_result():
        from mcp.types import ListToolsResult, Tool

        return ListToolsResult(
            tools=[Tool(name="get_capabilities", inputSchema={"type": "object"})]
        )

    class _Server:
        def __init__(self, handlers):
            self._request_handlers = handlers

    async def _annotated_names(self, key, *, envelope=False):
        from uxarray_mcp.annotations import apply_tool_annotations

        result = self._fake_result()
        if envelope:
            # A stand-in for mcp 1.x's ``ServerResult``, which is a RootModel
            # wrapping the real result. On mcp 2.x ``ServerResult`` is a bare
            # union and cannot be constructed, so building the shape by hand
            # keeps this case exercised on whichever SDK is installed.
            result = SimpleNamespace(root=result)

        async def handler(*_args, **_kwargs):
            return result

        handlers = {key: handler}
        apply_tool_annotations(self._Server(handlers))
        assert handlers[key] is not handler, "the handler was never wrapped"
        out = await handlers[key]()
        payload = getattr(out, "root", out)
        # By alias, because ``readOnlyHint`` is what goes out on the wire;
        # the Python attribute is snake_case on one SDK and camelCase on the
        # other, and the client only ever sees the former.
        return payload.tools[0].annotations.model_dump(by_alias=True, exclude_none=True)

    async def test_a_string_keyed_handler_is_wrapped(self):
        """mcp 2.x."""
        assert (await self._annotated_names("tools/list"))["readOnlyHint"] is True

    async def test_a_type_keyed_handler_is_wrapped(self):
        """mcp 1.x, the declared floor."""
        from mcp.types import ListToolsRequest

        hints = await self._annotated_names(ListToolsRequest)
        assert hints["readOnlyHint"] is True

    async def test_a_result_wrapped_in_a_server_envelope_is_annotated(self):
        """mcp 1.x returns ``ServerResult``, whose ``.root`` holds the tools.

        Without unwrapping it, the shim found the handler, wrapped it, and
        then iterated an empty ``.tools`` -- so every tool still went out
        unannotated and the wrapping looked like it had worked.
        """
        from mcp.types import ListToolsRequest

        hints = await self._annotated_names(ListToolsRequest, envelope=True)
        assert hints["readOnlyHint"] is True
