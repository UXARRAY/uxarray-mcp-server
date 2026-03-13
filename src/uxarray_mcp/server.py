"""UXarray MCP Server - Provides mesh analysis tools for AI agents."""

from fastmcp import FastMCP
from uxarray_mcp.tools import (
    get_capabilities,
    run_scientific_agent,
    inspect_mesh,
    inspect_variable,
    calculate_area,
    calculate_zonal_mean,
    calculate_area_hpc,
    inspect_variable_hpc,
    calculate_zonal_mean_hpc,
)

# Initialize the MCP server
mcp = FastMCP("uxarray-mcp-server")

# Tool discovery — always call this first with a new dataset
mcp.tool()(get_capabilities)

# Autonomous scientific agent — Analyze → Plan → Execute → Verify
mcp.tool()(run_scientific_agent)

# Register local tools
mcp.tool()(inspect_mesh)
mcp.tool()(inspect_variable)
mcp.tool()(calculate_area)
mcp.tool()(calculate_zonal_mean)

# Register HPC-capable tools
mcp.tool()(calculate_area_hpc)
mcp.tool()(inspect_variable_hpc)
mcp.tool()(calculate_zonal_mean_hpc)

if __name__ == "__main__":
    mcp.run()
