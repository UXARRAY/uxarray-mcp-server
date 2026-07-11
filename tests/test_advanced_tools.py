"""Tests for subsetting, comparison, remapping, temporal, and export tools."""

import warnings
from pathlib import Path

import numpy as np
import pytest

from uxarray_mcp.tools import (
    calculate_anomaly,
    calculate_bias,
    calculate_ensemble_mean,
    calculate_ensemble_spread,
    calculate_pattern_correlation,
    calculate_rmse,
    calculate_temporal_mean,
    compare_fields,
    create_session,
    export_to_csv,
    export_to_netcdf,
    extract_cross_section,
    get_result_handle,
    register_dataset,
    regrid_dataset,
    remap_variable,
    subset_bbox,
    subset_polygon,
    write_result,
)
from uxarray_mcp.tools.frontdoor import run_analysis


def test_spatial_subset_tools_persist_results(state_dir, synthetic_mesh_with_data):
    """Spatial query tools should return result handles with persisted artifacts."""
    grid_file, data_file = synthetic_mesh_with_data
    session = create_session("subset-session")

    bbox_result = subset_bbox(
        lon_bounds=[0.0, 1.0],
        lat_bounds=[0.0, 1.0],
        grid_path=grid_file,
        data_path=data_file,
        variable_name="temperature",
        session_id=session["session_id"],
    )
    polygon_result = subset_polygon(
        polygon_lon_lat=[[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]],
        grid_path=grid_file,
        session_id=session["session_id"],
    )
    cross_section = extract_cross_section(
        latitude=0.2,
        grid_path=grid_file,
        data_path=data_file,
        variable_name="temperature",
        session_id=session["session_id"],
    )

    bbox_handle = get_result_handle(bbox_result["result_handle"])
    polygon_handle = get_result_handle(polygon_result["result_handle"])
    cross_handle = get_result_handle(cross_section["result_handle"])

    assert bbox_result["subset_grid"]["n_face"] == 1
    assert polygon_result["selected_face_count"] == 1
    assert cross_section["selection_type"] == "constant_latitude"
    assert Path(bbox_handle["artifact_path"]).exists()
    assert Path(polygon_handle["artifact_path"]).exists()
    assert Path(cross_handle["artifact_path"]).exists()


def test_comparison_metric_tools_return_expected_values(
    state_dir, comparison_mesh_with_data
):
    """Same-grid comparison tools should compute bias, RMSE, and correlation."""
    grid_file, data_a, data_b = comparison_mesh_with_data
    session = create_session("compare-session")

    comparison = compare_fields(
        variable_name="temperature",
        data_path_a=data_a,
        data_path_b=data_b,
        grid_path=grid_file,
        session_id=session["session_id"],
    )
    bias = calculate_bias(
        variable_name="temperature",
        data_path_a=data_a,
        data_path_b=data_b,
        grid_path=grid_file,
    )
    rmse = calculate_rmse(
        variable_name="temperature",
        data_path_a=data_a,
        data_path_b=data_b,
        grid_path=grid_file,
    )
    correlation = calculate_pattern_correlation(
        variable_name="temperature",
        data_path_a=data_a,
        data_path_b=data_b,
        grid_path=grid_file,
    )

    difference = get_result_handle(comparison["difference_field_handle"])

    assert comparison["metrics"]["bias"] == -2.0
    assert comparison["metrics"]["rmse"] == 2.0
    assert bias["bias"] == -2.0
    assert rmse["rmse"] == 2.0
    assert correlation["pattern_correlation"] == 0.0
    assert Path(difference["artifact_path"]).exists()


def test_remap_and_regrid_tools_persist_outputs(
    state_dir, comparison_mesh_with_data, remap_target_grid
):
    """Remapping tools should persist artifacts on the target grid."""
    grid_file, data_a, _ = comparison_mesh_with_data
    session = create_session("remap-session")
    dataset = register_dataset(
        session["session_id"],
        grid_path=grid_file,
        data_path=data_a,
    )

    remapped = remap_variable(
        target_grid_path=remap_target_grid,
        variable_name="temperature",
        session_id=session["session_id"],
        dataset_handle=dataset["dataset_handle"],
    )
    regridded = regrid_dataset(
        target_grid_path=remap_target_grid,
        session_id=session["session_id"],
        dataset_handle=dataset["dataset_handle"],
        variable_names=["temperature"],
    )

    remap_result = get_result_handle(remapped["result_handle"])
    regrid_result = get_result_handle(regridded["result_handle"])

    assert remapped["variable_name"] == "temperature"
    assert regridded["variables"] == ["temperature"]
    assert Path(remap_result["artifact_path"]).exists()
    assert Path(regrid_result["artifact_path"]).exists()


def test_temporal_and_ensemble_tools_persist_outputs(
    state_dir, time_series_dataset, ensemble_data_files
):
    """Temporal and ensemble statistics should produce persisted result handles."""
    session = create_session("stats-session")

    temporal_mean = calculate_temporal_mean(
        data_path=time_series_dataset,
        variable_name="temperature",
        session_id=session["session_id"],
    )
    anomaly = calculate_anomaly(
        data_path=time_series_dataset,
        variable_name="temperature",
        session_id=session["session_id"],
    )
    ensemble_mean = calculate_ensemble_mean(
        variable_name="temperature",
        data_paths=ensemble_data_files,
        session_id=session["session_id"],
    )
    ensemble_spread = calculate_ensemble_spread(
        variable_name="temperature",
        data_paths=ensemble_data_files,
        session_id=session["session_id"],
    )

    assert temporal_mean["summary"]["shape"] == [2]
    assert anomaly["summary"]["shape"] == [3, 2]
    assert ensemble_mean["member_count"] == 2
    assert ensemble_spread["member_count"] == 2
    assert Path(
        get_result_handle(temporal_mean["result_handle"])["artifact_path"]
    ).exists()
    assert Path(
        get_result_handle(ensemble_mean["result_handle"])["artifact_path"]
    ).exists()


def test_export_tools_support_result_handles_and_dataset_handles(
    state_dir, comparison_mesh_with_data
):
    """Exports should work from both persisted results and registered datasets."""
    grid_file, data_a, data_b = comparison_mesh_with_data
    session = create_session("export-session")
    dataset = register_dataset(
        session["session_id"],
        grid_path=grid_file,
        data_path=data_a,
    )
    comparison = compare_fields(
        variable_name="temperature",
        data_path_a=data_a,
        data_path_b=data_b,
        grid_path=grid_file,
        session_id=session["session_id"],
    )

    netcdf_output = Path(state_dir) / "exports" / "difference.nc"
    csv_output = Path(state_dir) / "exports" / "dataset.csv"
    write_output = Path(state_dir) / "exports" / "difference.csv"

    exported_netcdf = export_to_netcdf(
        output_path=str(netcdf_output),
        result_handle=comparison["difference_field_handle"],
        session_id=session["session_id"],
    )
    exported_csv = export_to_csv(
        output_path=str(csv_output),
        session_id=session["session_id"],
        dataset_handle=dataset["dataset_handle"],
        variable_name="temperature",
    )
    written = write_result(
        output_path=str(write_output),
        format="csv",
        result_handle=comparison["difference_field_handle"],
        session_id=session["session_id"],
    )

    assert Path(exported_netcdf["output_path"]).exists()
    assert Path(exported_csv["output_path"]).exists()
    assert Path(written["output_path"]).exists()


def test_remap_to_rectilinear_dispatch(state_dir, structured_mesh_files):
    """remap_to_rectilinear returns a regular grid with a result handle."""
    grid_file, data_file = structured_mesh_files
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = run_analysis(
            operation="remap_to_rectilinear",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
            target_lon=list(np.arange(0, 360, 30.0)),
            target_lat=list(np.arange(-60, 61, 30.0)),
        )
    assert result["target_shape"] == [5, 12]
    assert set(result["stats"]) == {"min", "max", "mean"}
    assert result["result_handle"]
    assert "_provenance" in result


def test_remap_to_rectilinear_missing_target_coords_raises(
    state_dir, structured_mesh_files
):
    grid_file, data_file = structured_mesh_files
    with pytest.raises(ValueError):
        run_analysis(
            operation="remap_to_rectilinear",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
        )


# ---------------------------------------------------------------------------
# Remote remap dispatch (mocked agent — no real HPC call)
# ---------------------------------------------------------------------------


class _MockAgent:
    """Minimal agent stub whose _run_on_hpc returns synthetic remote results."""

    def __init__(self, payload):
        from types import SimpleNamespace

        self.config = SimpleNamespace(endpoint_id="ep-123", endpoint_name="chrysalis")
        self._payload = payload

    async def _run_on_hpc(self, func, *args, **kwargs):
        result = dict(self._payload)
        result.setdefault("_provenance", {})["execution_venue"] = "hpc:chrysalis"
        return result


def test_remap_variable_remote_dispatch(monkeypatch):
    """remap_variable(use_remote=True) returns the remote summary result."""
    from uxarray_mcp.remote import agent as agent_mod
    from uxarray_mcp.tools import remote_tools

    payload = {
        "variable_name": "temperature",
        "method": "nearest_neighbor",
        "result_shape": [42],
        "stats": {"min": 1.0, "max": 2.0, "mean": 1.5, "std": 0.1},
        "_provenance": {"execution_venue": "hpc:chrysalis"},
    }
    monkeypatch.setattr(agent_mod, "get_agent", lambda **kw: _MockAgent(payload))
    monkeypatch.setattr(
        remote_tools, "_endpoint_manager_is_up", lambda agent: (True, "ok")
    )

    result = remap_variable(
        target_grid_path="/lus/only/on/hpc/target.nc",
        variable_name="temperature",
        grid_path="/lus/only/on/hpc/grid.nc",
        data_path="/lus/only/on/hpc/data.nc",
        use_remote=True,
        endpoint="chrysalis",
    )
    assert result["_provenance"]["execution_venue"] == "hpc:chrysalis"
    assert result["stats"]["mean"] == 1.5


def test_remap_remote_raises_when_endpoint_down_and_path_remote(monkeypatch):
    """Remote-only path + dead endpoint must raise clearly, not FileNotFound."""
    from uxarray_mcp.remote import agent as agent_mod
    from uxarray_mcp.tools import remote_tools

    monkeypatch.setattr(agent_mod, "get_agent", lambda **kw: _MockAgent({}))
    monkeypatch.setattr(
        remote_tools,
        "_endpoint_manager_is_up",
        lambda agent: (False, "offline"),
    )

    with pytest.raises(RuntimeError, match="not readable locally"):
        remap_variable(
            target_grid_path="/lus/only/on/hpc/target.nc",
            variable_name="temperature",
            grid_path="/lus/only/on/hpc/grid.nc",
            data_path="/lus/only/on/hpc/data.nc",
            use_remote=True,
            endpoint="chrysalis",
        )
