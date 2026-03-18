"""Safety net tests for the HPC execution layer.

Covers health checks, pre-flight readiness, fallback behaviour,
validate_dataset, and provenance correctness. These must pass before
and after any refactor so the HPC path stays intact.
"""

import importlib.util

import pytest
from unittest.mock import MagicMock, patch

from uxarray_mcp.remote.config import HPCConfig

globus_available = importlib.util.find_spec("globus_compute_sdk") is not None
requires_globus = pytest.mark.skipif(
    not globus_available, reason="globus_compute_sdk not installed (HPC extra required)"
)
from uxarray_mcp.remote.health import check_endpoint_health
from uxarray_mcp.tools.inspection import validate_dataset
from uxarray_mcp.tools.remote_tools import (
    _endpoint_is_ready,
    inspect_mesh_hpc,
    calculate_area_hpc,
)


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
        """Returns online status when Globus SDK reports the endpoint is up."""
        config = HPCConfig(endpoint_id="fake-uuid-1234", execution_mode="remote")
        mock_client = MagicMock()
        mock_client.get_endpoint_status.return_value = {"status": "online"}

        with patch("globus_compute_sdk.Client", return_value=mock_client):
            result = check_endpoint_health(config)

        assert result["status"] == "online"
        assert result["endpoint_id"] == "fake-uuid-1234"

    @requires_globus
    def test_unreachable_endpoint(self):
        """Returns unreachable with error message when Globus SDK raises."""
        config = HPCConfig(endpoint_id="fake-uuid-1234", execution_mode="remote")

        with patch(
            "globus_compute_sdk.Client", side_effect=Exception("Connection refused")
        ):
            result = check_endpoint_health(config)

        assert result["status"] == "unreachable"
        assert result["endpoint_id"] == "fake-uuid-1234"
        assert "error" in result

    @requires_globus
    def test_unknown_status_passed_through(self):
        """Passes through whatever status string the Globus SDK returns."""
        config = HPCConfig(endpoint_id="fake-uuid-1234", execution_mode="remote")
        mock_client = MagicMock()
        mock_client.get_endpoint_status.return_value = {"status": "stopped"}

        with patch("globus_compute_sdk.Client", return_value=mock_client):
            result = check_endpoint_health(config)

        assert result["status"] == "stopped"


# -----------------------------------------------------------------------------
# Unit Tests (Mocked) — _endpoint_is_ready
# -----------------------------------------------------------------------------


class TestEndpointIsReady:
    """Tests for the pre-flight check used before every HPC job submission."""

    def _make_agent(self, endpoint_id=None):
        from uxarray_mcp.remote.agent import UXarrayComputeAgent

        config = HPCConfig(endpoint_id=endpoint_id, execution_mode="remote")
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
# Unit Tests (Mocked) — inspect_mesh_hpc routing and fallback
# -----------------------------------------------------------------------------


class TestInspectMeshHpcUnit:
    """Unit tests for inspect_mesh_hpc routing and fallback logic."""

    def test_no_endpoint_falls_back_to_local(self, synthetic_mesh_file):
        """Falls back to local when use_remote=True but no endpoint is configured."""
        with patch("uxarray_mcp.remote.agent.get_agent") as mock_get_agent:
            mock_agent = MagicMock()
            mock_agent.config.has_endpoint = False
            mock_get_agent.return_value = mock_agent

            result = inspect_mesh_hpc(synthetic_mesh_file, use_remote=True)

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

            result = inspect_mesh_hpc(synthetic_mesh_file, use_remote=True)

        assert "n_face" in result
        warnings = result["_provenance"]["warnings"]
        assert any("HPC endpoint not ready" in w for w in warnings)

    def test_provenance_always_attached(self):
        """Every inspect_mesh_hpc result carries a _provenance block."""
        result = inspect_mesh_hpc("healpix:2", use_remote=False)
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

            result = calculate_area_hpc(synthetic_mesh_file, use_remote=True)

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

            result = calculate_area_hpc(synthetic_mesh_file, use_remote=True)

        warnings = result["_provenance"]["warnings"]
        assert any("HPC endpoint not ready" in w for w in warnings)


# -----------------------------------------------------------------------------
# Integration Tests (Real Data)
# -----------------------------------------------------------------------------


def test_inspect_mesh_hpc_healpix():
    """Integration test: inspect_mesh_hpc runs locally on a HEALPix mesh."""
    result = inspect_mesh_hpc("healpix:2", use_remote=False)
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
