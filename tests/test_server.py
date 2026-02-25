import pytest
from uxarray_mcp.server import mcp


@pytest.mark.asyncio
async def test_inspect_mesh_tool_registered():
    """Verify all expected tools are registered with the MCP server."""
    # List tools to get their metadata
    tools = await mcp.get_tools()

    expected_tools = {
        "inspect_mesh",
        "inspect_variable",
        "calculate_area",
        "calculate_zonal_mean",
        "calculate_area_hpc",
        "inspect_variable_hpc",
        "calculate_zonal_mean_hpc",
    }
    assert expected_tools.issubset(set(tools.keys()))
