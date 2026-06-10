"""Eval cases — deliberately malformed calls to run_analysis / plot_dataset.

Each case is a dict with:
- id: short slug for the report
- description: one-line plain-English description of the bug
- tool: 'run_analysis' or 'plot_dataset'
- kwargs: the call to make
- expected: 'reject' (we want the boundary to catch it) or 'accept'
  (the call is well-formed and should run cleanly — a sanity baseline)

Cases marked 'accept' are baseline sanity checks: if too many of them fail,
the eval itself is broken. Cases marked 'reject' are the actual measurement.
"""

from __future__ import annotations


def build_cases(grid_path: str, grid_path_with_data: tuple[str, str]) -> list[dict]:
    """Return the case list, parameterized by the synthetic fixture paths."""
    grid_only = grid_path
    grid_for_data, data_path = grid_path_with_data
    missing_path = "/nonexistent/path/that/cannot/possibly/exist.nc"

    return [
        # ---- BASELINES: well-formed calls that SHOULD succeed ----
        {
            "id": "baseline_inspect_mesh",
            "description": "Well-formed inspect_mesh on a valid grid",
            "tool": "run_analysis",
            "kwargs": {"operation": "inspect_mesh", "grid_path": grid_only},
            "expected": "accept",
        },
        {
            "id": "baseline_calculate_area",
            "description": "Well-formed calculate_area on a valid grid",
            "tool": "run_analysis",
            "kwargs": {"operation": "calculate_area", "grid_path": grid_only},
            "expected": "accept",
        },
        # ---- MALFORMED: schema-level violations ----
        {
            "id": "wrong_operation_typo",
            "description": "operation='curl_calculation' instead of 'curl'",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "curl_calculation",
                "grid_path": grid_only,
                "data_path": data_path,
                "u_variable": "u",
                "v_variable": "v",
            },
            "expected": "reject",
        },
        {
            "id": "wrong_operation_empty",
            "description": "operation='' (empty string)",
            "tool": "run_analysis",
            "kwargs": {"operation": ""},
            "expected": "reject",
        },
        {
            "id": "wrong_operation_made_up",
            "description": "operation='fluxulate' — does not exist",
            "tool": "run_analysis",
            "kwargs": {"operation": "fluxulate", "grid_path": grid_only},
            "expected": "reject",
        },
        # ---- MALFORMED: missing required parameter ----
        {
            "id": "missing_grid_path",
            "description": "inspect_mesh without grid_path",
            "tool": "run_analysis",
            "kwargs": {"operation": "inspect_mesh"},
            "expected": "reject",
        },
        {
            "id": "missing_data_path",
            "description": "inspect_variable with grid but no data",
            "tool": "run_analysis",
            "kwargs": {"operation": "inspect_variable", "grid_path": grid_only},
            "expected": "reject",
        },
        {
            "id": "missing_variable_name",
            "description": "calculate_zonal_mean without variable_name",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "calculate_zonal_mean",
                "grid_path": grid_for_data,
                "data_path": data_path,
            },
            "expected": "reject",
        },
        {
            "id": "missing_u_variable",
            "description": "curl with v_variable but no u_variable",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "curl",
                "grid_path": grid_for_data,
                "data_path": data_path,
                "v_variable": "v",
            },
            "expected": "reject",
        },
        {
            "id": "missing_center_for_azimuthal",
            "description": "azimuthal_mean without center_lon/lat/radius",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "azimuthal_mean",
                "grid_path": grid_for_data,
                "data_path": data_path,
                "variable_name": "temperature",
            },
            "expected": "reject",
        },
        {
            "id": "missing_bbox_bounds",
            "description": "subset_bbox without lon_bounds/lat_bounds",
            "tool": "run_analysis",
            "kwargs": {"operation": "subset_bbox", "grid_path": grid_only},
            "expected": "reject",
        },
        {
            "id": "missing_data_path_a",
            "description": "compare_fields missing data_path_a",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "compare_fields",
                "variable_name": "temperature",
                "data_path_b": data_path,
            },
            "expected": "reject",
        },
        {
            "id": "missing_target_grid_for_remap",
            "description": "remap_variable without target_grid_path",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "remap_variable",
                "grid_path": grid_for_data,
                "data_path": data_path,
                "variable_name": "temperature",
            },
            "expected": "reject",
        },
        {
            "id": "missing_data_paths_for_ensemble",
            "description": "ensemble_mean without data_paths",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "ensemble_mean",
                "variable_name": "temperature",
            },
            "expected": "reject",
        },
        {
            "id": "missing_output_path_for_export",
            "description": "export without output_path",
            "tool": "run_analysis",
            "kwargs": {"operation": "export"},
            "expected": "reject",
        },
        # ---- MALFORMED: nonexistent file paths (IO layer should catch) ----
        {
            "id": "nonexistent_grid",
            "description": "inspect_mesh against a path that does not exist",
            "tool": "run_analysis",
            "kwargs": {"operation": "inspect_mesh", "grid_path": missing_path},
            "expected": "reject",
        },
        {
            "id": "nonexistent_data",
            "description": "inspect_variable with nonexistent data file",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "inspect_variable",
                "grid_path": grid_for_data,
                "data_path": missing_path,
            },
            "expected": "reject",
        },
        # ---- MALFORMED: plot_dataset variants ----
        {
            "id": "plot_unknown_type",
            "description": "plot_dataset with plot_type='holography'",
            "tool": "plot_dataset",
            "kwargs": {"plot_type": "holography", "grid_path": grid_only},
            "expected": "reject",
        },
        {
            "id": "plot_missing_variable",
            "description": "plot_dataset variable plot but no variable_name",
            "tool": "plot_dataset",
            "kwargs": {
                "plot_type": "variable",
                "grid_path": grid_for_data,
                "data_path": data_path,
            },
            "expected": "reject",
        },
        {
            "id": "plot_variable_does_not_exist",
            "description": "plot_dataset for variable 'pixiedust' (not in file)",
            "tool": "plot_dataset",
            "kwargs": {
                "plot_type": "variable",
                "grid_path": grid_for_data,
                "data_path": data_path,
                "variable_name": "pixiedust",
            },
            "expected": "reject",
        },
        # ---- MALFORMED: wrong-type bbox bounds ----
        {
            "id": "bbox_wrong_arity",
            "description": "subset_bbox with lon_bounds=[10] (needs 2 floats)",
            "tool": "run_analysis",
            "kwargs": {
                "operation": "subset_bbox",
                "grid_path": grid_only,
                "lon_bounds": [10.0],
                "lat_bounds": [0.0, 10.0],
            },
            "expected": "reject",
        },
    ]
