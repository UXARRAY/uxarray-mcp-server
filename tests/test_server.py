"""Verify the toolregistry-based server builds correctly.

These tests replace the previous FastMCP-based assertions. They
exercise ``uxarray_mcp.registry.build_registry`` and
``uxarray_mcp.app.make_registry`` to confirm the tool surface
matches the agreed design spec.
"""

from __future__ import annotations

import inspect
import json

import pytest

from uxarray_mcp.app import make_mcp_server, make_registry
from uxarray_mcp.registry import (
    _CONTROL_TOOLS,
    _CORE_EXTRA_TOOLS,
    _DEFERRED_TOOLS,
    _PROMPT_TOOLS,
    FRONTDOOR_NAMES,
    build_registry,
)

EXPECTED_FRONTDOOR = 11
EXPECTED_CONTROL = 12  # 8 session + 4 hpc
EXPECTED_CORE_EXTRA = 1  # list_datasets
EXPECTED_PROMPTS = 3  # first_look, vorticity_analysis, hpc_diagnose
EXPECTED_DEFERRED = 30


# ---------------------------------------------------------------------------
# Coverage invariants
# ---------------------------------------------------------------------------


def test_frontdoor_count():
    assert len(FRONTDOOR_NAMES) == EXPECTED_FRONTDOOR


def test_control_count():
    total = sum(len(v) for v in _CONTROL_TOOLS.values())
    assert total == EXPECTED_CONTROL


def test_prompt_count():
    total = sum(len(v) for v in _PROMPT_TOOLS.values())
    assert total == EXPECTED_PROMPTS


def test_namespace_plan_covers_every_public_tool():
    """Every public tool is reachable through one of the buckets."""
    import uxarray_mcp.tools as tools_mod

    control = {n for v in _CONTROL_TOOLS.values() for n in v}
    core_extra = {n for v in _CORE_EXTRA_TOOLS.values() for n in v}
    deferred = {n for v in _DEFERRED_TOOLS.values() for n in v}

    covered = FRONTDOOR_NAMES | control | core_extra | deferred
    missing = set(tools_mod.__all__) - covered
    assert not missing, f"uncovered public tools: {sorted(missing)}"


def test_buckets_are_disjoint():
    """A tool must not appear in two buckets."""
    control = {n for v in _CONTROL_TOOLS.values() for n in v}
    core_extra = {n for v in _CORE_EXTRA_TOOLS.values() for n in v}
    deferred = {n for v in _DEFERRED_TOOLS.values() for n in v}

    overlap = (
        (FRONTDOOR_NAMES & control)
        | (FRONTDOOR_NAMES & core_extra)
        | (FRONTDOOR_NAMES & deferred)
        | (control & core_extra)
        | (control & deferred)
        | (core_extra & deferred)
    )
    assert not overlap, f"overlapping tools: {sorted(overlap)}"


# ---------------------------------------------------------------------------
# Profile shape
# ---------------------------------------------------------------------------


def test_core_profile_shape():
    registry = make_registry(profile="core")
    status = registry.get_tools_status()
    enabled = [s for s in status if s["enabled"] and not s["defer"]]
    deferred = [s for s in status if s["enabled"] and s["defer"]]

    expected = (
        EXPECTED_FRONTDOOR + EXPECTED_CONTROL + EXPECTED_CORE_EXTRA + EXPECTED_PROMPTS
    )
    assert len(enabled) == expected, (
        f"expected {expected} enabled, got {len(enabled)}: "
        f"{sorted(s['name'] for s in enabled)}"
    )
    assert deferred == []
    assert "discover_tools" not in registry.list_tools()


def test_deferred_full_profile_shape():
    registry = build_registry(profile="deferred-full")
    status = registry.get_tools_status()
    enabled_visible = [s for s in status if s["enabled"] and not s["defer"]]
    enabled_deferred = [s for s in status if s["enabled"] and s["defer"]]

    expected_visible = (
        EXPECTED_FRONTDOOR
        + EXPECTED_CONTROL
        + EXPECTED_CORE_EXTRA
        + EXPECTED_PROMPTS
        + 1  # discover_tools
    )
    assert len(enabled_visible) == expected_visible
    assert len(enabled_deferred) == EXPECTED_DEFERRED
    assert "discover_tools" in registry.list_tools()


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        build_registry(profile="bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Front-door surface — backward compat checks
# ---------------------------------------------------------------------------


def test_public_tool_surface_includes_gateway_tools():
    """All 11 original gateway tools are present at the top level."""
    registry = make_registry(profile="core")
    tools = registry.list_tools()
    for name in FRONTDOOR_NAMES:
        assert name in tools, f"gateway tool {name!r} missing from core"


def test_no_hpc_suffixed_tool_names():
    """The tool surface should not expose ``*_hpc`` duplicates."""
    registry = make_registry(profile="core")
    suffixed = [n for n in registry.list_tools() if n.endswith("_hpc")]
    assert suffixed == [], f"Unexpected _hpc-suffixed tools: {suffixed}"


def test_low_level_implementation_tools_hidden_in_core():
    """Implementation verbs are not directly visible in core profile."""
    registry = make_registry(profile="core")
    tools = set(registry.list_tools())
    hidden = {
        "inspect_mesh",
        "calculate_area",
        "calculate_curl",
        "plot_mesh",
        "plot_variable",
    }
    assert hidden.isdisjoint(tools), f"leaked: {hidden & tools}"


def test_front_door_dispatch_tools_accept_remote_kwargs():
    """Remote execution is available through the intent-shaped tools."""
    registry = make_registry(profile="core")
    for name in ("analyze_dataset", "run_analysis", "plot_dataset"):
        tool = registry.get_tool(name)
        assert tool is not None, name
        sig = inspect.signature(tool.callable)
        assert "use_remote" in sig.parameters, name
        assert "endpoint" in sig.parameters, name
        assert "session_id" in sig.parameters, name


# ---------------------------------------------------------------------------
# Prompt-as-tool
# ---------------------------------------------------------------------------


def test_prompt_tools_registered_in_core():
    """Former @mcp.prompt() decorators are now prompt/ namespace tools."""
    registry = make_registry(profile="core")
    tools = registry.list_tools()
    sep = registry._name_sep
    for name in ("first_look", "vorticity_analysis", "hpc_diagnose"):
        assert f"prompt{sep}{name}" in tools, f"prompt tool {name} missing"


def test_prompt_tool_returns_text():
    """Prompt tools return instruction text, not analysis results."""
    registry = make_registry(profile="core")
    sep = registry._name_sep
    result = registry.execute_tool_calls(
        [
            {
                "id": "call_1",
                "function": {
                    "name": f"prompt{sep}first_look",
                    "arguments": json.dumps({"path": "/tmp/test.nc"}),
                },
            }
        ]
    )
    text = result["call_1"]
    assert "first-look analysis" in text.lower()
    assert "/tmp/test.nc" in text


# ---------------------------------------------------------------------------
# Policy tags
# ---------------------------------------------------------------------------


def test_set_execution_mode_is_file_system():
    from toolregistry.tool import ToolTag

    registry = build_registry(profile="core")
    sep = registry._name_sep
    tool = registry.get_tool(f"hpc{sep}set_execution_mode")
    assert tool is not None
    assert ToolTag.FILE_SYSTEM.value in tool.metadata.all_tags


def test_session_tools_are_file_system():
    from toolregistry.tool import ToolTag

    registry = build_registry(profile="core")
    sep = registry._name_sep
    # Session tools persist/read records on disk, so they must carry
    # FILE_SYSTEM in addition to stateful / read-only.
    for name in (
        "create_session",
        "register_dataset",
        "reset_session_state",
        "get_session_state",
        "get_result_handle",
        "get_operation_status",
        "list_operations",
        "get_workflow_status",
    ):
        tool = registry.get_tool(f"session{sep}{name}")
        assert tool is not None, name
        assert ToolTag.FILE_SYSTEM.value in tool.metadata.all_tags, name


def test_get_execution_mode_is_file_system_and_network():
    from toolregistry.tool import ToolTag

    registry = build_registry(profile="core")
    sep = registry._name_sep
    # Reads config from disk and queries the Globus Compute endpoint when one
    # is configured, so it touches both the filesystem and the network.
    tool = registry.get_tool(f"hpc{sep}get_execution_mode")
    assert tool is not None
    assert ToolTag.FILE_SYSTEM.value in tool.metadata.all_tags
    assert ToolTag.NETWORK.value in tool.metadata.all_tags


def test_scientific_agent_is_experimental_and_deferred():
    registry = build_registry(profile="deferred-full")
    sep = registry._name_sep
    tool = registry.get_tool(f"agent{sep}run_scientific_agent")
    assert tool is not None
    assert "experimental" in tool.metadata.custom_tags
    assert tool.metadata.defer is True


# ---------------------------------------------------------------------------
# Live call
# ---------------------------------------------------------------------------


def test_live_call_through_registry():
    """Side-effect-free tool round-trips through the registry."""
    registry = make_registry(profile="core")
    sep = registry._name_sep
    result = registry.execute_tool_calls(
        [
            {
                "id": "call_1",
                "function": {
                    "name": f"hpc{sep}get_execution_mode",
                    "arguments": "{}",
                },
            }
        ]
    )
    payload = json.loads(result["call_1"])
    assert "_provenance" in payload
    assert payload["_provenance"]["tool"] == "get_execution_mode"
    assert payload["mode"] in {"local", "auto", "remote"}


# ---------------------------------------------------------------------------
# MCP server construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_server_constructs():
    """make_mcp_server() returns a working MCP Server object."""
    server = make_mcp_server(profile="core")
    assert server.name == "UXarray MCP"
