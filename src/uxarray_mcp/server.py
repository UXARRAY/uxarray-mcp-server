"""UXarray MCP Server - Provides mesh analysis tools for AI agents."""

from fastmcp import FastMCP
from uxarray_mcp.tools import (
    inspect_mesh,
    inspect_variable,
    calculate_area,
    calculate_zonal_mean,
)

# Initialize the MCP server
mcp = FastMCP("uxarray-mcp-server")

# Register tools
mcp.tool()(inspect_mesh)
mcp.tool()(inspect_variable)
mcp.tool()(calculate_area)
mcp.tool()(calculate_zonal_mean)

if __name__ == "__main__":
    mcp.run()
