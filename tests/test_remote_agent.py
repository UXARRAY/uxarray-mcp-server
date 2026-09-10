"""Tests for remote execution via Academy agent and Globus Compute."""

from unittest.mock import MagicMock, patch

import pytest

from uxarray_mcp.remote.agent import UXarrayComputeAgent
from uxarray_mcp.remote.config import EndpointProfile, HPCConfig, load_config

try:
    import academy  # noqa: F401

    HAS_ACADEMY = True
except ImportError:
    HAS_ACADEMY = False

skip_no_academy = pytest.mark.skipif(
    not HAS_ACADEMY, reason="academy-py not installed (HPC optional dep)"
)


class TestHPCConfig:
    """Tests for HPC configuration."""

    def test_default_config(self):
        """Test default configuration has no endpoint."""
        config = HPCConfig()
        assert config.endpoint_id is None
        assert config.execution_mode == "local"
        assert config.has_endpoint is False
        assert config.should_use_remote is False

    def test_config_with_endpoint(self):
        """Test configuration with endpoint."""
        config = HPCConfig(endpoint_id="test-uuid-123", execution_mode="hpc")
        assert config.has_endpoint is True
        assert config.should_use_remote is True

    def test_remote_alias_normalized_to_hpc(self):
        """Legacy 'remote' mode is normalized to the canonical 'hpc' mode."""
        config = HPCConfig(endpoint_id="test-uuid-123", execution_mode="remote")
        assert config.execution_mode == "hpc"
        assert config.should_use_remote is True

    def test_config_load_missing_file(self, tmp_path):
        """Test loading config when file doesn't exist."""
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config.endpoint_id is None
        assert config.execution_mode == "local"

    def test_config_load_empty_file(self, tmp_path):
        """Test loading config when file exists but is empty."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")

        config = load_config(config_file)
        assert config.endpoint_id is None
        assert config.execution_mode == "local"
        assert config.timeout_seconds == 300

    def test_config_load_named_endpoints(self, tmp_path):
        """Named endpoint profiles are loaded and selected explicitly."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
hpc:
  default_endpoint: ucar
  endpoints:
    ucar:
      endpoint_id: ucar-uuid
    improv:
      endpoint_id: improv-uuid
  execution_mode: auto
  timeout_seconds: 300
""",
            encoding="utf-8",
        )

        config = load_config(config_file)

        assert config.endpoint_id == "ucar-uuid"
        assert config.endpoint_name == "ucar"
        assert config.endpoint_names == ["improv", "ucar"]
        assert (
            config.resolve_endpoint(path="/some/other/facility/test.nc").name == "ucar"
        )
        assert config.for_endpoint(endpoint="improv").endpoint_id == "improv-uuid"

    def test_config_load_user_endpoint_config(self, tmp_path):
        """A multi-user endpoint's config reaches the profile and the top level.

        A multi-user endpoint spawns the child endpoint only when the client
        asks for one, so a submit carrying no ``user_endpoint_config`` is
        refused with "did not signal readiness" (HTTP 422) no matter how
        healthy the manager is. An empty mapping is a valid ask. The top-level
        copy matters because a bare ``endpoint_id`` submit does not go through
        the named profile and would otherwise ask differently than the profile
        that supplied the very same UUID.
        """
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
hpc:
  default_endpoint: chrysalis
  endpoints:
    chrysalis:
      endpoint_id: chrysalis-uuid
      user_endpoint_config: {}
    improv:
      endpoint_id: improv-uuid
  execution_mode: auto
""",
            encoding="utf-8",
        )

        config = load_config(config_file)

        assert config.endpoints["chrysalis"].user_endpoint_config == {}
        assert config.user_endpoint_config == {}
        assert config.for_endpoint(endpoint="chrysalis").user_endpoint_config == {}
        # A single-user endpoint rejects a submit that carries the key, so the
        # absence has to survive as None rather than collapse to an empty dict.
        assert config.endpoints["improv"].user_endpoint_config is None
        assert config.for_endpoint(endpoint="improv").user_endpoint_config is None

    def test_config_unknown_endpoint_raises(self):
        """Unknown endpoint names fail before submitting to the wrong facility."""
        config = HPCConfig(
            endpoints={"ucar": EndpointProfile(name="ucar", endpoint_id="ucar-uuid")}
        )

        with pytest.raises(ValueError, match="Unknown endpoint"):
            config.for_endpoint(endpoint="improv")

    def test_raw_uuid_endpoint_is_allowed(self):
        """Explicit Globus endpoint UUIDs remain supported for one-off diagnostics."""
        endpoint_id = "11111111-2222-3333-4444-555555555555"
        config = HPCConfig()

        selected = config.for_endpoint(endpoint=endpoint_id)

        assert selected.endpoint_id == endpoint_id
        assert selected.endpoint_name == endpoint_id

    def test_named_agent_does_not_replace_default_singleton(self, monkeypatch):
        """Endpoint-specific agents do not poison the default agent cache."""
        from uxarray_mcp.remote import agent as agent_module

        config = HPCConfig(
            endpoint_id="ucar-uuid",
            execution_mode="hpc",
            endpoints={
                "ucar": EndpointProfile(name="ucar", endpoint_id="ucar-uuid"),
                "improv": EndpointProfile(name="improv", endpoint_id="improv-uuid"),
            },
            default_endpoint="ucar",
            endpoint_name="ucar",
        )
        monkeypatch.setattr("uxarray_mcp.remote.config.load_config", lambda: config)
        monkeypatch.setattr(agent_module, "_agent_instance", None)
        agent_module._agent_instances.clear()

        named_agent = agent_module.get_agent(endpoint="improv")
        default_agent = agent_module.get_agent()

        assert named_agent.config.endpoint_id == "improv-uuid"
        assert default_agent.config.endpoint_id == "ucar-uuid"
        assert default_agent is not named_agent


@skip_no_academy
class TestUXarrayComputeAgent:
    """Tests for UXarray Compute Agent."""

    @pytest.mark.asyncio
    async def test_agent_local_fallback_calculate_area(self):
        """Test agent falls back to local execution when no endpoint."""
        config = HPCConfig(endpoint_id=None, execution_mode="local")
        agent = UXarrayComputeAgent(config)

        result = await agent.calculate_area_remote("healpix:2", use_remote=False)

        assert "total_area" in result
        assert "mean_area" in result
        assert "n_face" in result
        assert result["n_face"] == 192

    @pytest.mark.asyncio
    async def test_agent_local_fallback_when_no_endpoint_configured(self):
        """Test agent uses local when remote requested but no endpoint."""
        config = HPCConfig(endpoint_id=None, execution_mode="local")
        agent = UXarrayComputeAgent(config)

        result = await agent.calculate_area_remote("healpix:2", use_remote=True)

        assert "total_area" in result
        assert result["n_face"] == 192

    @pytest.mark.asyncio
    async def test_agent_inspect_variable_local(self, synthetic_mesh_with_data):
        """Test agent inspect_variable with local execution."""
        grid_file, data_file = synthetic_mesh_with_data

        config = HPCConfig(endpoint_id=None)
        agent = UXarrayComputeAgent(config)

        result = await agent.inspect_variable_remote(
            grid_file, data_file, "temperature", use_remote=False
        )

        assert "variables" in result
        assert "grid_info" in result
        assert len(result["variables"]) == 1
        assert result["variables"][0]["name"] == "temperature"

    @pytest.mark.asyncio
    async def test_agent_zonal_mean_local(self, synthetic_mesh_with_data):
        """Test agent calculate_zonal_mean with local execution."""
        grid_file, data_file = synthetic_mesh_with_data

        config = HPCConfig(endpoint_id=None)
        agent = UXarrayComputeAgent(config)

        result = await agent.calculate_zonal_mean_remote(
            grid_file, data_file, "temperature", use_remote=False
        )

        assert "variable_name" in result
        assert result["variable_name"] == "temperature"
        assert "latitudes" in result
        assert "zonal_mean_values" in result

    @pytest.mark.asyncio
    async def test_agent_remote_execution_with_mock_executor(self):
        """Test agent submits to Globus Compute when endpoint configured."""
        config = HPCConfig(endpoint_id="test-uuid", execution_mode="hpc")
        agent = UXarrayComputeAgent(config)

        mock_future = MagicMock()
        mock_future.result.return_value = {
            "total_area": 1.0,
            "mean_area": 0.5,
            "min_area": 0.1,
            "max_area": 0.9,
            "area_units": "m^2",
            "n_face": 100,
        }

        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future

        with patch("globus_compute_sdk.Executor", return_value=mock_executor):
            result = await agent.calculate_area_remote("test.nc", use_remote=True)

            assert result["total_area"] == 1.0
            assert result["n_face"] == 100
            mock_executor.submit.assert_called_once()

    def test_executor_sends_user_endpoint_config_only_when_configured(self):
        """The submit is shaped by which kind of endpoint config names."""
        with patch("globus_compute_sdk.Executor") as executor_cls:
            multi_user = UXarrayComputeAgent(
                HPCConfig(
                    endpoint_id="mep-uuid",
                    execution_mode="hpc",
                    user_endpoint_config={},
                )
            )
            multi_user._get_executor()
            assert executor_cls.call_args.kwargs["user_endpoint_config"] == {}

            executor_cls.reset_mock()
            single_user = UXarrayComputeAgent(
                HPCConfig(endpoint_id="sep-uuid", execution_mode="hpc")
            )
            single_user._get_executor()
            # Not merely empty: a single-user endpoint refuses a submit that
            # carries the key at all, so it must be absent from the kwargs.
            assert "user_endpoint_config" not in executor_cls.call_args.kwargs

    def test_stopped_executor_is_rebuilt(self):
        """A failed submit must not poison every later call in the process.

        The SDK marks an Executor ``_stopped`` once a submit fails hard, and
        every call after that raises "is shutdown; no new functions may be
        executed". Caching it forever meant one unreachable-endpoint error
        required restarting the server to talk to an endpoint that had since
        come back -- which is exactly what made restarting the endpoint look
        like it changed nothing.
        """
        agent = UXarrayComputeAgent(
            HPCConfig(endpoint_id="test-uuid", execution_mode="hpc")
        )

        with patch("globus_compute_sdk.Executor") as executor_cls:
            executor_cls.side_effect = lambda **_: MagicMock(_stopped=False)
            first = agent._get_executor()
            assert agent._get_executor() is first  # a live one is reused

            first._stopped = True
            second = agent._get_executor()

        assert second is not first

    def test_worker_probe_submits_the_same_shape_as_real_work(self, monkeypatch):
        """A probe shaped unlike real work reports a health it cannot deliver.

        The probe is what decides whether an endpoint is usable, so if it
        submits without the ``user_endpoint_config`` that every tool call
        carries, a multi-user endpoint can be declared active and then refuse
        the very next submit.
        """
        from uxarray_mcp.remote import health

        monkeypatch.setattr(
            health,
            "check_endpoint_manager_status",
            lambda config, force=False: {"status": "registered"},
        )

        config = HPCConfig(
            endpoint_id="mep-uuid", execution_mode="hpc", user_endpoint_config={}
        )

        with patch("globus_compute_sdk.Executor") as executor_cls:
            executor_cls.return_value.submit.return_value.result.return_value = {
                "node": "chr-0001",
                "python": "3.12.13",
                "pythonpath": "",
            }
            health.probe_endpoint_worker(config, timeout_seconds=1)

        assert executor_cls.call_args.kwargs["user_endpoint_config"] == {}


class TestRemoteTools:
    """Tests for MCP remote tools."""

    def test_calculate_area_local(self):
        """Test calculate_area with local execution."""
        from uxarray_mcp.tools import calculate_area

        result = calculate_area("healpix:2", use_remote=False)

        assert "total_area" in result
        assert "n_face" in result
        assert result["n_face"] == 192

    def test_inspect_variable_local(self, synthetic_mesh_with_data):
        """Test inspect_variable with local execution."""
        from uxarray_mcp.tools import inspect_variable

        grid_file, data_file = synthetic_mesh_with_data

        result = inspect_variable(grid_file, data_file, "temperature", use_remote=False)

        assert "variables" in result
        assert len(result["variables"]) == 1

    def test_calculate_zonal_mean_local(self, synthetic_mesh_with_data):
        """Test calculate_zonal_mean with local execution."""
        from uxarray_mcp.tools import calculate_zonal_mean

        grid_file, data_file = synthetic_mesh_with_data

        result = calculate_zonal_mean(
            grid_file, data_file, "temperature", use_remote=False
        )

        assert "variable_name" in result
        assert result["variable_name"] == "temperature"

    @pytest.mark.asyncio
    async def test_calculate_area_local_inside_running_loop(self):
        """Test wrapper returns result dict even when an event loop is running."""
        from uxarray_mcp.tools import calculate_area

        result = calculate_area("healpix:2", use_remote=False)

        assert isinstance(result, dict)
        assert result["n_face"] == 192

    @pytest.mark.asyncio
    async def test_run_sync_preserves_remote_runtime_error(self):
        from uxarray_mcp.tools.remote_tools import _run_sync

        async def fail():
            raise RuntimeError("original worker failure")

        with pytest.raises(RuntimeError, match="original worker failure"):
            _run_sync(fail)

    def test_remote_inspect_variable_invalid_name(self, synthetic_mesh_with_data):
        """Test remote inspect_variable mirrors local invalid-variable behavior."""
        from uxarray_mcp.remote.compute_functions import remote_inspect_variable

        grid_file, data_file = synthetic_mesh_with_data

        with pytest.raises(ValueError, match="Variable 'salinity' not found"):
            remote_inspect_variable(grid_file, data_file, "salinity")
