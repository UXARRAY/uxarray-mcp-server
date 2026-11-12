"""Remapping ops in the pure core layer (uxarray backend only; YAC is -m yac)."""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.core.remap import regrid_dataset, remap_to_rectilinear, remap_variable


@pytest.fixture
def overlapping_target_grid(tmp_path):
    """Target mesh sitting inside the regional source mesh extent."""
    grid = ux.Grid.from_structured(
        lon=np.arange(42, 46, 1.0), lat=np.arange(-1, 2, 1.0)
    )
    path = tmp_path / "overlap.nc"
    grid.to_xarray().to_netcdf(path)
    return str(path)


@pytest.fixture(autouse=True)
def _quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def test_remap_variable_onto_overlapping_target_is_full_coverage(
    regional_mesh_files, overlapping_target_grid
):
    grid_file, data_file = regional_mesh_files
    result = remap_variable(
        grid_file, data_file, "temperature", overlapping_target_grid
    )
    assert result["variable_name"] == "temperature"
    assert result["method"] == "nearest_neighbor"
    assert result["backend"] == "uxarray"
    assert result["remap_to"] == "faces"
    coverage = result["source_coverage"]
    assert coverage["coverage_fraction"] == 1.0
    assert coverage["test"] == "point_in_cell"
    assert result["warning_codes"] == ["REMAP_METHOD_NOT_CONSERVATIVE"]
    assert result["target_grid"]["n_face"] == 12
    assert result["variable_summary"]["shape"] == [12]
    assert 0.1 <= result["variable_summary"]["mean"] <= 0.16
    assert isinstance(result["_payload"], ux.UxDataArray)


def test_remap_variable_onto_distant_target_is_zero_coverage(
    regional_mesh_files, remap_target_grid
):
    grid_file, data_file = regional_mesh_files
    result = remap_variable(grid_file, data_file, "temperature", remap_target_grid)
    assert result["coverage"]["points_in_source"] == 0
    assert "REMAP_COVERAGE_ZERO" in result["warning_codes"]
    assert any("REMAP_COVERAGE_ZERO" in w for w in result["warnings"])
    assert result["variable_summary"]["mean"] is not None


def test_regrid_dataset_remaps_every_face_variable(
    regional_mesh_files, overlapping_target_grid, tmp_path
):
    grid_file, data_file = regional_mesh_files
    result = regrid_dataset(grid_file, data_file, overlapping_target_grid)
    assert result["variables"] == ["temperature"]
    assert result["dataset_summary"]["dims"] == {"n_face": 12}
    assert result["source_coverage"]["coverage_fraction"] == 1.0
    assert isinstance(result["_payload"], xr.Dataset)
    no_face = tmp_path / "scalar.nc"
    xr.Dataset({"n": ((), 1.0)}).to_netcdf(no_face)
    with pytest.raises(ValueError, match="No face-centered"):
        regrid_dataset(grid_file, str(no_face), overlapping_target_grid)


def test_remap_to_rectilinear_shape_and_stats(structured_mesh_files):
    grid_file, data_file = structured_mesh_files
    result = remap_to_rectilinear(
        grid_file,
        data_file,
        "temperature",
        list(np.arange(0, 360, 30.0)),
        list(np.arange(-60, 61, 30.0)),
    )
    assert result["target_shape"] == [5, 12]
    assert result["result_dims"] == ["lat", "lon"]
    assert 250 <= result["stats"]["mean"] <= 280
    assert result["source_coverage"]["coverage_fraction"] >= 0.9
    assert "REMAP_COVERAGE_ZERO" not in result["warning_codes"]
    assert "REMAP_METHOD_NOT_CONSERVATIVE" in result["warning_codes"]
    payload = result["_payload"]
    assert isinstance(payload, xr.Dataset)
    assert payload["temperature"].shape == (5, 12)


def test_remap_to_rectilinear_off_mesh_is_zero_coverage(regional_mesh_files):
    grid_file, data_file = regional_mesh_files
    result = remap_to_rectilinear(
        grid_file,
        data_file,
        "temperature",
        list(np.arange(-180, 180, 72.0)),
        list(np.arange(-60, 61, 30.0)),
    )
    coverage = result["source_coverage"]
    assert coverage["n_target_points"] == 25
    assert coverage["points_in_source"] == 0
    assert result["warning_codes"] == [
        "REMAP_COVERAGE_ZERO",
        "REMAP_METHOD_NOT_CONSERVATIVE",
    ]


def test_bad_method_or_backend_is_refused(regional_mesh_files, remap_target_grid):
    grid_file, data_file = regional_mesh_files
    with pytest.raises(ValueError, match="Unsupported remap method"):
        remap_variable(grid_file, data_file, "temperature", remap_target_grid, "cubic")
    with pytest.raises(ValueError, match="requires backend='yac'"):
        remap_variable(
            grid_file, data_file, "temperature", remap_target_grid, yac_method="nnn"
        )
