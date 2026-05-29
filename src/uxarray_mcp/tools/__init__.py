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
    endpoint_status,
    get_execution_mode,
    probe_path_access,
    set_execution_mode,
    validate_hpc_setup,
)
from .inspection import validate_dataset
from .orchestration import analyze_dataset

# Public tool surface for inspection and plotting. Each function is a
# dispatcher that runs locally by default and routes to a Globus Compute
# endpoint when ``use_remote=True``. Internal callers that need the pure
# local implementation can import the underscored helpers from
# ``.inspection`` / ``.plotting`` directly.
from .remote_tools import (
    calculate_area,
    calculate_zonal_mean,
    inspect_mesh,
    inspect_variable,
    plot_mesh,
    plot_variable,
    plot_zonal_mean,
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
    "analyze_dataset",
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
    "endpoint_status",
    "get_execution_mode",
    "probe_path_access",
    "set_execution_mode",
    "validate_hpc_setup",
]
