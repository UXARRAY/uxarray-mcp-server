"""Tests for remote execution via Academy agent and Globus Compute."""

import pytest
from unittest.mock import MagicMock, patch
from uxarray_mcp.remote.config import HPCConfig, load_config
from uxarray_mcp.remote.agent import UXarrayComputeAgent

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


class TestRemoteTools:
    """Tests for MCP remote tools."""

    def test_calculate_area_hpc_local(self):
        """Test calculate_area_hpc with local execution."""
        from uxarray_mcp.tools import calculate_area_hpc

        result = calculate_area_hpc("healpix:2", use_remote=False)

        assert "total_area" in result
        assert "n_face" in result
        assert result["n_face"] == 192

    def test_inspect_variable_hpc_local(self, synthetic_mesh_with_data):
        """Test inspect_variable_hpc with local execution."""
        from uxarray_mcp.tools import inspect_variable_hpc

        grid_file, data_file = synthetic_mesh_with_data

        result = inspect_variable_hpc(
            grid_file, data_file, "temperature", use_remote=False
        )

        assert "variables" in result
        assert len(result["variables"]) == 1

    def test_calculate_zonal_mean_hpc_local(self, synthetic_mesh_with_data):
        """Test calculate_zonal_mean_hpc with local execution."""
        from uxarray_mcp.tools import calculate_zonal_mean_hpc

        grid_file, data_file = synthetic_mesh_with_data

        result = calculate_zonal_mean_hpc(
            grid_file, data_file, "temperature", use_remote=False
        )

        assert "variable_name" in result
        assert result["variable_name"] == "temperature"

    @pytest.mark.asyncio
    async def test_calculate_area_hpc_local_inside_running_loop(self):
        """Test wrapper returns result dict even when an event loop is running."""
        from uxarray_mcp.tools import calculate_area_hpc

        result = calculate_area_hpc("healpix:2", use_remote=False)

        assert isinstance(result, dict)
        assert result["n_face"] == 192

    def test_remote_inspect_variable_invalid_name(self, synthetic_mesh_with_data):
        """Test remote inspect_variable mirrors local invalid-variable behavior."""
        from uxarray_mcp.remote.compute_functions import remote_inspect_variable

        grid_file, data_file = synthetic_mesh_with_data

        with pytest.raises(ValueError, match="Variable 'salinity' not found"):
            remote_inspect_variable(grid_file, data_file, "salinity")
