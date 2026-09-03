"""A binned profile that misses the mesh must not come back looking answered.

Before this gate, a regional mesh spanning 0-40N asked for bands at -70 and
-60 returned `[nan, nan]` with `outcome: complete`, `status: complete` and no
warning codes. `azimuthal_mean` centred a hundred degrees off the mesh did the
same, and even on-mesh returned 4 empty rings of 6 without saying so.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import uxarray as ux
import xarray as xr

from uxarray_mcp.domain.profile_coverage import (
    compute_profile_coverage,
    profile_coverage_warning_codes,
)
from uxarray_mcp.preconditions import OVERRIDE_TOKEN
from uxarray_mcp.tools.frontdoor import run_analysis

NAN = float("nan")


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
    return str(grid_file), str(data_file)


def _call(files, operation, **kwargs):
    grid_file, data_file = files
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_analysis(
            operation=operation,
            grid_path=grid_file,
            data_path=data_file,
            variable_name="t",
            **kwargs,
        )


class TestComputeProfileCoverage:
    def test_a_full_profile_reports_no_cause(self):
        coverage = compute_profile_coverage([1.0, 2.0, 3.0])

        assert coverage["n_bins_filled"] == 3
        assert coverage["cause"] == "none"
        assert profile_coverage_warning_codes(coverage) == []

    def test_empty_bins_over_a_complete_field_are_attributed_to_the_bins(self):
        source = np.array([1.0, 2.0, 3.0])

        coverage = compute_profile_coverage([NAN, 2.0], source=source)

        assert coverage["source_has_missing"] is False
        assert coverage["cause"] == "bins_miss_mesh"
        assert profile_coverage_warning_codes(coverage) == ["PROFILE_COVERAGE_PARTIAL"]

    def test_missing_data_in_the_field_leaves_the_cause_ambiguous(self):
        """Two explanations, so the measurement must not pick one."""
        source = np.array([1.0, NAN, 3.0])

        coverage = compute_profile_coverage([NAN, 2.0], source=source)

        assert coverage["source_has_missing"] is True
        assert coverage["cause"] == "ambiguous"

    def test_an_unsupplied_field_is_not_read_as_a_complete_one(self):
        coverage = compute_profile_coverage([NAN, 2.0])

        assert coverage["source_has_missing"] is None
        assert coverage["cause"] == "ambiguous"

    def test_a_wholly_empty_profile_has_its_own_code(self):
        coverage = compute_profile_coverage([NAN, NAN], source=np.array([1.0]))

        assert profile_coverage_warning_codes(coverage) == ["PROFILE_COVERAGE_ZERO"]

    def test_an_empty_profile_is_not_reported_as_covered(self):
        """Zero bins is zero measurements, not full coverage of nothing."""
        coverage = compute_profile_coverage([])

        assert coverage["n_bins"] == 0
        assert profile_coverage_warning_codes(coverage) == []


class TestZonalMeanCoverage:
    def test_bands_outside_the_mesh_refuse_without_a_profile(
        self, state_dir, regional_files
    ):
        result = _call(regional_files, "calculate_zonal_mean", lat_spec=[-70.0, -60.0])

        assert result["outcome"] == "input_required"
        assert [c["id"] for c in result["refusal"]["failed_checks"]] == [
            "profile_coverage_nonzero"
        ]
        assert "zonal_mean_values" not in result

    def test_the_repair_names_the_argument_the_caller_controls(
        self, state_dir, regional_files
    ):
        result = _call(regional_files, "calculate_zonal_mean", lat_spec=[-70.0, -60.0])

        repair = result["refusal"]["failed_checks"][0]["repair"]
        assert "lat_spec" in repair
        assert "outer_radius" not in repair

    def test_bands_on_the_mesh_complete_clean(self, state_dir, regional_files):
        result = _call(
            regional_files, "calculate_zonal_mean", lat_spec=[5.0, 15.0, 25.0]
        )

        assert result["outcome"] == "complete"
        assert result["scientific_status"]["warning_codes"] == []
        assert result["profile_coverage"]["cause"] == "none"

    def test_override_returns_the_empty_profile_marked_unverified(
        self, state_dir, regional_files
    ):
        result = _call(
            regional_files,
            "calculate_zonal_mean",
            lat_spec=[-70.0, -60.0],
            acknowledge=OVERRIDE_TOKEN,
        )

        assert result["preconditions"]["status"] == "overridden"
        assert result["scientific_status"]["physically_interpretable"] is False


class TestAzimuthalMeanCoverage:
    def test_a_centre_off_the_mesh_refuses(self, state_dir, regional_files):
        result = _call(
            regional_files,
            "azimuthal_mean",
            center_lon=-140.0,
            center_lat=-60.0,
            outer_radius=5.0,
            radius_step=1.0,
        )

        assert result["outcome"] == "input_required"
        assert [c["id"] for c in result["refusal"]["failed_checks"]] == [
            "profile_coverage_nonzero"
        ]

    def test_the_repair_names_the_centre_and_not_lat_spec(
        self, state_dir, regional_files
    ):
        result = _call(
            regional_files,
            "azimuthal_mean",
            center_lon=-140.0,
            center_lat=-60.0,
            outer_radius=5.0,
            radius_step=1.0,
        )

        repair = result["refusal"]["failed_checks"][0]["repair"]
        assert "center_lon" in repair
        assert "lat_spec" not in repair

    def test_the_worker_measures_coverage_the_same_way(self, state_dir, regional_files):
        """The worker copy is inlined by hand, so it can drift from the local one.

        Globus Compute serializes each remote function body standalone, so the
        measurement exists twice -- and it is the block that decides whether
        the front door refuses. A disagreement means the same request answers
        differently depending on where it ran.
        """
        from uxarray_mcp.remote.compute_functions import (
            remote_calculate_azimuthal_mean,
        )

        grid_file, data_file = regional_files
        kwargs = dict(
            center_lon=20.0, center_lat=20.0, outer_radius=5.0, radius_step=1.0
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            local = _call(regional_files, "azimuthal_mean", **kwargs)
            remote = remote_calculate_azimuthal_mean(
                grid_file, data_file, "t", **kwargs
            )

        assert remote["profile_coverage"] == local["profile_coverage"]

    def test_empty_rings_on_a_reachable_centre_warn_rather_than_refuse(
        self, state_dir, regional_files
    ):
        """Rings finer than the mesh leave gaps, and the caller should be told."""
        result = _call(
            regional_files,
            "azimuthal_mean",
            center_lon=20.0,
            center_lat=20.0,
            outer_radius=5.0,
            radius_step=1.0,
        )

        assert result["outcome"] == "complete"
        codes = result["scientific_status"]["warning_codes"]
        assert "PROFILE_COVERAGE_PARTIAL" in codes
        assert result["profile_coverage"]["n_bins_filled"] > 0
