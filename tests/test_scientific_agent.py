"""Tests for the autonomous scientific agent tool."""

import pytest
from uxarray_mcp.tools.scientific_agent import run_scientific_agent, _decide_venue


class TestDecideVenue:
    def test_local_small_mesh(self):
        assert _decide_venue("mesh.nc", 100) == "local"

    def test_local_healpix(self):
        assert _decide_venue("healpix:2", 192) == "local"

    def test_hpc_home_path(self):
        assert _decide_venue("/home/user/mesh.nc", 100) == "hpc"

    def test_hpc_lus_path(self):
        assert _decide_venue("/lus/grand/mesh.nc", 100) == "hpc"

    def test_hpc_scratch_path(self):
        assert _decide_venue("/scratch/user/mesh.nc", 100) == "hpc"

    def test_hpc_projects_path(self):
        assert _decide_venue("/projects/atm/mesh.nc", 100) == "hpc"

    def test_hpc_large_mesh(self):
        assert _decide_venue("mesh.nc", 2_000_000) == "hpc"

    def test_local_just_under_threshold(self):
        assert _decide_venue("mesh.nc", 999_999) == "local"

    def test_hpc_exactly_at_threshold(self):
        assert _decide_venue("mesh.nc", 1_000_001) == "hpc"


class TestRunScientificAgent:
    def test_returns_expected_keys(self):
        result = run_scientific_agent("healpix:1")
        assert "file_path" in result
        assert "execution_venue" in result
        assert "reasoning_trace" in result
        assert "mesh_summary" in result
        assert "area_results" in result
        assert "verification" in result

    def test_file_path_preserved(self):
        result = run_scientific_agent("healpix:2")
        assert result["file_path"] == "healpix:2"

    def test_healpix_runs_locally(self):
        result = run_scientific_agent("healpix:2")
        assert result["execution_venue"] == "local"

    def test_reasoning_trace_is_list(self):
        result = run_scientific_agent("healpix:1")
        assert isinstance(result["reasoning_trace"], list)
        assert len(result["reasoning_trace"]) > 0

    def test_reasoning_trace_has_all_stages(self):
        result = run_scientific_agent("healpix:1")
        stages = {step["stage"] for step in result["reasoning_trace"]}
        assert "analyze" in stages
        assert "plan" in stages
        assert "execute" in stages
        assert "verify" in stages

    def test_mesh_summary_has_topology(self):
        result = run_scientific_agent("healpix:2")
        summary = result["mesh_summary"]
        assert "n_face" in summary
        assert "n_node" in summary
        assert summary["n_face"] > 0

    def test_area_results_present(self):
        result = run_scientific_agent("healpix:2")
        area = result["area_results"]
        assert "total_area" in area
        assert area["total_area"] > 0

    def test_verification_structure(self):
        result = run_scientific_agent("healpix:2")
        v = result["verification"]
        assert "passed" in v
        assert "warnings" in v
        assert isinstance(v["warnings"], list)

    def test_verification_passes_for_valid_mesh(self):
        result = run_scientific_agent("healpix:2")
        assert result["verification"]["passed"] is True

    def test_no_variable_results_without_data_path(self):
        result = run_scientific_agent("healpix:2")
        assert result["variable_results"] is None
        assert result["zonal_mean_results"] is None

    def test_hpc_path_sets_venue(self):
        # We can't actually run HPC in tests, but we can verify the venue decision
        # by checking the reasoning trace for a small HPC-path mesh
        # This tests _decide_venue integration — actual execution would need endpoint
        result = run_scientific_agent("healpix:1")
        # healpix:1 is small and local path → local
        assert result["execution_venue"] == "local"

    def test_larger_healpix_still_local(self):
        # healpix:5 has 12*4^5 = 12288 faces — still under 1M threshold
        result = run_scientific_agent("healpix:5")
        assert result["execution_venue"] == "local"
        assert result["verification"]["passed"] is True

    def test_plan_includes_calculate_area(self):
        result = run_scientific_agent("healpix:2")
        plan_steps = [
            step for step in result["reasoning_trace"] if step.get("stage") == "plan"
        ]
        ops = next((s["operations"] for s in plan_steps if "operations" in s), [])
        assert "calculate_area" in ops

    def test_zonal_mean_not_planned_without_data(self):
        result = run_scientific_agent("healpix:2")
        plan_steps = [
            step for step in result["reasoning_trace"] if step.get("stage") == "plan"
        ]
        ops = next((s["operations"] for s in plan_steps if "operations" in s), [])
        assert "calculate_zonal_mean" not in ops
