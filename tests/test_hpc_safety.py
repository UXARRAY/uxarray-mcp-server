"""Safety net tests for the HPC execution layer.

Covers health checks, pre-flight readiness, fallback behaviour,
validate_dataset, and provenance correctness. These must pass before
and after any refactor so the HPC path stays intact.
"""

import importlib.util
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from uxarray_mcp.remote import health
from uxarray_mcp.remote.compute_functions import remote_yac_remap_smoke
from uxarray_mcp.remote.config import HPCConfig
from uxarray_mcp.remote.health import check_endpoint_health
from uxarray_mcp.tools.inspection import validate_dataset
from uxarray_mcp.tools.remote_tools import (
    _endpoint_is_ready,
    calculate_area,
    inspect_mesh,
)

globus_available = importlib.util.find_spec("globus_compute_sdk") is not None
requires_globus = pytest.mark.skipif(
    not globus_available, reason="globus_compute_sdk not installed (HPC extra required)"
)


@pytest.fixture(autouse=True)
def _reset_health_module_cache():
    """Reset the cached Globus Compute Client + health cache between tests."""
    health.invalidate_cache()
    health._CLIENT = None
    yield
    health.invalidate_cache()
    health._CLIENT = None


# -----------------------------------------------------------------------------
# Unit Tests (Mocked) — check_endpoint_health
# -----------------------------------------------------------------------------


class TestCheckEndpointHealth:
    """Tests for endpoint health checking."""

    def test_no_endpoint_configured(self):
        """Returns no_endpoint immediately when endpoint_id is None."""
        config = HPCConfig(endpoint_id=None)
        result = check_endpoint_health(config)
        assert result["status"] == "no_endpoint"
        assert "message" in result

    @requires_globus
    def test_healthy_endpoint(self):
        """Returns 'registered' when Globus SDK reports the endpoint manager is up."""
        config = HPCConfig(endpoint_id="fake-uuid-1234", execution_mode="hpc")
        mock_client = MagicMock()
        mock_client.get_endpoint_status.return_value = {"status": "online"}

        with patch("globus_compute_sdk.Client", return_value=mock_client):
            result = check_endpoint_health(config)

        assert result["status"] == "registered"
        assert result["endpoint_configured"] is True

    @requires_globus
    def test_unreachable_endpoint(self):
        """Returns unreachable with error message when Globus SDK raises."""
        config = HPCConfig(endpoint_id="fake-uuid-1234", execution_mode="hpc")

        with patch(
            "globus_compute_sdk.Client", side_effect=Exception("Connection refused")
        ):
            result = check_endpoint_health(config)

        assert result["status"] == "unreachable"
        assert result["endpoint_configured"] is True
        assert "error" in result

    @requires_globus
    def test_globus_offline_maps_to_offline(self):
        """Globus 'stopped'/'offline' maps to our 'offline' status."""
        config = HPCConfig(endpoint_id="fake-uuid-1234", execution_mode="hpc")
        mock_client = MagicMock()
        mock_client.get_endpoint_status.return_value = {"status": "stopped"}

        with patch("globus_compute_sdk.Client", return_value=mock_client):
            result = check_endpoint_health(config)

        assert result["status"] == "offline"

    def test_yac_pythonpath_is_expected_runtime_path(self):
        """Endpoint-side YAC source/runtime paths are not a worker leak."""
        pythonpath = (
            "/home/testuser/src/yac/build/python:"
            "/home/testuser/local/yac-3.17/lib/python3.12/site-packages:"
            "/lcrc/group/e3sm/jain/uxarray-yac-src"
        )

        assert health._is_expected_yac_pythonpath(pythonpath) is True

    def test_conda_env_pythonpath_is_not_expected_yac_runtime_path(self):
        """A broad conda env site-packages path can still leak pydantic/dill."""
        pythonpath = (
            "/home/testuser/.conda/envs/uxarray-yac/lib/python3.12/site-packages"
        )

        assert health._is_expected_yac_pythonpath(pythonpath) is False

    def test_remote_yac_smoke_parses_subprocess_payload(self, monkeypatch):
        """YAC smoke returns structured output from the worker-side subprocess."""
        payload = {
            "yac_helper_ok": True,
            "remap_ok": True,
            "remap_dst_shape": [768],
        }

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, f"0: {json.dumps(payload)}", "")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = remote_yac_remap_smoke()

        assert result["subprocess_ok"] is True
        assert result["subprocess_returncode"] == 0
        assert result["yac_helper_ok"] is True
        assert result["remap_dst_shape"] == [768]


# -----------------------------------------------------------------------------
# Unit Tests (Mocked) — _endpoint_is_ready
# -----------------------------------------------------------------------------


class TestEndpointIsReady:
    """Tests for the pre-flight check used before every HPC job submission."""

    def _make_agent(self, endpoint_id=None):
        from uxarray_mcp.remote.agent import UXarrayComputeAgent

        config = HPCConfig(endpoint_id=endpoint_id, execution_mode="hpc")
        return UXarrayComputeAgent(config)

    def test_no_endpoint_returns_not_ready(self):
        """Returns (False, reason) immediately when no endpoint is configured."""
        agent = self._make_agent(endpoint_id=None)
        ready, reason = _endpoint_is_ready(agent)
        assert ready is False
        assert "no_endpoint" in reason

    @requires_globus
    def test_healthy_endpoint_returns_ready(self):
        """Returns (True, 'ok') when the endpoint reports online."""
        agent = self._make_agent(endpoint_id="fake-uuid")
        mock_client = MagicMock()
        mock_client.get_endpoint_status.return_value = {"status": "online"}

        with patch("globus_compute_sdk.Client", return_value=mock_client):
            ready, reason = _endpoint_is_ready(agent)

        assert ready is True
        assert reason == "ok"

    @requires_globus
    def test_unreachable_endpoint_returns_not_ready(self):
        """Returns (False, reason) when the Globus SDK raises an exception."""
        agent = self._make_agent(endpoint_id="fake-uuid")

        with patch("globus_compute_sdk.Client", side_effect=Exception("timeout")):
            ready, reason = _endpoint_is_ready(agent)

        assert ready is False
        assert "unreachable" in reason


# -----------------------------------------------------------------------------
# Unit Tests (Mocked) — inspect_mesh routing and fallback
# -----------------------------------------------------------------------------


class TestInspectMeshHpcUnit:
    """Unit tests for inspect_mesh routing and fallback logic."""

    def test_no_endpoint_falls_back_to_local(self, synthetic_mesh_file):
        """Falls back to local when use_remote=True but no endpoint is configured."""
        with patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.config.has_endpoint = False
            mock_get_agent.return_value = mock_agent

            result = inspect_mesh(synthetic_mesh_file, use_remote=True)

        assert "n_face" in result
        assert "_provenance" in result

    def test_unhealthy_endpoint_falls_back_and_warns(self, synthetic_mesh_file):
        """Falls back to local and adds a warning when the health check fails."""
        with (
            patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent,
            patch(
                "uxarray_mcp.tools.remote_tools._endpoint_is_ready",
                return_value=(False, "endpoint status='stopped': "),
            ),
        ):
            mock_agent = MagicMock()
            mock_agent.config.has_endpoint = True
            mock_get_agent.return_value = mock_agent

            result = inspect_mesh(synthetic_mesh_file, use_remote=True)

        assert "n_face" in result
        warnings = result["_provenance"]["warnings"]
        assert any("HPC endpoint not ready" in w for w in warnings)

    def test_provenance_always_attached(self):
        """Every inspect_mesh result carries a _provenance block."""
        result = inspect_mesh("healpix:2", use_remote=False)
        assert "_provenance" in result
        prov = result["_provenance"]
        assert "tool" in prov
        assert "execution_venue" in prov
        assert "timestamp_utc" in prov
        assert isinstance(prov["warnings"], list)


# -----------------------------------------------------------------------------
# Unit Tests (Mocked) — validate_dataset error handling
# -----------------------------------------------------------------------------


class TestValidateDatasetUnit:
    """Unit tests for validate_dataset error handling."""

    def test_missing_grid_file_raises(self, tmp_path):
        """Raises FileNotFoundError when the grid file does not exist."""
        with pytest.raises(FileNotFoundError, match="Grid file not found"):
            validate_dataset("/nonexistent/grid.nc", "/nonexistent/data.nc")

    def test_missing_data_file_raises(self, synthetic_mesh_file):
        """Raises FileNotFoundError when the data file does not exist."""
        with pytest.raises(FileNotFoundError, match="Data file not found"):
            validate_dataset(synthetic_mesh_file, "/nonexistent/data.nc")


# -----------------------------------------------------------------------------
# Unit Tests (Mocked) — HPC fallback provenance correctness
# -----------------------------------------------------------------------------


class TestHpcFallbackProvenance:
    """When HPC is unavailable, provenance must say 'local' and include a warning."""

    def test_fallback_venue_is_local(self, synthetic_mesh_file):
        """execution_venue is 'local' in provenance after an HPC fallback."""
        with (
            patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent,
            patch(
                "uxarray_mcp.tools.remote_tools._endpoint_is_ready",
                return_value=(False, "endpoint status='stopped': "),
            ),
        ):
            mock_agent = MagicMock()
            mock_agent.config.has_endpoint = True
            mock_get_agent.return_value = mock_agent

            result = calculate_area(synthetic_mesh_file, use_remote=True)

        assert result["_provenance"]["execution_venue"] == "local"

    def test_fallback_warning_present(self, synthetic_mesh_file):
        """A warning about the fallback is recorded in provenance."""
        with (
            patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent,
            patch(
                "uxarray_mcp.tools.remote_tools._endpoint_is_ready",
                return_value=(False, "endpoint status='stopped': "),
            ),
        ):
            mock_agent = MagicMock()
            mock_agent.config.has_endpoint = True
            mock_get_agent.return_value = mock_agent

            result = calculate_area(synthetic_mesh_file, use_remote=True)

        warnings = result["_provenance"]["warnings"]
        assert any("HPC endpoint not ready" in w for w in warnings)


# -----------------------------------------------------------------------------
# Unit Tests (Mocked) — Issue #27: clear error for HPC-only paths
# -----------------------------------------------------------------------------


class TestRemoteOnlyPathRaisesClearError:
    """When use_remote=True and the path is not reachable locally, the
    dispatcher must raise a clear endpoint-state error instead of falling
    through to a local read that raises a misleading FileNotFoundError.
    """

    REMOTE_ONLY_PATH = "/lus/grand/projects/does-not-exist-locally/grid.nc"

    def test_no_endpoint_remote_only_path_raises(self):
        """No endpoint + remote-only path → RuntimeError, not FileNotFoundError."""
        with patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.config.endpoint_id = None
            mock_get_agent.return_value = mock_agent

            with pytest.raises(RuntimeError, match="no HPC endpoint is configured"):
                inspect_mesh(self.REMOTE_ONLY_PATH, use_remote=True)

    def test_endpoint_not_ready_remote_only_path_raises(self):
        """Endpoint unhealthy + remote-only path → RuntimeError naming the reason."""
        with (
            patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent,
            patch(
                "uxarray_mcp.tools.remote_tools._endpoint_is_ready",
                return_value=(False, "endpoint status='stopped': "),
            ),
        ):
            mock_agent = MagicMock()
            mock_agent.config.endpoint_id = "fake-uuid"
            mock_get_agent.return_value = mock_agent

            with pytest.raises(RuntimeError, match="HPC endpoint not ready"):
                inspect_mesh(self.REMOTE_ONLY_PATH, use_remote=True)

    def test_no_endpoint_local_path_still_falls_back(self, synthetic_mesh_file):
        """Existing convenience: a path that exists locally still falls back."""
        with patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.config.endpoint_id = None
            mock_get_agent.return_value = mock_agent

            result = inspect_mesh(synthetic_mesh_file, use_remote=True)

        assert "n_face" in result
        assert result["_provenance"]["execution_venue"] == "local"

    def test_no_endpoint_healpix_spec_still_falls_back(self):
        """HEALPix pseudo-paths must keep working when no endpoint is configured."""
        with patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.config.endpoint_id = None
            mock_get_agent.return_value = mock_agent

            result = inspect_mesh("healpix:2", use_remote=True)

        assert result["n_face"] == 192


# -----------------------------------------------------------------------------
# Integration Tests (Real Data)
# -----------------------------------------------------------------------------


def test_inspect_mesh_healpix():
    """Integration test: inspect_mesh runs locally on a HEALPix mesh."""
    result = inspect_mesh("healpix:2", use_remote=False)
    assert result["n_face"] == 192
    assert result["n_node"] > 0
    assert "_provenance" in result


def test_validate_dataset_clean_data(synthetic_mesh_with_data):
    """Integration test: clean dataset passes all validation checks."""
    grid_file, data_file = synthetic_mesh_with_data
    result = validate_dataset(grid_file, data_file)

    assert result["passed"] is True
    assert result["n_variables_failed"] == 0
    assert result["n_variables_checked"] > 0


def test_validate_dataset_per_variable_entries(synthetic_mesh_with_data):
    """Integration test: every variable in the dataset gets a result entry."""
    grid_file, data_file = synthetic_mesh_with_data
    result = validate_dataset(grid_file, data_file)

    assert len(result["variables"]) == result["n_variables_checked"]
    for var in result["variables"]:
        assert "name" in var
        assert "passed" in var
        assert "n_nan" in var
        assert "n_inf" in var


def test_validate_dataset_provenance(synthetic_mesh_with_data):
    """Integration test: validate_dataset result always carries _provenance."""
    grid_file, data_file = synthetic_mesh_with_data
    result = validate_dataset(grid_file, data_file)

    assert "_provenance" in result
    assert result["_provenance"]["tool"] == "validate_dataset"
    assert isinstance(result["_provenance"]["warnings"], list)


# -----------------------------------------------------------------------------
# Worker-version provenance + drift warning
# -----------------------------------------------------------------------------


class TestWorkerVersionProvenance:
    """All compute/analysis remote functions report the worker's UXarray version,
    and _run_on_hpc surfaces it plus a drift warning."""

    def test_every_remote_function_emits_worker_runtime(self):
        """Every remote_* function must report the worker's runtime envelope.

        Enumerated by reflection rather than a hand-maintained list: the old
        list silently omitted the plot functions and remote_probe_path, so
        their results carried the submitter's Python version instead of the
        worker's.
        """
        import inspect as _inspect

        from uxarray_mcp.remote import compute_functions as cf

        remote_funcs = [
            name
            for name in dir(cf)
            if name.startswith("remote_") and callable(getattr(cf, name))
        ]
        assert remote_funcs, "no remote_* functions discovered"

        missing = [
            name
            for name in remote_funcs
            if "_worker_runtime" not in _inspect.getsource(getattr(cf, name))
        ]
        assert not missing, (
            f"{len(missing)} remote function(s) do not emit _worker_runtime: "
            f"{sorted(missing)}"
        )

    def test_worker_runtime_envelope_reports_python_and_host(self):
        """The envelope must carry the worker's Python version and hostname."""
        import inspect as _inspect

        from uxarray_mcp.remote import compute_functions as cf

        remote_funcs = [
            name
            for name in dir(cf)
            if name.startswith("remote_") and callable(getattr(cf, name))
        ]
        for name in remote_funcs:
            src = _inspect.getsource(getattr(cf, name))
            assert "python_version" in src, f"{name} omits worker python_version"
            assert "hostname" in src, f"{name} omits worker hostname"

    @requires_globus
    def test_run_on_hpc_surfaces_worker_version_and_drift(self):
        """_run_on_hpc records remote_uxarray_version and warns on drift."""
        import asyncio

        from uxarray_mcp.remote.agent import UXarrayComputeAgent
        from uxarray_mcp.remote.config import HPCConfig

        agent = UXarrayComputeAgent(
            HPCConfig(endpoint_id="fake", endpoint_name="test", execution_mode="hpc")
        )

        # Fake executor: returns a payload with a worker version that differs
        # from whatever is installed locally.
        class _Fut:
            def result(self, timeout=None):
                return {
                    "n_face": 1,
                    "_worker_uxarray_version": "0.0.0-worker-different",
                    "_worker_python_version": "3.11.12",
                }

        class _Exec:
            def submit(self, func, *a, **k):
                return _Fut()

        agent._executor = _Exec()

        def _fake_func():
            return None

        _fake_func.__name__ = "remote_inspect_mesh"
        result = asyncio.run(agent._run_on_hpc(_fake_func))

        prov = result["_provenance"]
        assert prov["remote_uxarray_version"] == "0.0.0-worker-different"
        assert prov["remote_python_version"] == "3.11.12"
        assert any("drift" in w for w in prov["warnings"])
        # Internal key must not leak into the user-facing result.
        assert "_worker_uxarray_version" not in result


class TestWorkerRuntimeProvenancePromotion:
    """A remote result must describe the worker, not the laptop that submitted it."""

    @staticmethod
    def _run(payload):
        import asyncio

        from uxarray_mcp.remote.agent import UXarrayComputeAgent

        agent = UXarrayComputeAgent(
            HPCConfig(
                endpoint_id="fake", endpoint_name="chrysalis", execution_mode="hpc"
            )
        )

        class _Fut:
            def result(self, timeout=None):
                return dict(payload)

        class _Exec:
            def submit(self, func, *a, **k):
                return _Fut()

        agent._executor = _Exec()

        def _fake_func():
            return None

        _fake_func.__name__ = "remote_inspect_mesh"
        return asyncio.run(agent._run_on_hpc(_fake_func))

    @requires_globus
    def test_worker_runtime_overwrites_submitter_python_version(self):
        result = self._run(
            {
                "n_face": 1,
                "_worker_runtime": {
                    "hostname": "chr-0123",
                    "python_version": "3.12.13",
                    "uxarray_version": "2026.6.0",
                    "slurm_job_id": "987654",
                },
            }
        )
        prov = result["_provenance"]

        # Top-level runtime fields describe the machine that did the work.
        assert prov["python_version"] == "3.12.13"
        assert prov["remote_hostname"] == "chr-0123"
        assert prov["remote_slurm_job_id"] == "987654"
        # The submitter's own interpreter is preserved, not silently dropped.
        assert prov["submitter_python_version"] != "3.12.13"
        assert "_worker_runtime" not in result

    @requires_globus
    def test_matching_versions_do_not_add_submitter_keys(self):
        import platform

        result = self._run(
            {
                "n_face": 1,
                "_worker_runtime": {
                    "hostname": "chr-0123",
                    "python_version": platform.python_version(),
                },
            }
        )
        prov = result["_provenance"]

        # Nothing drifted, so there is no second version worth reporting.
        assert "submitter_python_version" not in prov
        assert prov["python_version"] == platform.python_version()


def _two_cluster_config() -> HPCConfig:
    """improv claims a prefix; chrysalis is the default and claims nothing."""
    from uxarray_mcp.remote.config import EndpointProfile

    return HPCConfig(
        endpoints={
            "improv": EndpointProfile(
                name="improv", endpoint_id="a", path_prefixes=("/gpfs/fs1/",)
            ),
            "chrysalis": EndpointProfile(name="chrysalis", endpoint_id="b"),
        },
        default_endpoint="chrysalis",
    )


class TestDefaultRouteIsDisclosed:
    """Falling through to the default endpoint must not look deliberate."""

    def test_unclaimed_path_is_flagged_as_a_guess(self):
        config = _two_cluster_config()
        scoped = config.for_endpoint(path="/lcrc/group/e3sm/data/grid.nc")

        assert scoped.endpoint_name == "chrysalis"
        assert scoped.routed_by_default_guess is True

    def test_prefix_match_is_not_flagged(self):
        config = _two_cluster_config()
        scoped = config.for_endpoint(path="/gpfs/fs1/home/testuser/grid.nc")

        assert scoped.endpoint_name == "improv"
        assert scoped.routed_by_default_guess is False

    def test_explicit_endpoint_is_not_flagged(self):
        config = _two_cluster_config()
        scoped = config.for_endpoint(
            endpoint="chrysalis", path="/lcrc/group/e3sm/grid.nc"
        )

        assert scoped.routed_by_default_guess is False

    @requires_globus
    def test_guess_surfaces_as_a_provenance_warning(self):
        import asyncio

        from uxarray_mcp.remote.agent import UXarrayComputeAgent

        config = HPCConfig(
            endpoint_id="b", endpoint_name="chrysalis", execution_mode="hpc"
        )
        config.routed_by_default_guess = True
        agent = UXarrayComputeAgent(config)

        class _Fut:
            def result(self, timeout=None):
                return {"n_face": 1}

        class _Exec:
            def submit(self, func, *a, **k):
                return _Fut()

        agent._executor = _Exec()

        def _fake_func():
            return None

        _fake_func.__name__ = "remote_inspect_mesh"
        prov = asyncio.run(agent._run_on_hpc(_fake_func))["_provenance"]

        assert any("configured default" in w for w in prov["warnings"])


class TestRemoteErrorNormalization:
    """Worker tracebacks must not be forwarded verbatim into an agent's context."""

    def test_missing_file_traceback_collapses_to_one_line(self):
        from uxarray_mcp.remote.agent import _normalize_remote_error

        traceback_text = (
            "Traceback (most recent call last):\n"
            + "".join(
                f'  File "/lcrc/sw/lib/python3.12/frame{i}.py", line {i}, in load\n'
                f"    return _open(path)\n"
                for i in range(40)
            )
            + "FileNotFoundError: [Errno 2] No such file or directory: "
            "'/lcrc/group/e3sm/nope.nc'\n"
        )
        config = HPCConfig(endpoint_id="b", endpoint_name="chrysalis")

        normalized = _normalize_remote_error(Exception(traceback_text), config)

        assert isinstance(normalized, FileNotFoundError)
        message = str(normalized)
        assert len(traceback_text) > 2000
        assert len(message) < 300
        assert "/lcrc/group/e3sm/nope.nc" in message
        assert "chrysalis" in message
        assert "Traceback" not in message
        assert "probe_path_access" in message

    def test_unknown_long_failure_keeps_only_the_cause_line(self):
        from uxarray_mcp.remote.agent import _normalize_remote_error

        text = (
            "Traceback:\n" + ("  frame padding line\n" * 200) + "ValueError: bad mesh"
        )
        config = HPCConfig(endpoint_id="b", endpoint_name="ucar-uxarray-yac")

        normalized = _normalize_remote_error(Exception(text), config)

        assert "ValueError: bad mesh" in str(normalized)
        assert len(str(normalized)) < 200
        assert "ucar-uxarray-yac" in str(normalized)

    def test_short_errors_pass_through_untouched(self):
        from uxarray_mcp.remote.agent import _normalize_remote_error

        original = ValueError("endpoint offline")
        config = HPCConfig(endpoint_id="b", endpoint_name="chrysalis")

        assert _normalize_remote_error(original, config) is original

    def test_timeout_is_preserved_for_callers_that_branch_on_it(self):
        from uxarray_mcp.remote.agent import _normalize_remote_error

        original = TimeoutError("x" * 900)
        config = HPCConfig(endpoint_id="b", endpoint_name="chrysalis")

        assert _normalize_remote_error(original, config) is original


class TestCheckRemoteYacTool:
    """The YAC smoke test is reachable as a tool, not just a standalone script."""

    @staticmethod
    def _patch_executor(monkeypatch, payload):
        """Point check_remote_yac at a fake worker returning ``payload``."""
        from uxarray_mcp.remote.config import EndpointProfile
        from uxarray_mcp.tools import execution_control

        config = HPCConfig(
            endpoints={
                "chrysalis": EndpointProfile(name="chrysalis", endpoint_id="fake-uuid")
            },
            default_endpoint="chrysalis",
        )
        monkeypatch.setattr(
            execution_control, "_load_config_for_tools", lambda: (config, None)
        )

        class _Fut:
            def result(self, timeout=None):
                if isinstance(payload, Exception):
                    raise payload
                return dict(payload)

        class _Exec:
            def __init__(self, *a, **k):
                pass

            def submit(self, func, *a, **k):
                return _Fut()

        monkeypatch.setattr(
            execution_control,
            "_load_globus_compute_sdk",
            lambda: (MagicMock(), _Exec, MagicMock(), MagicMock()),
        )
        return execution_control

    def test_working_yac_reports_available(self, monkeypatch):
        ec = self._patch_executor(
            monkeypatch,
            {
                "subprocess_ok": True,
                "yac_helper_ok": True,
                "remap_ok": True,
                "remap_seconds": 1.2,
                "_worker_runtime": {"hostname": "chr-0007", "slurm_job_id": "42"},
            },
        )

        result = ec.check_remote_yac(endpoint="chrysalis")

        assert result["available"] is True
        assert result["_provenance"]["remote_hostname"] == "chr-0007"
        assert result["_provenance"]["remote_slurm_job_id"] == "42"
        assert result["_provenance"]["execution_venue"] == "hpc"

    def test_importable_but_broken_remap_is_not_available(self, monkeypatch):
        """yac.core importing is not a promise that a remap actually works."""
        ec = self._patch_executor(
            monkeypatch,
            {
                "subprocess_ok": False,
                "yac_core_ok": True,
                "yac_helper_ok": True,
                "remap_ok": False,
                "remap_error": "RuntimeError: MPI_Init failed",
            },
        )

        result = ec.check_remote_yac(endpoint="chrysalis")

        assert result["available"] is False
        assert "MPI_Init failed" in result["remap_error"]

    def test_healthy_result_drops_bulky_worker_output(self, monkeypatch):
        """A passing check must not dump kilobytes of stdout into the context."""
        ec = self._patch_executor(
            monkeypatch,
            {
                "yac_helper_ok": True,
                "remap_ok": True,
                "stdout_tail": "x" * 4000,
                "stderr_tail": "y" * 4000,
            },
        )

        result = ec.check_remote_yac(endpoint="chrysalis")

        assert result["available"] is True
        assert "stdout_tail" not in result
        assert "stderr_tail" not in result

    def test_failed_result_keeps_a_bounded_traceback(self, monkeypatch):
        """On failure the diagnostics are kept, but capped."""
        ec = self._patch_executor(
            monkeypatch,
            {
                "yac_helper_ok": False,
                "remap_ok": False,
                "yac_helper_traceback": "T" * 5000,
            },
        )

        result = ec.check_remote_yac(endpoint="chrysalis")

        assert result["available"] is False
        assert 0 < len(result["yac_helper_traceback"]) <= 800

    def test_worker_failure_is_reported_not_raised(self, monkeypatch):
        ec = self._patch_executor(monkeypatch, RuntimeError("WorkerLost: node down"))

        result = ec.check_remote_yac(endpoint="chrysalis")

        assert result["available"] is False
        assert result["reason"] == "probe_failed"
        assert "WorkerLost" in result["error"]

    def test_no_endpoint_configured_is_reported_cleanly(self, monkeypatch):
        from uxarray_mcp.tools import execution_control

        monkeypatch.setattr(
            execution_control,
            "_load_config_for_tools",
            lambda: (HPCConfig(), None),
        )

        result = execution_control.check_remote_yac()

        assert result["available"] is False
        assert result["reason"] == "no_endpoint"

    def test_diagnose_endpoint_routes_the_check_yac_action(self, monkeypatch):
        """The front door exposes YAC without a separate core tool."""
        from uxarray_mcp.tools import execution_control, frontdoor

        seen = {}

        def _fake(endpoint=None, probe_timeout_seconds=300, session_id=None):
            seen["endpoint"] = endpoint
            seen["timeout"] = probe_timeout_seconds
            return {"available": True}

        monkeypatch.setattr(execution_control, "check_remote_yac", _fake)

        result = frontdoor.diagnose_endpoint(action="check_yac", endpoint="chrysalis")

        assert result == {"available": True}
        assert seen["endpoint"] == "chrysalis"
        # YAC builds a grid and remaps; never inherit the short default probe.
        assert seen["timeout"] >= 300

    def test_unknown_action_names_check_yac(self):
        from uxarray_mcp.tools.frontdoor import diagnose_endpoint

        with pytest.raises(ValueError, match="check_yac"):
            diagnose_endpoint(action="not_a_real_action")
