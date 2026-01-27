import pytest
from uxarray_mcp.server import mcp


@pytest.mark.asyncio
async def test_inspect_mesh_tool_registered():
    """Verify that the inspect_mesh tool is registered with the MCP server."""
    # List tools to get their metadata
    tools = await mcp.get_tools()

    assert "inspect_mesh" in tools, "inspect_mesh tool should be registered"
