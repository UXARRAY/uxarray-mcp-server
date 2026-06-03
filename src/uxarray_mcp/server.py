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
    calculate_azimuthal_mean,
    calculate_bias,
    calculate_curl,
    calculate_divergence,
    calculate_ensemble_mean,
    calculate_ensemble_spread,
    calculate_gradient,
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
    plot_mesh_geo,
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
mcp.tool()(plot_mesh_geo)
mcp.tool()(plot_variable)
mcp.tool()(plot_zonal_mean)

# Vector calculus — gradient, curl (vorticity), divergence, azimuthal mean
mcp.tool()(calculate_gradient)
mcp.tool()(calculate_curl)
mcp.tool()(calculate_divergence)
mcp.tool()(calculate_azimuthal_mean)

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

# ---------------------------------------------------------------------------
# MCP Prompts — user-invokable slash commands that guide common workflows.
# Each prompt returns a structured message the client injects into the
# conversation; the AI then calls the appropriate tools.
# ---------------------------------------------------------------------------


@mcp.prompt()
def first_look(path: str) -> str:
    """Run the full first-look analysis pipeline on a mesh or dataset.

    Pass a local file path (or HEALPix spec like healpix:4). The assistant
    will call get_capabilities, then analyze_dataset to inspect topology,
    validate data quality, compute area statistics, zonal mean, and produce
    mesh and variable plots — all in one shot.

    Parameters
    ----------
    path : str
        Path to the mesh or data file, e.g. /data/grid.nc or healpix:4.
    """
    return (
        f"Run a complete first-look analysis on `{path}`.\n\n"
        "Steps:\n"
        '1. Call `get_capabilities` with `grid_path="{path}"` to discover '
        "what tools apply.\n"
        '2. Call `analyze_dataset` with `file_path="{path}"` to run the full '
        "pipeline: inspect_mesh → validate_dataset → inspect_variable → "
        "calculate_area → calculate_zonal_mean → plot_mesh → plot_variable.\n"
        "3. Summarise the mesh topology, any data quality issues, and the "
        "zonal mean profile. Show the plots inline.\n"
        "4. List the recommended next steps from the result."
    ).format(path=path)


@mcp.prompt()
def vorticity_analysis(grid_path: str, data_path: str, u_var: str, v_var: str) -> str:
    """Compute and interpret relative vorticity and wind divergence.

    Runs calculate_curl (vorticity ζ = ∂v/∂x − ∂u/∂y) and
    calculate_divergence (∂u/∂x + ∂v/∂y) on the provided wind components,
    then asks the assistant to interpret the atmospheric dynamics.

    Parameters
    ----------
    grid_path : str
        Path to the mesh grid file.
    data_path : str
        Path to the data file containing wind components.
    u_var : str
        Zonal wind variable name (e.g. uReconstructZonal).
    v_var : str
        Meridional wind variable name (e.g. uReconstructMeridional).
    """
    return (
        f"Analyse the vorticity and divergence of the wind field in `{data_path}`.\n\n"
        f'1. Call `calculate_curl` with grid_path="{grid_path}", '
        f'data_path="{data_path}", u_variable="{u_var}", v_variable="{v_var}".\n'
        f"2. Call `calculate_divergence` with the same arguments.\n"
        "3. Interpret the results:\n"
        "   - Where is vorticity largest/smallest? What does that indicate "
        "(cyclonic vs anticyclonic flow)?\n"
        "   - Where is divergence strongly negative (convergence)? That "
        "indicates rising motion and potential convection.\n"
        "   - Report the global min/max/mean/std for both fields.\n"
        "4. Suggest follow-up analysis (e.g. subset_bbox over regions of "
        "extreme vorticity, plot_variable of a derived field)."
    )


@mcp.prompt()
def hpc_diagnose(endpoint: str = "") -> str:
    """Diagnose the HPC endpoint connection and configuration.

    Runs endpoint_status, then validate_hpc_setup, and guides the user
    through fixing any issues found.

    Parameters
    ----------
    endpoint : str, optional
        Named endpoint to diagnose (e.g. "improv", "ucar"). Leave blank
        to check all configured endpoints.
    """
    ep_arg = f'endpoint="{endpoint}"' if endpoint else ""
    return (
        "Diagnose the HPC Globus Compute configuration.\n\n"
        f"1. Call `endpoint_status`({ep_arg}) to get a fast cached status "
        "summary of all configured endpoints.\n"
        f"2. Call `validate_hpc_setup`({ep_arg}) to run a deeper check: "
        "SDK auth, endpoint manager reachability, and a remote no-op probe.\n"
        "3. If any check fails, explain what the error means and what the "
        "user should do to fix it (re-authenticate, restart the endpoint "
        "manager, check the worker environment, etc.).\n"
        "4. If everything passes, confirm the endpoint is ready for "
        "use_remote=True tool calls."
    )


if __name__ == "__main__":
    mcp.run()
