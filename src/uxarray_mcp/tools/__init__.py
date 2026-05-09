from .advanced import (
    calculate_anomaly,
    calculate_bias,
    calculate_ensemble_mean,
    calculate_ensemble_spread,
    calculate_pattern_correlation,
    calculate_rmse,
    calculate_temporal_mean,
    compare_fields,
    export_to_csv,
    export_to_netcdf,
    extract_cross_section,
    regrid_dataset,
    remap_variable,
    subset_bbox,
    subset_polygon,
    write_result,
)
from .capabilities import get_capabilities
from .catalog import list_datasets
from .execution_control import (
    get_execution_mode,
    probe_path_access,
    set_execution_mode,
    validate_hpc_setup,
)

# Local-only implementations are still importable for internal callers
# (scientific_agent, tests). The dispatcher versions in remote_tools.py are
# the user-facing entry points and accept use_remote/endpoint/session_id.
from .inspection import (
    calculate_area,
    calculate_zonal_mean,
    inspect_mesh,
    inspect_variable,
    validate_dataset,
)
from .plotting import plot_mesh, plot_variable, plot_zonal_mean
from .remote_tools import (
    calculate_area_hpc,
    calculate_zonal_mean_hpc,
    inspect_mesh_hpc,
    inspect_variable_hpc,
    plot_mesh_hpc,
    plot_variable_hpc,
    plot_zonal_mean_hpc,
)
from .scientific_agent import run_scientific_agent
from .stateful import (
    create_session,
    get_operation_status,
    get_result_handle,
    get_session_state,
    get_workflow_status,
    list_operations,
    register_dataset,
    reset_session_state,
    resume_workflow,
    run_workflow,
)

__all__ = [
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
    # Local implementations (used by scientific_agent and tests)
    "inspect_mesh",
    "inspect_variable",
    "calculate_area",
    "calculate_zonal_mean",
    "validate_dataset",
    "plot_mesh",
    "plot_variable",
    "plot_zonal_mean",
    # Dispatcher versions (registered as MCP tools without _hpc suffix)
    "inspect_mesh_hpc",
    "calculate_area_hpc",
    "inspect_variable_hpc",
    "calculate_zonal_mean_hpc",
    "plot_mesh_hpc",
    "plot_variable_hpc",
    "plot_zonal_mean_hpc",
    # Analysis extensions
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
]
