"""Each public tool: a real number, one refusal, and the envelope."""

from __future__ import annotations

import json

import pytest

from uxarray_mcp.server import tools as t
from uxarray_mcp.server.contract import OVERRIDE_TOKEN

EARTH = 6371000.0


def _envelope(result: dict) -> None:
    assert result["outcome"] == "complete"
    assert result["status"] in ("complete", "warning", "unverified")
    assert "warning_codes" in result and "preconditions" in result
    prov = result["_provenance"]
    assert prov["tool"] and prov["venue"] == "local" and prov["uxarray_version"]
    json.dumps(result, allow_nan=False)


def _refused(result: dict, check_id: str) -> None:
    assert result["outcome"] == "input_required"
    assert check_id in [c["id"] for c in result["refusal"]["failed_checks"]]
    assert result["refusal"]["repairs"]


# ------------------------------------------------------------- list / inspect


def test_list_datasets_reads_headers_not_filenames(structured_mesh_files, tmp_path):
    grid, data = structured_mesh_files
    out = t.list_datasets(directory=str(tmp_path), recursive=True)
    _envelope(out)
    by_path = {f["path"]: f for f in out["files"]}
    assert (
        by_path[grid]["role"] in ("grid", "grid+data") and by_path[grid]["n_face"] > 0
    )
    assert by_path[data]["role"] in ("data", "grid+data")
    assert grid in out["grids"]


def test_list_datasets_missing_directory_is_an_error():
    with pytest.raises(FileNotFoundError):
        t.list_datasets(directory="/nope/none")


def test_inspect_dataset_reports_topology_coverage_variables(
    structured_mesh_files, state_dir
):
    grid, data = structured_mesh_files
    out = t.inspect_dataset(grid_path=grid, data_path=data)
    _envelope(out)
    assert out["n_face"] > 0 and out["size_class"] == "small"
    assert "sphere_fraction" in out["mesh_coverage"]
    assert any(v["name"] == "temperature" for v in out["variables"])
    assert out["validation"]["passed"] is True
    assert out["plot_hint"].startswith("polygons")


def test_inspect_healpix_spec_needs_no_file(state_dir):
    out = t.inspect_dataset(grid_path="healpix:2")
    assert out["n_face"] == 192 and out["mesh_coverage"][
        "sphere_fraction"
    ] == pytest.approx(1.0, abs=1e-3)


# -------------------------------------------------------------------- compute


def test_area_with_radius_is_physical(state_dir):
    out = t.compute(statistic="area", grid_path="healpix:3", sphere_radius=EARTH)
    _envelope(out)
    assert out["total_area"] == pytest.approx(
        4 * 3.141592653589793 * EARTH**2, rel=1e-4
    )
    assert out["physically_interpretable"] is True
    assert len(json.dumps(out)) < 1500


def test_area_without_radius_is_refused_then_overridable(state_dir):
    refused = t.compute(statistic="area", grid_path="healpix:2")
    _refused(refused, "radius_known")
    forced = t.compute(
        statistic="area", grid_path="healpix:2", acknowledge=OVERRIDE_TOKEN
    )
    assert (
        forced["status"] == "unverified" and forced["physically_interpretable"] is False
    )


def test_regional_mesh_area_warns_not_global(regional_mesh_files, state_dir):
    grid, _ = regional_mesh_files
    out = t.compute(statistic="area", grid_path=grid, sphere_radius=EARTH)
    assert "MESH_NOT_GLOBAL" in out["warning_codes"] and out["status"] == "warning"


def test_zonal_mean_profile_and_empty_bands_refuse(
    structured_mesh_files, regional_mesh_files, state_dir
):
    grid, data = structured_mesh_files
    out = t.compute(
        statistic="zonal_mean",
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
        lat_spec=[-60, 60],
        lat_step=30,
    )
    _envelope(out)
    assert len(out["latitudes"]) == 5 and len(out["zonal_mean_values"]) == 5
    rgrid, rdata = regional_mesh_files
    refused = t.compute(
        statistic="zonal_mean",
        grid_path=rgrid,
        data_path=rdata,
        variable_name="temperature",
        lat_spec=[-85.0, -80.0],
    )
    _refused(refused, "zonal_mean_nonzero")


def test_temporal_mean_persists_a_result(time_series_dataset, state_dir):
    out = t.compute(
        statistic="temporal_mean",
        data_path=time_series_dataset,
        variable_name="temperature",
    )
    _envelope(out)
    assert out["result_handle"].startswith("result_") and out["artifact_path"].endswith(
        ".nc"
    )


def test_unknown_statistic_names_the_options(state_dir):
    with pytest.raises(ValueError, match="zonal_mean"):
        t.compute(statistic="frobnicate", grid_path="healpix:1")


# -------------------------------------------------------------- vector calc


@pytest.fixture
def healpix_files(healpix_field_dataset, tmp_path):
    data = tmp_path / "hp_data.nc"
    healpix_field_dataset.to_xarray().to_netcdf(data)
    return "healpix:2", str(data)


def test_gradient_refuses_without_radius_then_computes(healpix_files, state_dir):
    grid, data = healpix_files
    refused = t.vector_calc(
        operation="gradient",
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
    )
    _refused(refused, "radius_scaling")
    out = t.vector_calc(
        operation="gradient",
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
        sphere_radius=EARTH,
    )
    _envelope(out)
    assert out["physically_interpretable"] is True


def test_curl_needs_velocity_metadata(healpix_files, state_dir):
    grid, data = healpix_files
    out = t.vector_calc(
        operation="curl",
        grid_path=grid,
        data_path=data,
        u_variable="u",
        v_variable="v",
        sphere_radius=EARTH,
    )
    assert out["outcome"] in ("complete", "input_required")
    if out["outcome"] == "input_required":
        assert {c["id"] for c in out["refusal"]["failed_checks"]} <= {
            "velocity_units",
            "component_identity",
        }


# ----------------------------------------------------------------- compare


def test_compare_weighted_metrics(comparison_mesh_with_data, state_dir):
    grid, a, b = comparison_mesh_with_data
    out = t.compare(
        variable_name="temperature", data_path_a=a, data_path_b=b, grid_path=grid
    )
    _envelope(out)
    assert {"bias", "rmse", "pattern_correlation"} <= set(out["metrics"])
    assert "_payload" not in out and out["result_handle"]


# ------------------------------------------------------------------- remap


def test_remap_variable_to_target_grid(
    structured_mesh_files, remap_target_grid, state_dir
):
    grid, data = structured_mesh_files
    out = t.remap(
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
        target_grid_path=remap_target_grid,
    )
    _envelope(out)
    assert out["result_handle"] and out["source_coverage"]["coverage_fraction"] > 0
    assert "REMAP_METHOD_NOT_CONSERVATIVE" in out["warning_codes"]


def test_remap_outside_source_is_refused(
    synthetic_mesh_with_data, remap_target_grid, state_dir
):
    grid, data = synthetic_mesh_with_data  # spans lon 0..1; the target sits at 10.5
    out = t.remap(
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
        target_grid_path=remap_target_grid,
    )
    _refused(out, "remap_variable_nonzero")


# ------------------------------------------------------------------ subset


def test_subset_bbox_keeps_faces_and_persists(structured_mesh_files, state_dir):
    grid, data = structured_mesh_files
    out = t.subset(
        shape="bbox",
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
        lon_bounds=[-60, 60],
        lat_bounds=[-30, 30],
    )
    _envelope(out)
    assert 0 < out["coverage"]["n_face_retained"] < out["coverage"]["n_face_source"]
    assert out["result_handle"]


def test_subset_empty_box_refuses_with_extent(structured_mesh_files, state_dir):
    grid, _ = structured_mesh_files
    out = t.subset(
        shape="bbox", grid_path=grid, lon_bounds=[0.1, 0.2], lat_bounds=[0.1, 0.2]
    )
    _refused(out, "subset_bbox_nonzero")


# -------------------------------------------------------------------- plot


def test_plot_mesh_returns_image_and_metadata(structured_mesh_files, state_dir):
    grid, _ = structured_mesh_files
    blocks = t.plot(kind="mesh", grid_path=grid, title="t", width=400, height=200)
    assert blocks[0]["type"] == "image"
    meta = json.loads(blocks[1]["text"])
    assert meta["render_mode"] == "polygons" and meta["status"] == "complete"
    assert meta["image_path"].endswith(".png")
    assert meta["_provenance"]["artifacts"][0]["type"] == "plot"


def test_plot_field_rasterized_when_forced(healpix_files, state_dir):
    grid, data = healpix_files
    blocks = t.plot(
        kind="field",
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
        force_raster=True,
    )
    meta = json.loads(blocks[1]["text"])
    assert meta["render_mode"] in ("rasterized", "centers")


def test_plot_error_is_a_text_block_not_an_exception(state_dir):
    blocks = t.plot(kind="field", grid_path="healpix:1")
    payload = json.loads(blocks[0]["text"])
    assert payload["status"] == "error" and "data_path" in payload["message"]


# ------------------------------------------------------------------- export


def test_export_subset_to_netcdf(structured_mesh_files, state_dir, tmp_path):
    grid, data = structured_mesh_files
    sub = t.subset(
        shape="bbox",
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
        lon_bounds=[-60, 60],
        lat_bounds=[-30, 30],
    )
    out = t.export(
        output_path=str(tmp_path / "sub.nc"), result_handle=sub["result_handle"]
    )
    _envelope(out)
    assert (tmp_path / "sub.nc").exists()


# ------------------------------------------------------------------ session


def test_session_handles_replace_paths(structured_mesh_files, state_dir):
    grid, data = structured_mesh_files
    s = t.session(action="create", name="demo")
    d = t.session(
        action="register", session_id=s["session_id"], grid_path=grid, data_path=data
    )
    out = t.inspect_dataset(
        grid_path=None, session_id=s["session_id"], dataset_handle=d["dataset_handle"]
    )  # type: ignore[arg-type]
    assert out["grid_path"] == grid and out["data_path"] == data
    assert t.session(action="get", session_id=s["session_id"])["datasets"]


def test_unknown_handle_names_the_session(state_dir):
    s = t.session(action="create")
    with pytest.raises(FileNotFoundError, match="not in session"):
        t.compute(
            statistic="area",
            session_id=s["session_id"],
            dataset_handle="dataset_x",
            sphere_radius=EARTH,
        )


# ---------------------------------------------------------------- endpoint


def test_endpoint_status_without_config_is_honest(state_dir):
    out = t.endpoint(action="status")
    _envelope(out)
    assert out["endpoints"] == [] and out["default_endpoint"] is None


def test_remote_path_without_endpoint_is_a_clear_error(state_dir):
    with pytest.raises(FileNotFoundError, match="no endpoint claims"):
        t.compute(
            statistic="area", grid_path="/lcrc/does/not/exist.nc", sphere_radius=EARTH
        )


def test_plot_temporal_mean_over_files(structured_mesh_files, state_dir, tmp_path):
    import numpy as np
    import xarray as xr

    grid, data = structured_mesh_files
    n_face = xr.open_dataset(data)["temperature"].size
    paths = []
    for i in range(2):
        path = tmp_path / f"year{i}.nc"
        xr.Dataset(
            {
                "temperature": (
                    ["time", "n_face"],
                    np.full((3, n_face), 280.0 + i),
                    {"units": "K"},
                )
            },
            coords={"time": np.arange(3) + 3 * i},
        ).to_netcdf(path)
        paths.append(str(path))
    blocks = t.plot(
        kind="temporal_mean",
        grid_path=grid,
        data_paths=paths,
        variable_name="temperature",
        scale_factor=2.0,
        units_label="K2",
        lon_bounds=[-90, 90],
        lat_bounds=[-45, 45],
    )
    meta = json.loads(blocks[1]["text"])
    assert meta["status"] in ("complete", "warning"), meta
    assert meta["n_time_steps"] == 6 and meta["n_files"] == 2 and meta["units"] == "K2"
    assert meta["value_stats"]["mean"] == pytest.approx(561.0)  # (280+281)/2 * 2
    assert 0 < meta["n_faces_in_region"] < meta["n_faces_total"]


def test_plot_field_honours_a_crop(structured_mesh_files, state_dir):
    grid, data = structured_mesh_files
    blocks = t.plot(
        kind="field",
        grid_path=grid,
        data_path=data,
        variable_name="temperature",
        lon_bounds=[-60, 60],
        lat_bounds=[-30, 30],
    )
    meta = json.loads(blocks[1]["text"])
    assert 0 < meta["n_faces_in_region"] < meta["n_faces_total"]


def test_first_look_runs_area_zonal_and_plots(structured_mesh_files, state_dir):
    grid, data = structured_mesh_files
    out = t.inspect_dataset(grid_path=grid, data_path=data, first_look=True)
    _envelope(out)
    assert out["area"]["total_area"] > 0 and out["selected_variable"] == "temperature"
    assert len(out["zonal_mean"]["latitudes"]) > 3
    assert (
        set(out["plots"]) == {"mesh", "field"} and out["plots"]["field"]["image_path"]
    )


def test_remap_destination_reports_uxarray_limit(structured_mesh_files, state_dir):
    # UXarray can carry node data to faces but not yet faces to nodes; the
    # limitation must surface as its own message, not a generic failure.
    grid, data = structured_mesh_files
    with pytest.raises(NotImplementedError, match="face-centered"):
        t.remap(
            grid_path=grid,
            data_path=data,
            variable_name="temperature",
            destination="node",
        )


def test_guide_names_tool_calls_and_missing_args(state_dir):
    out = t.guide(topic="first_look", grid_path="g.nc")
    assert "inspect_dataset(" in out["plan"] and out["status"] == "complete"
    with pytest.raises(ValueError, match="u_variable"):
        t.guide(topic="vorticity", grid_path="g.nc", data_path="d.nc")
    with pytest.raises(ValueError, match="hpc_diagnose"):
        t.guide(topic="nonsense")
