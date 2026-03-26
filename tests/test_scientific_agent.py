"""Tests for the autonomous scientific agent tool."""

from unittest.mock import patch

from uxarray_mcp.tools.scientific_agent import (
    _decide_venue,
    _is_hpc_path,
    run_scientific_agent,
)


class TestIsHpcPath:
    def test_home_path(self):
        assert _is_hpc_path("/home/user/mesh.nc") is True

    def test_lus_path(self):
        assert _is_hpc_path("/lus/grand/mesh.nc") is True

    def test_scratch_path(self):
        assert _is_hpc_path("/scratch/user/mesh.nc") is True

    def test_projects_path(self):
        assert _is_hpc_path("/projects/atm/mesh.nc") is True

    def test_gpfs_path(self):
        assert _is_hpc_path("/gpfs/data/mesh.nc") is True

    def test_local_path(self):
        assert _is_hpc_path("mesh.nc") is False

    def test_healpix(self):
        assert _is_hpc_path("healpix:2") is False


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

    def test_at_threshold_is_local(self):
        # Threshold is > 1_000_000, so exactly 1M is local
        assert _decide_venue("mesh.nc", 1_000_000) == "local"

    def test_hpc_just_over_threshold(self):
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

    def test_larger_healpix_still_local(self):
        # healpix:5 has 12*4^5 = 12288 faces -- still under 1M threshold
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


class TestHpcPathRouting:
    """Tests for HPC path detection and remote routing in Stage 1."""

    @patch("uxarray_mcp.tools.remote_tools.inspect_mesh_hpc")
    def test_hpc_path_calls_remote_inspect(self, mock_inspect):
        """HPC paths should route to remote inspection, not local."""
        mock_inspect.return_value = {
            "n_face": 100,
            "n_node": 200,
            "n_edge": 300,
            "source": "/home/user/mesh.nc",
        }
        with patch("uxarray_mcp.tools.remote_tools.calculate_area_hpc") as mock_area:
            mock_area.return_value = {
                "total_area": 5.1e14,
                "mean_area": 1.0e7,
                "min_area": 1.0e6,
                "max_area": 2.0e7,
                "n_face": 100,
            }
            result = run_scientific_agent("/home/user/mesh.nc")

        assert result["execution_venue"] == "hpc"
        # Verify reasoning trace mentions HPC path detection
        trace_actions = [step.get("action", "") for step in result["reasoning_trace"]]
        assert any("HPC path" in a for a in trace_actions)

    def test_hpc_path_failure_returns_error(self):
        """If HPC inspection fails, return structured error, don't crash."""
        with patch(
            "uxarray_mcp.tools.remote_tools.inspect_mesh_hpc",
            side_effect=RuntimeError("Endpoint unreachable"),
        ):
            result = run_scientific_agent("/home/user/mesh.nc")

        assert result["verification"]["passed"] is False
        assert any(
            "unreachable" in w.lower() for w in result["verification"]["warnings"]
        )

    def test_local_path_does_not_use_hpc(self):
        """Local HEALPix paths should never touch HPC tools."""
        result = run_scientific_agent("healpix:2")
        trace_actions = [step.get("action", "") for step in result["reasoning_trace"]]
        assert not any("HPC" in a for a in trace_actions)


class TestHpcErrorHandling:
    """Tests for graceful HPC fallback during execution."""

    def test_hpc_area_failure_falls_back_to_local(self):
        """If HPC area calculation fails, fall back to local."""
        with (
            patch(
                "uxarray_mcp.tools.remote_tools.inspect_mesh_hpc",
                return_value={
                    "n_face": 100,
                    "n_node": 200,
                    "n_edge": 300,
                    "source": "/home/user/mesh.nc",
                },
            ),
            patch(
                "uxarray_mcp.tools.remote_tools.calculate_area_hpc",
                side_effect=RuntimeError("Globus timeout"),
            ),
            patch(
                "uxarray_mcp.tools.inspection.calculate_area",
                return_value={
                    "total_area": 5.1e14,
                    "mean_area": 1.0e7,
                    "min_area": 1.0e6,
                    "max_area": 2.0e7,
                    "n_face": 100,
                },
            ),
        ):
            result = run_scientific_agent("/home/user/mesh.nc")

        assert "fallback" in result["execution_venue"].lower()
        warnings_in_trace = [
            step for step in result["reasoning_trace"] if "warning" in step
        ]
        assert len(warnings_in_trace) > 0
