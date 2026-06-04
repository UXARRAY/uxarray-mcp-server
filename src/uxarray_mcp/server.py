"""UXarray MCP Server - Provides mesh analysis tools for AI agents.

The MCP surface is intentionally small. Low-level UXarray capabilities remain
available inside ``uxarray_mcp.tools`` for tests, scripts, and internal
workflows, but MCP clients see intent-shaped front doors instead of dozens of
fine-grained implementation functions.
"""

from fastmcp import FastMCP

from uxarray_mcp.tools import (
    analyze_dataset,
    diagnose_endpoint,
    get_capabilities,
    get_result,
    get_status,
    manage_session,
    plot_dataset,
    probe_path_access,
    resume_workflow,
    run_analysis,
    run_workflow,
)

mcp = FastMCP("uxarray-mcp-server")

# Discovery and first-look analysis.
mcp.tool()(get_capabilities)
mcp.tool()(analyze_dataset)

# Intent-shaped operation dispatch. These tools fan out to the lower-level
# analysis, plotting, state, and diagnostic functions.
mcp.tool()(run_analysis)
mcp.tool()(plot_dataset)
mcp.tool()(diagnose_endpoint)
mcp.tool()(probe_path_access)

# Stateful workflow/session front doors.
mcp.tool()(run_workflow)
mcp.tool()(resume_workflow)
mcp.tool()(get_status)
mcp.tool()(get_result)
mcp.tool()(manage_session)


@mcp.prompt()
def first_look(path: str) -> str:
    """Run the full first-look analysis pipeline on a mesh or dataset."""
    return (
        f"Run a complete first-look analysis on `{path}`.\n\n"
        "Steps:\n"
        f'1. Call `get_capabilities` with `grid_path="{path}"` to discover '
        "what operations apply.\n"
        f'2. Call `analyze_dataset` with `grid_path="{path}"` to run the full '
        "first-look pipeline.\n"
        "3. Summarise topology, data quality issues, selected variable, area "
        "statistics, zonal mean, plots, and recommended next steps."
    )


@mcp.prompt()
def vorticity_analysis(grid_path: str, data_path: str, u_var: str, v_var: str) -> str:
    """Compute and interpret relative vorticity and wind divergence."""
    return (
        f"Analyse vorticity and divergence for `{data_path}`.\n\n"
        "1. Call `run_analysis` with "
        f'operation="curl", grid_path="{grid_path}", data_path="{data_path}", '
        f'u_variable="{u_var}", v_variable="{v_var}".\n'
        "2. Call `run_analysis` with "
        f'operation="divergence", grid_path="{grid_path}", '
        f'data_path="{data_path}", u_variable="{u_var}", '
        f'v_variable="{v_var}".\n'
        "3. Interpret the min/max/mean/std values and identify follow-up "
        "plots or regional subsets."
    )


@mcp.prompt()
def hpc_diagnose(endpoint: str = "") -> str:
    """Diagnose the HPC endpoint connection and configuration."""
    ep = f', endpoint="{endpoint}"' if endpoint else ""
    return (
        "Diagnose the HPC Globus Compute configuration.\n\n"
        f'1. Call `diagnose_endpoint(action="status"{ep})` for endpoint '
        "manager and worker status.\n"
        f'2. Call `diagnose_endpoint(action="validate"{ep})` for SDK auth, '
        "manager reachability, and a remote no-op probe.\n"
        "3. Explain failures as concrete next actions: re-authenticate, "
        "restart the endpoint, fix worker environment, or probe a path."
    )


if __name__ == "__main__":
    mcp.run()
