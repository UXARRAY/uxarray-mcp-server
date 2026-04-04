"""Tests for execution mode naming and persistence."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from uxarray_mcp.remote.config import HPCConfig, load_config
from uxarray_mcp.tools import execution_control


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
    mock_future = MagicMock()
    mock_future.result.side_effect = RuntimeError("/bin/sh: qsub: command not found")
    mock_executor = MagicMock()
    mock_executor.submit.return_value = mock_future

    with (
        patch("globus_compute_sdk.Client", return_value=mock_client),
        patch("globus_compute_sdk.Executor", return_value=mock_executor),
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
    mock_future = MagicMock()
    mock_future.result.side_effect = RuntimeError(
        "Failed to start worker: (SystemExit) 73"
    )
    mock_executor = MagicMock()
    mock_executor.submit.return_value = mock_future

    with (
        patch("globus_compute_sdk.Client", return_value=mock_client),
        patch("globus_compute_sdk.Executor", return_value=mock_executor),
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

    with (
        patch("globus_compute_sdk.Client", return_value=mock_client),
        patch("globus_compute_sdk.Executor", return_value=mock_executor),
    ):
        result = execution_control.validate_hpc_setup(
            run_remote_probe=True,
            sample_path="/home/jain/test.nc",
        )

    sample_check = next(c for c in result["checks"] if c["name"] == "sample_path_probe")
    assert sample_check["passed"] is True
    assert result["sample_path_probe"]["path"] == "/home/jain/test.nc"


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
