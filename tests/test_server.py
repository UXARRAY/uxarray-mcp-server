import pytest
from uxarray_mcp.server import mcp
from uxarray_mcp.remote.config import load_config


@pytest.mark.asyncio
async def test_inspect_mesh_tool_registered():
    """Verify all expected tools are registered with the MCP server."""
    # List tools to get their metadata
    tools = await mcp.get_tools()

    expected_tools = {
        "get_capabilities",
        "run_scientific_agent",
        "inspect_mesh",
        "inspect_variable",
        "calculate_area",
        "calculate_zonal_mean",
        "validate_dataset",
        "get_execution_mode",
        "set_execution_mode",
    }
    assert expected_tools.issubset(set(tools.keys()))

    hpc_tools = {
        "inspect_mesh_hpc",
        "calculate_area_hpc",
        "inspect_variable_hpc",
        "calculate_zonal_mean_hpc",
    }
    if load_config().has_endpoint:
        assert hpc_tools.issubset(set(tools.keys()))
    else:
        assert hpc_tools.isdisjoint(set(tools.keys()))
