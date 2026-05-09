"""Tests for the ``uxarray-mcp`` CLI and config discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from uxarray_mcp import cli
from uxarray_mcp.remote import config as config_module


@pytest.fixture()
def isolated_user_config(tmp_path, monkeypatch):
    """Redirect USER_CONFIG_PATH and HOME to a tmp dir for the test."""
    user_cfg = tmp_path / "config" / "uxarray-mcp" / "config.yaml"
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", user_cfg)
    monkeypatch.setattr(cli, "USER_CONFIG_PATH", user_cfg)
    monkeypatch.delenv("UXARRAY_MCP_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    return user_cfg


def test_cli_help_runs():
    parser = cli.build_parser()
    assert parser.prog == "uxarray-mcp"
    text = parser.format_help()
    for sub in ("serve", "setup", "endpoints", "doctor", "install-claude"):
        assert sub in text


def test_setup_writes_starter_config(isolated_user_config: Path):
    rc = cli.main(["setup", "--execution-mode", "auto"])
    assert rc == 0
    assert isolated_user_config.exists()
    data = yaml.safe_load(isolated_user_config.read_text())
    assert data["hpc"]["execution_mode"] == "auto"
    assert data["hpc"]["endpoints"] == {}


def test_setup_refuses_overwrite_without_force(isolated_user_config: Path):
    isolated_user_config.parent.mkdir(parents=True)
    isolated_user_config.write_text("hpc: {}\n")
    rc = cli.main(["setup"])
    assert rc == 2


def test_endpoints_add_creates_canonical_schema(isolated_user_config: Path):
    rc = cli.main(
        [
            "endpoints",
            "add",
            "improv",
            "00000000-0000-0000-0000-000000000001",
            "--path-prefix",
            "/lus/",
            "--set-default",
        ]
    )
    assert rc == 0
    data = yaml.safe_load(isolated_user_config.read_text())
    assert data["hpc"]["default_endpoint"] == "improv"
    assert data["hpc"]["execution_mode"] == "auto"
    profile = data["hpc"]["endpoints"]["improv"]
    assert profile["endpoint_id"] == "00000000-0000-0000-0000-000000000001"
    assert profile["path_prefixes"] == ["/lus/"]


def test_endpoints_remove(isolated_user_config: Path):
    cli.main(["endpoints", "add", "ucar", "00000000-0000-0000-0000-000000000002"])
    rc = cli.main(["endpoints", "remove", "ucar"])
    assert rc == 0
    data = yaml.safe_load(isolated_user_config.read_text())
    assert "ucar" not in data["hpc"]["endpoints"]


def test_install_claude_print_only(capsys, isolated_user_config: Path):
    rc = cli.main(["install-claude", "--print-only", "--name", "uxarray-test"])
    assert rc == 0
    captured = capsys.readouterr().out
    block = json.loads(captured)
    server = block["mcpServers"]["uxarray-test"]
    assert server["args"] == ["serve"]
    assert server["command"]


def test_install_claude_merges_existing(tmp_path, isolated_user_config: Path):
    target = tmp_path / "claude_desktop_config.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    rc = cli.main(
        [
            "install-claude",
            "--name",
            "uxarray",
            "--config-path",
            str(target),
        ]
    )
    assert rc == 0
    merged = json.loads(target.read_text())
    assert "other" in merged["mcpServers"]
    assert "uxarray" in merged["mcpServers"]


# --- Config discovery ----------------------------------------------------


def test_discover_config_uses_env_var(tmp_path, monkeypatch):
    target = tmp_path / "explicit.yaml"
    target.write_text("hpc: {execution_mode: hpc}\n")
    monkeypatch.setenv("UXARRAY_MCP_CONFIG", str(target))
    monkeypatch.setattr(
        config_module, "USER_CONFIG_PATH", tmp_path / "user-not-here.yaml"
    )

    found = config_module.discover_config_path()
    assert found == target


def test_discover_config_user_home_beats_repo(tmp_path, monkeypatch):
    monkeypatch.delenv("UXARRAY_MCP_CONFIG", raising=False)
    user_cfg = tmp_path / "user.yaml"
    user_cfg.write_text("hpc: {}\n")
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", user_cfg)
    found = config_module.discover_config_path()
    assert found == user_cfg


def test_discover_config_no_match_returns_none(tmp_path, monkeypatch):
    monkeypatch.delenv("UXARRAY_MCP_CONFIG", raising=False)
    monkeypatch.setattr(
        config_module, "USER_CONFIG_PATH", tmp_path / "missing.yaml"
    )
    # Point load_config at a definitely-missing repo path.
    monkeypatch.chdir(tmp_path)
    cfg = config_module.load_config(config_path=tmp_path / "no-such-config.yaml")
    assert cfg.endpoint_id is None
    assert cfg.endpoints == {}


def test_load_config_parses_canonical_endpoints(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "hpc": {
                    "execution_mode": "auto",
                    "default_endpoint": "improv",
                    "endpoints": {
                        "improv": {
                            "endpoint_id": "11111111-1111-1111-1111-111111111111",
                            "path_prefixes": ["/lus/", "/home/jain/"],
                            "timeout_seconds": 600,
                        },
                        "ucar": {
                            "endpoint_id": "22222222-2222-2222-2222-222222222222",
                        },
                    },
                }
            }
        )
    )
    cfg = config_module.load_config(config_path=cfg_path)
    assert cfg.execution_mode == "auto"
    assert cfg.default_endpoint == "improv"
    assert set(cfg.endpoints) == {"improv", "ucar"}
    improv = cfg.endpoints["improv"]
    assert improv.endpoint_id == "11111111-1111-1111-1111-111111111111"
    assert improv.path_prefixes == ("/lus/", "/home/jain/")
    assert improv.timeout_seconds == 600
    # Default resolves to improv profile
    resolved = cfg.resolve_endpoint()
    assert resolved is not None
    assert resolved.name == "improv"


def test_load_config_legacy_single_endpoint_still_works(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "hpc": {
                    "execution_mode": "hpc",
                    "globus_compute": {
                        "endpoint_id": "33333333-3333-3333-3333-333333333333",
                    },
                }
            }
        )
    )
    cfg = config_module.load_config(config_path=cfg_path)
    assert cfg.endpoint_id == "33333333-3333-3333-3333-333333333333"
    assert cfg.execution_mode == "hpc"
    assert cfg.has_endpoint
