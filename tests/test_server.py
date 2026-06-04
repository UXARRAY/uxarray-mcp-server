import inspect

import pytest

from uxarray_mcp.server import mcp


async def _registered_tools():
    """Return registered tools as a {name: Tool} dict across FastMCP versions."""
    if hasattr(mcp, "get_tools"):
        return await mcp.get_tools()
    tools = await mcp.list_tools()
    return {tool.name: tool for tool in tools}


@pytest.mark.asyncio
async def test_public_tool_surface_is_small_and_intent_shaped():
    """Verify the MCP server exposes front doors, not every implementation tool."""
    tools = await _registered_tools()

    expected_tools = {
        "get_capabilities",
        "analyze_dataset",
        "run_analysis",
        "plot_dataset",
        "diagnose_endpoint",
        "probe_path_access",
        "run_workflow",
        "resume_workflow",
        "get_status",
        "get_result",
        "manage_session",
    }
    assert set(tools.keys()) == expected_tools
    assert len(tools) <= 12


@pytest.mark.asyncio
async def test_no_hpc_suffixed_tool_names():
    """The MCP surface should not expose ``*_hpc`` duplicates anymore."""
    tools = await _registered_tools()
    suffixed = [name for name in tools if name.endswith("_hpc")]
    assert suffixed == [], f"Unexpected _hpc-suffixed tools: {suffixed}"


@pytest.mark.asyncio
async def test_low_level_implementation_tools_are_not_registered():
    """The MCP surface should not expose low-level implementation verbs."""
    tools = await _registered_tools()
    hidden = {
        "inspect_mesh",
        "inspect_variable",
        "calculate_area",
        "calculate_zonal_mean",
        "plot_mesh",
        "plot_variable",
        "plot_zonal_mean",
        "calculate_gradient",
        "calculate_curl",
        "calculate_divergence",
        "calculate_azimuthal_mean",
        "endpoint_status",
        "validate_hpc_setup",
    }
    assert hidden.isdisjoint(tools)


@pytest.mark.asyncio
async def test_front_door_dispatch_tools_accept_remote_kwargs():
    """Remote execution remains available through the intent-shaped tools."""
    tools = await _registered_tools()
    for name in ("analyze_dataset", "run_analysis", "plot_dataset"):
        tool = tools[name]
        sig = inspect.signature(tool.fn)
        assert "use_remote" in sig.parameters, name
        assert "endpoint" in sig.parameters, name
        assert "session_id" in sig.parameters, name
