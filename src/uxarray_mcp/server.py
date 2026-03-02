"""UXarray MCP Server - Provides mesh analysis tools for AI agents."""

from fastmcp import FastMCP
from uxarray_mcp.tools import (
    inspect_mesh,
    inspect_variable,
    calculate_area,
    calculate_zonal_mean,
    validate_dataset,
    calculate_area_hpc,
    inspect_variable_hpc,
    calculate_zonal_mean_hpc,
)

# Initialize the MCP server
mcp = FastMCP("uxarray-mcp-server")

# Register local tools
mcp.tool()(inspect_mesh)
mcp.tool()(inspect_variable)
mcp.tool()(calculate_area)
mcp.tool()(calculate_zonal_mean)
mcp.tool()(validate_dataset)

# Register HPC-capable tools
mcp.tool()(calculate_area_hpc)
mcp.tool()(inspect_variable_hpc)
mcp.tool()(calculate_zonal_mean_hpc)

if __name__ == "__main__":
    mcp.run()
