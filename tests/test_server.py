import pytest

from uxarray_mcp.remote.config import load_config
from uxarray_mcp.server import mcp


@pytest.mark.asyncio
async def test_inspect_mesh_tool_registered():
    """Verify all expected tools are registered with the MCP server."""
    # List tools to get their metadata
    tools = await mcp.get_tools()

    expected_tools = {
        "get_capabilities",
        "list_datasets",
        "run_scientific_agent",
        "run_workflow",
        "resume_workflow",
        "get_workflow_status",
        "create_session",
        "register_dataset",
        "get_session_state",
        "reset_session_state",
        "get_result_handle",
        "get_operation_status",
        "list_operations",
        "inspect_mesh",
        "inspect_variable",
        "calculate_area",
        "calculate_zonal_mean",
        "validate_dataset",
        "plot_mesh",
        "plot_variable",
        "plot_zonal_mean",
        "subset_bbox",
        "subset_polygon",
        "extract_cross_section",
        "compare_fields",
        "calculate_bias",
        "calculate_rmse",
        "calculate_pattern_correlation",
        "remap_variable",
        "regrid_dataset",
        "calculate_temporal_mean",
        "calculate_anomaly",
        "calculate_ensemble_mean",
        "calculate_ensemble_spread",
        "export_to_netcdf",
        "export_to_csv",
        "write_result",
        "get_execution_mode",
        "probe_path_access",
        "set_execution_mode",
        "validate_hpc_setup",
    }
    assert expected_tools.issubset(set(tools.keys()))

    hpc_tools = {
        "inspect_mesh_hpc",
        "calculate_area_hpc",
        "inspect_variable_hpc",
        "calculate_zonal_mean_hpc",
    }
    if load_config().has_endpoint:
        assert hpc_tools.issubset(set(tools.keys()))
    else:
        assert hpc_tools.isdisjoint(set(tools.keys()))
