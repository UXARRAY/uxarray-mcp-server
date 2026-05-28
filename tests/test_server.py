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
async def test_inspect_mesh_tool_registered():
    """Verify all expected tools are registered with the MCP server."""
    tools = await _registered_tools()

    expected_tools = {
        "get_capabilities",
        "list_datasets",
        "run_scientific_agent",
        "run_workflow",
        "resume_workflow",
        "get_workflow_status",
        "create_session",
        "register_dataset",
        "get_session_state",
        "reset_session_state",
        "get_result_handle",
        "get_operation_status",
        "list_operations",
        "inspect_mesh",
        "inspect_variable",
        "calculate_area",
        "calculate_zonal_mean",
        "validate_dataset",
        "plot_mesh",
        "plot_variable",
        "plot_zonal_mean",
        "subset_bbox",
        "subset_polygon",
        "extract_cross_section",
        "compare_fields",
        "calculate_bias",
        "calculate_rmse",
        "calculate_pattern_correlation",
        "remap_variable",
        "regrid_dataset",
        "calculate_temporal_mean",
        "calculate_anomaly",
        "calculate_ensemble_mean",
        "calculate_ensemble_spread",
        "export_to_netcdf",
        "export_to_csv",
        "write_result",
        "endpoint_status",
        "get_execution_mode",
        "probe_path_access",
        "set_execution_mode",
        "validate_hpc_setup",
    }
    assert expected_tools.issubset(set(tools.keys()))


@pytest.mark.asyncio
async def test_no_hpc_suffixed_tool_names():
    """The MCP surface should not expose ``*_hpc`` duplicates anymore."""
    tools = await _registered_tools()
    suffixed = [name for name in tools if name.endswith("_hpc")]
    assert suffixed == [], f"Unexpected _hpc-suffixed tools: {suffixed}"


@pytest.mark.asyncio
async def test_dispatched_tools_accept_use_remote():
    """Tools that wrap the dispatcher must expose use_remote/endpoint kwargs."""
    tools = await _registered_tools()
    dispatched = {
        "inspect_mesh",
        "inspect_variable",
        "calculate_area",
        "calculate_zonal_mean",
        "plot_mesh",
        "plot_variable",
        "plot_zonal_mean",
    }
    for name in dispatched:
        tool = tools[name]
        sig = inspect.signature(tool.fn)
        assert "use_remote" in sig.parameters, name
        assert "endpoint" in sig.parameters, name
        assert "session_id" in sig.parameters, name
