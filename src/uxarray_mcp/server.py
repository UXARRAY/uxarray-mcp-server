"""UXarray MCP Server - Provides mesh analysis tools for AI agents.

The MCP-registered tool names are kept short and stable. Tools that can run
on either the local machine or a configured Globus Compute endpoint expose a
``use_remote`` flag — there is a single canonical name per tool (no
``*_hpc`` suffix). The dispatcher falls back to local execution
automatically when no endpoint is configured.
"""

from fastmcp import FastMCP

from uxarray_mcp.tools import (
    analyze_dataset,
    calculate_anomaly,
    calculate_area,
    calculate_bias,
    calculate_ensemble_mean,
    calculate_ensemble_spread,
    calculate_pattern_correlation,
    calculate_rmse,
    calculate_temporal_mean,
    calculate_zonal_mean,
    compare_fields,
    create_session,
    endpoint_status,
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
    inspect_variable,
    list_datasets,
    list_operations,
    plot_mesh,
    plot_variable,
    plot_zonal_mean,
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

# Deterministic one-shot analysis — full first-look pipeline in a single call
mcp.tool()(analyze_dataset)

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

# Core inspection + computation tools. Each accepts ``use_remote`` /
# ``endpoint`` and falls back to local execution when no endpoint is configured.
mcp.tool()(inspect_mesh)
mcp.tool()(inspect_variable)
mcp.tool()(calculate_area)
mcp.tool()(calculate_zonal_mean)
mcp.tool()(validate_dataset)
mcp.tool()(list_datasets)

# Visualization tools — same dispatcher pattern.
mcp.tool()(plot_mesh)
mcp.tool()(plot_variable)
mcp.tool()(plot_zonal_mean)

# Analysis extensions
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

# Execution mode + diagnostics
mcp.tool()(get_execution_mode)
mcp.tool()(endpoint_status)
mcp.tool()(probe_path_access)
mcp.tool()(set_execution_mode)
mcp.tool()(validate_hpc_setup)

if __name__ == "__main__":
    mcp.run()
