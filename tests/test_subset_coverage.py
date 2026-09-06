"""A selection that kept nothing must not come back looking like a selection.

Before this gate, a bounding box at 160-170W / 70-80S applied to a mesh
covering 0-40E / 0-40N returned `outcome: complete`, `status: complete`, no
warning codes, a `subset_grid` of `n_face: 0`, a `variable_summary` of
`shape: [0]`, a persisted artifact and a recommended-next-steps list telling
the caller to plot it. `subset_polygon` did the same with
`selected_face_count: 0`. `cross_section` was the odd one out: UXarray raises
`ValueError("No intersections found at lat=-70.0")`, which is at least not
silent, but the message says the line found nothing without saying where a
line would find something.

Keeping *fewer* faces is not checked anywhere here. That is what a subset is
for, and a partial code would fire on every successful call.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.domain.subset_coverage import (
    compute_subset_coverage,
    mesh_extent,
    subset_coverage_warning_codes,
)
from uxarray_mcp.preconditions import OVERRIDE_TOKEN
from uxarray_mcp.tools.frontdoor import run_analysis

#: A box and a polygon in the South Pacific, nowhere near the fixture mesh.
OFF_MESH_LON = [-170.0, -160.0]
OFF_MESH_LAT = [-80.0, -70.0]
OFF_MESH_POLYGON = [[-170.0, -80.0], [-160.0, -80.0], [-160.0, -70.0]]


@pytest.fixture
def regional_files(tmp_path):
    """A mesh covering 0-40E, 0-40N and nothing else."""
    lon = np.arange(0.0, 41.0, 5.0)
    lat = np.arange(0.0, 41.0, 5.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_file = tmp_path / "regional.nc"
    grid.to_xarray().to_netcdf(grid_file)

    rng = np.random.default_rng(0)
    data_file = tmp_path / "t.nc"
    xr.Dataset(
        {"t": (["n_face"], 280.0 + rng.standard_normal(grid.n_face), {"units": "K"})}
    ).to_netcdf(data_file)
    return str(grid_file), str(data_file), grid


def _analyze(grid_file, data_file, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_analysis(
            grid_path=grid_file,
            data_path=data_file,
            variable_name="t",
            **kwargs,
        )


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


def test_coverage_reports_both_counts():
    assert compute_subset_coverage(81, 9) == {
        "n_face_source": 81,
        "n_face_retained": 9,
    }


def test_an_extent_is_carried_when_it_was_measured():
    extent = {"lon_min": 0.0, "lon_max": 40.0, "lat_min": 0.0, "lat_max": 40.0}
    coverage = compute_subset_coverage(81, 9, extent=extent)
    assert coverage["source_extent"] == extent


def test_a_grid_without_coordinates_has_no_extent():
    class Bare:
        pass

    assert mesh_extent(Bare()) is None


def test_an_empty_grid_has_no_extent():
    class Empty:
        face_lon = np.array([])
        face_lat = np.array([])

    assert mesh_extent(Empty()) is None


def test_a_grid_of_only_missing_coordinates_has_no_extent():
    class AllNaN:
        face_lon = np.array([np.nan, np.nan])
        face_lat = np.array([np.nan, np.nan])

    assert mesh_extent(AllNaN()) is None


def test_the_extent_ignores_missing_coordinates():
    class Partial:
        face_lon = np.array([0.0, np.nan, 10.0])
        face_lat = np.array([5.0, np.nan, 15.0])

    assert mesh_extent(Partial()) == {
        "lon_min": 0.0,
        "lon_max": 10.0,
        "lat_min": 5.0,
        "lat_max": 15.0,
    }


# ---------------------------------------------------------------------------
# The codes
# ---------------------------------------------------------------------------


def test_a_selection_that_kept_faces_warns_about_nothing():
    assert subset_coverage_warning_codes(compute_subset_coverage(81, 1)) == []


def test_an_empty_selection_is_zero_coverage():
    codes = subset_coverage_warning_codes(compute_subset_coverage(81, 0))
    assert codes == ["SUBSET_COVERAGE_ZERO"]


def test_an_empty_source_yields_no_codes():
    assert subset_coverage_warning_codes(compute_subset_coverage(0, 0)) == []


# ---------------------------------------------------------------------------
# End to end through the front door
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("operation", "kwargs", "argument"),
    [
        (
            "subset_bbox",
            {"lon_bounds": OFF_MESH_LON, "lat_bounds": OFF_MESH_LAT},
            "lon_bounds/lat_bounds",
        ),
        (
            "subset_polygon",
            {"polygon_lon_lat": OFF_MESH_POLYGON},
            "polygon_lon_lat",
        ),
        ("cross_section", {"latitude": -70.0}, "latitude/longitude"),
    ],
)
def test_an_off_mesh_selection_refuses_with_the_mesh_extent(
    regional_files, operation, kwargs, argument
):
    grid_file, data_file, grid = regional_files
    result = _analyze(grid_file, data_file, operation=operation, **kwargs)

    assert result["outcome"] == "input_required"
    failed = result["refusal"]["failed_checks"]
    assert [check["id"] for check in failed] == ["subset_retains_faces"]
    assert f"0 of {grid.n_face} faces selected" in failed[0]["detail"]
    repair = failed[0]["repair"]
    assert argument in repair
    # The extent is the whole point: "nothing selected" does not tell a caller
    # where to put the box, and the -180..180 / 0..360 mix-up is the most
    # likely way to arrive here.
    assert "longitude 0 to 40" in repair
    assert "0..360" in repair


@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [
        ("subset_bbox", {"lon_bounds": [5.0, 15.0], "lat_bounds": [5.0, 15.0]}),
        (
            "subset_polygon",
            {"polygon_lon_lat": [[5.0, 5.0], [25.0, 5.0], [25.0, 25.0]]},
        ),
        ("cross_section", {"latitude": 20.0}),
    ],
)
def test_an_on_mesh_selection_completes_and_reports_what_it_kept(
    regional_files, operation, kwargs
):
    grid_file, data_file, grid = regional_files
    result = _analyze(grid_file, data_file, operation=operation, **kwargs)

    assert result["outcome"] == "complete"
    coverage = result["subset_coverage"]
    assert coverage["n_face_source"] == grid.n_face
    assert 0 < coverage["n_face_retained"] < grid.n_face
    # Selecting a region is a choice, not a physical claim, so the server does
    # not certify it either way.
    assert result["scientific_status"]["physically_interpretable"] is None
    assert result["scientific_status"]["warning_codes"] == []


def test_a_cross_section_that_misses_no_longer_raises(regional_files):
    """UXarray raises here; the front door turns it into the refusal shape."""
    grid_file, data_file, _ = regional_files
    result = _analyze(grid_file, data_file, operation="cross_section", longitude=-170.0)
    assert result["outcome"] == "input_required"


def test_an_unrelated_value_error_still_propagates(regional_files):
    grid_file, data_file, _ = regional_files
    with pytest.raises(ValueError, match="exactly one of latitude or longitude"):
        _analyze(grid_file, data_file, operation="cross_section")


def test_the_override_returns_the_empty_selection_without_claiming_it(
    regional_files,
):
    grid_file, data_file, _ = regional_files
    result = _analyze(
        grid_file,
        data_file,
        operation="subset_bbox",
        lon_bounds=OFF_MESH_LON,
        lat_bounds=OFF_MESH_LAT,
        acknowledge=OVERRIDE_TOKEN,
    )

    assert result["outcome"] == "complete"
    assert result["preconditions"]["status"] == "overridden"
    assert result["subset_grid"]["n_face"] == 0
    assert result["scientific_status"]["physically_interpretable"] is False
