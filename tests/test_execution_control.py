"""Tests for execution mode naming and persistence."""

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from uxarray_mcp.remote import health
from uxarray_mcp.remote.config import HPCConfig, load_config
from uxarray_mcp.tools import execution_control


@pytest.fixture(autouse=True)
def _reset_health_cache():
    """Drop the process-wide health cache + cached Client between tests."""
    health.invalidate_cache()
    health._CLIENT = None
    yield
    health.invalidate_cache()
    health._CLIENT = None


def test_hpc_mode_is_persisted(monkeypatch):
    """set_execution_mode writes the canonical HPC mode to config.yaml."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

        result = execution_control.set_execution_mode("hpc")

        assert result["mode"] == "hpc"
        saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert saved["hpc"]["execution_mode"] == "hpc"


def test_remote_alias_is_persisted_as_hpc(monkeypatch):
    """Legacy 'remote' requests are normalized before being written."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        config_path = Path(tmp_dir) / "config.yaml"
        monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

        result = execution_control.set_execution_mode("remote")

        assert result["mode"] == "hpc"
        config = load_config(config_path)
        assert config.execution_mode == "hpc"


def test_hpc_config_load_normalizes_legacy_remote(tmp_path):
    """Older configs using 'remote' still load as the canonical HPC mode."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "hpc:\n  globus_compute:\n    endpoint_id: legacy-id\n  execution_mode: remote\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert isinstance(config, HPCConfig)
    assert config.execution_mode == "hpc"


def test_validate_hpc_setup_without_endpoint(monkeypatch, tmp_path):
    """validate_hpc_setup fails clearly when no endpoint is configured."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("hpc:\n  execution_mode: auto\n", encoding="utf-8")
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    result = execution_control.validate_hpc_setup(run_remote_probe=False)

    assert result["passed"] is False
    assert result["endpoint_status"] == "no_endpoint"
    assert result["checks"][0]["name"] == "config"
    assert result["checks"][0]["passed"] is False


def test_validate_hpc_setup_local_dependency_failure(monkeypatch, tmp_path):
    """A missing local Globus package produces an actionable diagnostic."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "hpc:\n  globus_compute:\n    endpoint_id: test-uuid\n  execution_mode: auto\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "globus_compute_sdk":
            raise ImportError("No module named 'globus_compute_sdk'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        result = execution_control.validate_hpc_setup(run_remote_probe=False)

    assert result["passed"] is False
    dependency_check = next(
        c for c in result["checks"] if c["name"] == "local_dependencies"
    )
    assert dependency_check["passed"] is False
    assert "uv sync --extra hpc" in dependency_check["guidance"]


def test_validate_hpc_setup_surfaces_remote_probe_failure(monkeypatch, tmp_path):
    """Scheduler/bootstrap errors from a real remote probe are returned directly."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "hpc:\n  globus_compute:\n    endpoint_id: test-uuid\n  execution_mode: auto\n  timeout_seconds: 300\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client
    mock_future = MagicMock()
    mock_future.result.side_effect = RuntimeError("/bin/sh: qsub: command not found")
    mock_executor = MagicMock()
    mock_executor.submit.return_value = mock_future
    mock_client_cls = MagicMock(return_value=mock_client)
    mock_executor_cls = MagicMock(return_value=mock_executor)

    with patch.object(
        execution_control,
        "_load_globus_compute_sdk",
        return_value=(mock_client_cls, mock_executor_cls, MagicMock(), MagicMock()),
    ):
        result = execution_control.validate_hpc_setup(run_remote_probe=True)

    assert result["passed"] is False
    probe_check = next(c for c in result["checks"] if c["name"] == "remote_probe")
    assert probe_check["passed"] is False
    assert "qsub" in probe_check["details"]["error"]
    assert probe_check["details"]["exception_type"] == "RuntimeError"
    assert "/opt/pbs/bin" in probe_check["guidance"]


def test_validate_hpc_setup_surfaces_systemexit_guidance(monkeypatch, tmp_path):
    """SystemExit 73 gets cluster-specific remediation guidance."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "hpc:\n  globus_compute:\n    endpoint_id: test-uuid\n  execution_mode: auto\n  timeout_seconds: 300\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client
    mock_future = MagicMock()
    mock_future.result.side_effect = RuntimeError(
        "Failed to start worker: (SystemExit) 73"
    )
    mock_executor = MagicMock()
    mock_executor.submit.return_value = mock_future
    mock_client_cls = MagicMock(return_value=mock_client)
    mock_executor_cls = MagicMock(return_value=mock_executor)

    with patch.object(
        execution_control,
        "_load_globus_compute_sdk",
        return_value=(mock_client_cls, mock_executor_cls, MagicMock(), MagicMock()),
    ):
        result = execution_control.validate_hpc_setup(run_remote_probe=True)

    probe_check = next(c for c in result["checks"] if c["name"] == "remote_probe")
    assert "single login node" in probe_check["guidance"]


def test_validate_hpc_setup_can_probe_sample_path(monkeypatch, tmp_path):
    """A sample path probe reports remote readability separately from worker health."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "hpc:\n  globus_compute:\n    endpoint_id: test-uuid\n  execution_mode: auto\n  timeout_seconds: 300\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client

    mock_runtime_future = MagicMock()
    mock_runtime_future.result.return_value = {
        "hostname": "ilogin1",
        "qsub_path": "/opt/pbs/bin/qsub",
    }
    mock_path_future = MagicMock()
    mock_path_future.result.return_value = {
        "path": "/home/jain/test.nc",
        "exists": True,
        "is_file": True,
        "readable": True,
        "size_bytes": 128,
    }

    mock_executor = MagicMock()
    mock_executor.submit.side_effect = [mock_runtime_future, mock_path_future]
    mock_client_cls = MagicMock(return_value=mock_client)
    mock_executor_cls = MagicMock(return_value=mock_executor)

    with patch.object(
        execution_control,
        "_load_globus_compute_sdk",
        return_value=(mock_client_cls, mock_executor_cls, MagicMock(), MagicMock()),
    ):
        result = execution_control.validate_hpc_setup(
            run_remote_probe=True,
            sample_path="/home/jain/test.nc",
        )

    sample_check = next(c for c in result["checks"] if c["name"] == "sample_path_probe")
    assert sample_check["passed"] is True
    assert result["sample_path_probe"]["path"] == "/home/jain/test.nc"


def test_validate_hpc_setup_selects_named_endpoint(monkeypatch, tmp_path):
    """Diagnostics validate the selected endpoint profile."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
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
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client
    mock_client_cls = MagicMock(return_value=mock_client)

    with patch.object(
        execution_control,
        "_load_globus_compute_sdk",
        return_value=(mock_client_cls, MagicMock(), MagicMock(), MagicMock()),
    ):
        result = execution_control.validate_hpc_setup(
            endpoint="improv", run_remote_probe=False
        )

    assert result["endpoint_name"] == "improv"
    assert result["endpoint_configured"] is True
    mock_client.get_endpoint_status.assert_called_once_with("improv-uuid")


def test_validate_hpc_setup_uses_default_endpoint_with_sample_path(
    monkeypatch, tmp_path
):
    """Sample paths are probed on the selected endpoint, not used for routing."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
hpc:
  default_endpoint: improv
  endpoints:
    ucar:
      endpoint_id: ucar-uuid
    improv:
      endpoint_id: improv-uuid
  execution_mode: auto
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client
    mock_client_cls = MagicMock(return_value=mock_client)

    with patch.object(
        execution_control,
        "_load_globus_compute_sdk",
        return_value=(mock_client_cls, MagicMock(), MagicMock(), MagicMock()),
    ):
        result = execution_control.validate_hpc_setup(
            sample_path="/glade/u/home/rajeevj/test.nc",
            run_remote_probe=False,
        )

    assert result["endpoint_name"] == "improv"
    assert result["endpoint_configured"] is True
    mock_client.get_endpoint_status.assert_called_once_with("improv-uuid")


def test_probe_path_access_local(tmp_path):
    """Local path probing returns file metadata with provenance."""
    sample = tmp_path / "sample.txt"
    sample.write_text("hello", encoding="utf-8")

    result = execution_control.probe_path_access(
        str(sample), use_remote=False, inspect_netcdf=False
    )

    assert result["path"] == str(sample)
    assert result["exists"] is True
    assert result["readable"] is True
    assert result["_provenance"]["execution_venue"] == "local"


def _stub_config(endpoint_id="endpoint-uuid", endpoint_name="default"):
    cfg = MagicMock()
    cfg.endpoint_id = endpoint_id
    cfg.endpoint_name = endpoint_name
    return cfg


def test_health_check_caches_status_within_ttl():
    """Back-to-back health checks reuse the cached payload."""
    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client
    cfg = _stub_config("ep-1", "ucar")

    first = health.check_endpoint_health(cfg)
    second = health.check_endpoint_health(cfg)

    assert first["status"] == "registered"
    assert first["cached"] is False
    assert second["cached"] is True
    assert "cache_age_seconds" in second
    mock_client.get_endpoint_status.assert_called_once_with("ep-1")


def test_health_check_force_bypasses_cache():
    """force=True re-queries the SDK even with a valid cached entry."""
    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client
    cfg = _stub_config("ep-2")

    health.check_endpoint_health(cfg)
    health.check_endpoint_health(cfg, force=True)

    assert mock_client.get_endpoint_status.call_count == 2


def test_unhealthy_status_uses_shorter_ttl():
    """A failing endpoint is re-checked sooner than a healthy one."""
    mock_client = MagicMock()
    mock_client.get_endpoint_status.side_effect = RuntimeError("boom")
    health._CLIENT = mock_client
    cfg = _stub_config("ep-3")

    first = health.check_endpoint_health(cfg)
    assert first["status"] == "unreachable"
    assert first["cached"] is False

    # Pretend the cache entry is older than the unhealthy TTL.
    ts, payload = health._STATUS_CACHE["ep-3"]
    health._STATUS_CACHE["ep-3"] = (
        ts - (health._TTL_OTHER_SECONDS + 0.5),
        payload,
    )

    second = health.check_endpoint_health(cfg)
    assert second["cached"] is False
    assert mock_client.get_endpoint_status.call_count == 2


def test_invalidate_cache_drops_entry():
    """invalidate_cache forces the next check to query the SDK again."""
    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client
    cfg = _stub_config("ep-4")

    health.check_endpoint_health(cfg)
    health.invalidate_cache("ep-4")
    health.check_endpoint_health(cfg)

    assert mock_client.get_endpoint_status.call_count == 2


def test_check_all_endpoints_health_iterates_named_endpoints(monkeypatch, tmp_path):
    """check_all_endpoints_health returns one row per configured endpoint."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
hpc:
  default_endpoint: ucar
  endpoints:
    ucar:
      endpoint_id: ucar-uuid
    improv:
      endpoint_id: improv-uuid
  execution_mode: auto
""",
        encoding="utf-8",
    )
    config = load_config(config_path)

    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client

    rows = health.check_all_endpoints_health(config)
    names = {row["name"] for row in rows}
    assert names == {"ucar", "improv"}
    assert all(row["status"] == "registered" for row in rows)


def test_endpoint_status_tool_returns_cached_summary(monkeypatch, tmp_path):
    """The endpoint_status tool reports every configured endpoint."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
hpc:
  default_endpoint: ucar
  endpoints:
    ucar:
      endpoint_id: ucar-uuid
    improv:
      endpoint_id: improv-uuid
  execution_mode: auto
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client

    result = execution_control.endpoint_status()
    names = {row["name"] for row in result["endpoints"]}

    assert names == {"ucar", "improv"}
    assert result["default_endpoint"] == "ucar"
    assert result["mode"] == "auto"
    assert "_provenance" in result


def test_endpoint_status_named_endpoint_only(monkeypatch, tmp_path):
    """Passing endpoint='name' scopes the check to that endpoint."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
hpc:
  default_endpoint: ucar
  endpoints:
    ucar:
      endpoint_id: ucar-uuid
    improv:
      endpoint_id: improv-uuid
  execution_mode: auto
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    mock_client = MagicMock()
    mock_client.get_endpoint_status.return_value = {"status": "online"}
    health._CLIENT = mock_client

    result = execution_control.endpoint_status(endpoint="improv")
    assert len(result["endpoints"]) == 1
    assert result["endpoints"][0]["name"] == "improv"
    mock_client.get_endpoint_status.assert_called_once_with("improv-uuid")


def test_set_execution_mode_invalidates_health_cache(monkeypatch, tmp_path):
    """Switching modes drops the cached endpoint status."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "hpc:\n  globus_compute:\n    endpoint_id: test-uuid\n  execution_mode: auto\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(execution_control, "_CONFIG_PATH", config_path)

    health._STATUS_CACHE["test-uuid"] = (
        time.monotonic(),
        {"status": "online", "endpoint_id": "test-uuid"},
    )

    execution_control.set_execution_mode("local")

    assert "test-uuid" not in health._STATUS_CACHE
