"""The annotation map itself, independent of what any profile exposes.

``tests/test_mcp_protocol.py`` checks the hints that reach a client. Most
tools never do: ``deferred-full`` publishes 35 of its 72 and reaches the rest
through ``call_deferred``, so the transfer and export tools -- the ones whose
classification matters most -- are invisible to a wire test.

These tests hold the map to its own rules directly, so a wrong entry is
caught whether or not a profile happens to advertise that tool today.
"""

from __future__ import annotations

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
    monkeypatch.setattr(
        "uxarray_mcp.registry._transfers_are_configured", lambda: True
    )


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
                for marker in ("transfer_put", "transfer_get", "export_to", "write_result")
            ):
                continue
            hints = annotations_for(name) or {}
            assert hints.get("readOnlyHint") is not True, f"{name} claims read-only"
