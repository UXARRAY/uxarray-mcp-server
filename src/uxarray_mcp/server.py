"""UXarray MCP Server - Provides mesh analysis tools for AI agents."""

from fastmcp import FastMCP
from uxarray_mcp.tools import inspect_mesh

# Initialize the MCP server
mcp = FastMCP("uxarray-mcp-server")

# Register tools
mcp.tool()(inspect_mesh)

if __name__ == "__main__":
    mcp.run()
