"""UXarray MCP Server - Provides mesh analysis tools for AI agents."""

from fastmcp import FastMCP

from uxarray_mcp.remote.config import load_config
from uxarray_mcp.tools import (
    calculate_anomaly,
    calculate_area,
    calculate_area_hpc,
    calculate_bias,
    calculate_ensemble_mean,
    calculate_ensemble_spread,
    calculate_pattern_correlation,
    calculate_rmse,
    calculate_temporal_mean,
    calculate_zonal_mean,
    calculate_zonal_mean_hpc,
    compare_fields,
    create_session,
    export_to_csv,
    export_to_netcdf,
    extract_cross_section,
    get_capabilities,
    get_execution_mode,
    get_operation_status,
    get_result_handle,
    get_session_state,
    get_workflow_status,
    inspect_mesh,
    inspect_mesh_hpc,
    inspect_variable,
    inspect_variable_hpc,
    list_datasets,
    list_operations,
    plot_mesh,
    plot_mesh_hpc,
    plot_variable,
    plot_variable_hpc,
    plot_zonal_mean,
    plot_zonal_mean_hpc,
    probe_path_access,
    register_dataset,
    regrid_dataset,
    remap_variable,
    reset_session_state,
    resume_workflow,
    run_scientific_agent,
    run_workflow,
    set_execution_mode,
    subset_bbox,
    subset_polygon,
    validate_dataset,
    validate_hpc_setup,
    write_result,
)

# Initialize the MCP server
mcp = FastMCP("uxarray-mcp-server")

# Tool discovery — always call this first with a new dataset
mcp.tool()(get_capabilities)

# Autonomous scientific agent — Analyze → Plan → Execute → Verify
mcp.tool()(run_scientific_agent)
mcp.tool()(run_workflow)
mcp.tool()(resume_workflow)
mcp.tool()(get_workflow_status)
mcp.tool()(create_session)
mcp.tool()(register_dataset)
mcp.tool()(get_session_state)
mcp.tool()(reset_session_state)
mcp.tool()(get_result_handle)
mcp.tool()(get_operation_status)
mcp.tool()(list_operations)

# Core local tools — always registered
mcp.tool()(inspect_mesh)
mcp.tool()(inspect_variable)
mcp.tool()(calculate_area)
mcp.tool()(calculate_zonal_mean)
mcp.tool()(validate_dataset)
mcp.tool()(list_datasets)

# Visualization tools — always registered
mcp.tool()(plot_mesh)
mcp.tool()(plot_variable)
mcp.tool()(plot_zonal_mean)

# Analysis extensions — always registered
mcp.tool()(subset_bbox)
mcp.tool()(subset_polygon)
mcp.tool()(extract_cross_section)
mcp.tool()(compare_fields)
mcp.tool()(calculate_bias)
mcp.tool()(calculate_rmse)
mcp.tool()(calculate_pattern_correlation)
mcp.tool()(remap_variable)
mcp.tool()(regrid_dataset)
mcp.tool()(calculate_temporal_mean)
mcp.tool()(calculate_anomaly)
mcp.tool()(calculate_ensemble_mean)
mcp.tool()(calculate_ensemble_spread)
mcp.tool()(export_to_netcdf)
mcp.tool()(export_to_csv)
mcp.tool()(write_result)

# Execution mode control — always registered so users can switch modes
mcp.tool()(get_execution_mode)
mcp.tool()(probe_path_access)
mcp.tool()(set_execution_mode)
mcp.tool()(validate_hpc_setup)

# HPC tools — only register when an endpoint is configured
if load_config().has_endpoint:
    mcp.tool()(inspect_mesh_hpc)
    mcp.tool()(calculate_area_hpc)
    mcp.tool()(inspect_variable_hpc)
    mcp.tool()(calculate_zonal_mean_hpc)
    mcp.tool()(plot_mesh_hpc)
    mcp.tool()(plot_variable_hpc)
    mcp.tool()(plot_zonal_mean_hpc)

if __name__ == "__main__":
    mcp.run()
