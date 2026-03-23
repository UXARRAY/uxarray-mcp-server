"""Tests for execution mode naming and persistence."""

import tempfile
from pathlib import Path

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
