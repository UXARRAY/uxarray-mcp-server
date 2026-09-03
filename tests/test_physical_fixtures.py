"""Fixtures with a physical radius, a vertical coordinate, and a mask (#92).

Every other mesh in this suite sits on a unit sphere with a single level
and no missing data. That is fine for exercising code paths and hides
three classes of bug: on R=1 a wrong radius-scaling default is invisible
(#87 was exactly that), a wrong level selection is invisible when there
is only one level, and averaging over a mask is invisible when nothing
is masked. These tests exist to make each of the three visible.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import uxarray as ux

from uxarray_mcp.postconditions import mesh_is_closed
from uxarray_mcp.tools.frontdoor import run_analysis
from uxarray_mcp.tools.vector_calc import calculate_gradient

EARTH_RADIUS_M = 6371000.0


class TestPhysicalRadius:
    def test_grid_declares_earth_radius(self, earth_radius_mesh_files):
        grid_file, _ = earth_radius_mesh_files
        grid = ux.open_grid(grid_file)
        assert grid.sphere_radius == pytest.approx(EARTH_RADIUS_M)

    def test_radius_scaling_changes_the_answer(
        self, earth_radius_mesh_files, structured_mesh_files
    ):
        """The check #87 could not have failed on a unit sphere.

        Same mesh, same field, same default: dividing by R either happens
        or it does not, and only a physical radius makes the difference
        observable.
        """
        earth_grid, earth_data = earth_radius_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            scaled = calculate_gradient(earth_grid, earth_data, "u")
            unscaled = calculate_gradient(
                earth_grid, earth_data, "u", scale_by_radius=False
            )

        assert scaled["scale_by_radius"] is True
        scaled_max = scaled["component_stats"]["zonal_gradient"]["max"]
        unscaled_max = unscaled["component_stats"]["zonal_gradient"]["max"]
        assert unscaled_max / scaled_max == pytest.approx(EARTH_RADIUS_M, rel=1e-6)

    def test_unit_sphere_grid_warns_that_scaling_did_not_apply(
        self, structured_mesh_files
    ):
        grid_file, data_file = structured_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = calculate_gradient(grid_file, data_file, "temperature")
        joined = " ".join(result["component_warnings"])
        assert "sphere_radius" in joined

    def test_area_postcondition_reports_the_radius_it_saw(
        self, state_dir, earth_radius_mesh_files
    ):
        """A unit-sphere answer must not pass by a hidden unit-sphere reference.

        UXarray returns unscaled areas here, so ``4*pi`` is the right
        reference -- but the check has to say that the declared radius was
        not applied, otherwise the caller cannot tell which quantity it
        just verified.
        """
        grid_file, _ = earth_radius_mesh_files
        result = run_analysis(operation="calculate_area", grid_path=grid_file)

        check = result["postconditions"]["checks"][0]
        assert result["postconditions"]["status"] == "checked"
        assert check["passed"] is True
        assert check["reference"] == pytest.approx(4 * np.pi)
        assert "6.371e+06" in check["reference_source"]
        assert "not applied" in check["reference_source"]

    def test_open_mesh_gets_no_area_verdict(self, state_dir, regional_mesh_files):
        """``4*pi`` is not the reference for a mesh with a boundary."""
        grid_file, _ = regional_mesh_files
        result = run_analysis(operation="calculate_area", grid_path=grid_file)

        assert not mesh_is_closed(ux.open_grid(grid_file))
        assert result["postconditions"]["status"] == "not_evaluated"


class TestVerticalCoordinate:
    def test_variable_reports_all_levels(self, state_dir, multi_level_mesh_files):
        grid_file, data_file = multi_level_mesh_files
        result = run_analysis(
            operation="inspect_variable",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
        )
        variable = result["variables"][0]
        assert "n_level" in variable["dims"]
        assert variable["shape"][0] == 4

    def test_zonal_mean_discloses_the_collapsed_vertical_axis(
        self, state_dir, multi_level_mesh_files
    ):
        """A multi-level field must yield one profile *and* say what was dropped.

        Levels are 100/200/300/400. Returning all four rows made
        ``zonal_mean_values`` shape-unstable for every downstream consumer
        (plotting expects a line); returning one row without comment lets a
        caller believe a single level is the whole answer. So the result is
        the first level, and ``reduced_dims`` names the axis, the index used,
        and how many were available.
        """
        grid_file, data_file = multi_level_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_analysis(
                operation="calculate_zonal_mean",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
            )
        values = np.asarray(result["zonal_mean_values"], dtype=float)
        assert values.ndim == 1
        # Level 0 is uniform at 100.0, so every finite band equals it.
        finite = values[np.isfinite(values)]
        assert finite.size > 0
        assert finite == pytest.approx(100.0)
        # The collapse is disclosed, not silent.
        reduced = result["reduced_dims"]
        assert "n_level" in reduced, reduced
        # ``kind`` is what tells the caller which selector reaches this axis:
        # "level" means level_index, not time_index, moves it.
        assert reduced["n_level"] == {"kind": "level", "index": 0, "size": 4}

    def test_remote_zonal_mean_collapses_the_same_axis_as_local(
        self, state_dir, multi_level_mesh_files
    ):
        """The worker copy is inlined by hand, so it can drift from the local one.

        ``remote_calculate_zonal_mean`` cannot call the shared helper --
        Globus Compute serializes each function body standalone -- so the
        reduction logic exists twice. If the two ever disagree, the same
        request answers differently depending on where it ran, which is the
        worst kind of divergence to debug.
        """
        from uxarray_mcp.remote.compute_functions import remote_calculate_zonal_mean

        grid_file, data_file = multi_level_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            local = run_analysis(
                operation="calculate_zonal_mean",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="temperature",
            )
            remote = remote_calculate_zonal_mean(
                grid_file, data_file, "temperature", None, False
            )
        assert remote["reduced_dims"] == local["reduced_dims"]
        assert remote["latitudes"] == local["latitudes"]
        assert np.allclose(
            np.asarray(remote["zonal_mean_values"], dtype=float),
            np.asarray(local["zonal_mean_values"], dtype=float),
            equal_nan=True,
        )
        # The bin-coverage measurement is inlined in the worker for the same
        # reason, so it can drift the same way -- and a coverage block that
        # disagrees decides whether the front door refuses.
        assert remote["profile_coverage"] == local["profile_coverage"]


class TestMaskedField:
    def test_validation_reports_the_mask(self, state_dir, masked_mesh_files):
        grid_file, data_file = masked_mesh_files
        result = run_analysis(
            operation="validate_dataset", grid_path=grid_file, data_path=data_file
        )
        variable = result["variables"][0]
        assert result["passed"] is False
        assert variable["n_nan"] > 0
        assert variable["nan_percentage"] == pytest.approx(50.0, abs=5.0)

    def test_statistics_skip_the_mask_rather_than_averaging_over_it(
        self, state_dir, masked_mesh_files
    ):
        """Unmasked cells are all exactly 1.0, so any other mean folded in NaN."""
        grid_file, data_file = masked_mesh_files
        result = run_analysis(
            operation="inspect_variable",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="salinity",
        )
        stats = result["variables"][0]["statistics"]
        assert stats["mean"] == pytest.approx(1.0)
        assert stats["min"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(1.0)
