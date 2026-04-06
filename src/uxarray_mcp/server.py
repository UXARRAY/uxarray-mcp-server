"""UXarray MCP Server - Provides mesh analysis tools for AI agents."""

from fastmcp import FastMCP

from uxarray_mcp.remote.config import load_config
from uxarray_mcp.tools import (
    calculate_area,
    calculate_area_hpc,
    calculate_zonal_mean,
    calculate_zonal_mean_hpc,
    get_capabilities,
    get_execution_mode,
    inspect_mesh,
    inspect_mesh_hpc,
    inspect_variable,
    inspect_variable_hpc,
    plot_mesh,
    plot_variable,
    plot_zonal_mean,
    run_scientific_agent,
    set_execution_mode,
    validate_dataset,
)

# Initialize the MCP server
mcp = FastMCP("uxarray-mcp-server")

# Tool discovery — always call this first with a new dataset
mcp.tool()(get_capabilities)

# Autonomous scientific agent — Analyze → Plan → Execute → Verify
mcp.tool()(run_scientific_agent)

# Core local tools — always registered
mcp.tool()(inspect_mesh)
mcp.tool()(inspect_variable)
mcp.tool()(calculate_area)
mcp.tool()(calculate_zonal_mean)
mcp.tool()(validate_dataset)

# Visualization tools — always registered
mcp.tool()(plot_mesh)
mcp.tool()(plot_variable)
mcp.tool()(plot_zonal_mean)

# Execution mode control — always registered so users can switch modes
mcp.tool()(get_execution_mode)
mcp.tool()(set_execution_mode)

# HPC tools — only register when an endpoint is configured
if load_config().has_endpoint:
    mcp.tool()(inspect_mesh_hpc)
    mcp.tool()(calculate_area_hpc)
    mcp.tool()(inspect_variable_hpc)
    mcp.tool()(calculate_zonal_mean_hpc)

if __name__ == "__main__":
    mcp.run()
