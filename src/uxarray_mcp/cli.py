"""Command-line interface for the UXarray MCP server.

Subcommands
-----------
- ``serve`` — run the MCP server (stdio transport)
- ``setup`` — write a minimal user config to ``~/.config/uxarray-mcp/config.yaml``
- ``doctor`` — validate local Globus auth, endpoint health, and optional remote probes
- ``endpoints`` — manage named Globus Compute endpoints in the user config
- ``install-claude`` — print or write the Claude Desktop ``mcpServers`` block

The CLI is registered via the ``uxarray-mcp`` entry point in pyproject.toml.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from uxarray_mcp.remote.config import (
    USER_CONFIG_PATH,
    discover_config_path,
    load_config,
)


def _read_user_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_user_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def _ensure_hpc_block(data: dict[str, Any]) -> dict[str, Any]:
    hpc = data.setdefault("hpc", {})
    if not isinstance(hpc, dict):
        hpc = {}
        data["hpc"] = hpc
    endpoints = hpc.setdefault("endpoints", {})
    if not isinstance(endpoints, dict):
        hpc["endpoints"] = {}
    return hpc


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the MCP server on stdio."""
    from uxarray_mcp.server import mcp

    mcp.run()
    return 0


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


def cmd_setup(args: argparse.Namespace) -> int:
    """Write a starter config to the user config path."""
    target = Path(args.path).expanduser() if args.path else USER_CONFIG_PATH
    if target.exists() and not args.force:
        print(
            f"Config already exists at {target}. Pass --force to overwrite.",
            file=sys.stderr,
        )
        return 2

    starter: dict[str, Any] = {
        "hpc": {
            "execution_mode": args.execution_mode,
            "timeout_seconds": 300,
            "default_endpoint": None,
            "endpoints": {},
        }
    }
    _write_user_config(target, starter)
    print(f"Wrote starter config to {target}")
    print("Add an endpoint with:  uxarray-mcp endpoints add <name> <uuid>")
    return 0


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


def _user_write_target() -> Path:
    """Path that mutating commands (`endpoints add/remove`) should write to.

    Honors `$UXARRAY_MCP_CONFIG` so add/remove stay consistent with the
    config the rest of the server reads. Falls back to ``USER_CONFIG_PATH``.
    """
    env_path = os.environ.get("UXARRAY_MCP_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return USER_CONFIG_PATH


def cmd_endpoints_list(args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg.endpoints and not cfg.endpoint_id:
        print("No endpoints configured.")
        return 0
    payload: dict[str, Any] = {
        "config_path": str(discover_config_path() or ""),
        "default_endpoint": cfg.default_endpoint,
        "execution_mode": cfg.execution_mode,
        "endpoints": {
            name: {
                "endpoint_id": p.endpoint_id,
                "path_prefixes": list(p.path_prefixes),
                "timeout_seconds": p.timeout_seconds,
            }
            for name, p in cfg.endpoints.items()
        },
    }
    if cfg.endpoint_id and not cfg.endpoints:
        payload["legacy_endpoint_id"] = cfg.endpoint_id
    print(json.dumps(payload, indent=2))
    return 0


def cmd_endpoints_add(args: argparse.Namespace) -> int:
    target = _user_write_target()
    data = _read_user_config(target)
    hpc = _ensure_hpc_block(data)
    endpoints = hpc["endpoints"]
    profile: dict[str, Any] = {"endpoint_id": args.uuid}
    if args.path_prefix:
        profile["path_prefixes"] = list(args.path_prefix)
    if args.timeout_seconds is not None:
        profile["timeout_seconds"] = args.timeout_seconds
    endpoints[args.name] = profile
    if args.set_default or not hpc.get("default_endpoint"):
        hpc["default_endpoint"] = args.name
    if hpc.get("execution_mode") in (None, "local"):
        hpc["execution_mode"] = "auto"
    _write_user_config(target, data)
    print(f"Added endpoint {args.name!r} → {args.uuid} in {target}")
    return 0


def cmd_endpoints_remove(args: argparse.Namespace) -> int:
    target = _user_write_target()
    if not target.exists():
        print(f"No user config at {target}", file=sys.stderr)
        return 2
    data = _read_user_config(target)
    hpc = _ensure_hpc_block(data)
    endpoints = hpc["endpoints"]
    if args.name not in endpoints:
        print(f"Endpoint {args.name!r} is not configured.", file=sys.stderr)
        return 2
    del endpoints[args.name]
    if hpc.get("default_endpoint") == args.name:
        hpc["default_endpoint"] = next(iter(endpoints), None)
    _write_user_config(target, data)
    print(f"Removed endpoint {args.name!r} from {target}")
    return 0


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    from uxarray_mcp.tools.execution_control import (
        probe_path_access,
        validate_hpc_setup,
    )

    sample_path = args.sample_path[0] if args.sample_path else None
    report = validate_hpc_setup(
        run_remote_probe=not args.skip_remote_probe,
        probe_timeout_seconds=args.timeout_seconds,
        sample_path=sample_path,
        endpoint=args.endpoint,
    )

    if len(args.sample_path) > 1:
        report["additional_path_probes"] = [
            probe_path_access(
                path,
                use_remote=True,
                inspect_netcdf=not args.no_netcdf,
                endpoint=args.endpoint,
            )
            for path in args.sample_path[1:]
        ]

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed") else 1


# ---------------------------------------------------------------------------
# install-claude
# ---------------------------------------------------------------------------


def _build_claude_block(name: str) -> dict[str, Any]:
    bin_path = shutil.which("uxarray-mcp") or "uxarray-mcp"
    return {
        "mcpServers": {
            name: {
                "command": bin_path,
                "args": ["serve"],
            }
        }
    }


def cmd_install_claude(args: argparse.Namespace) -> int:
    block = _build_claude_block(args.name)
    if args.print_only:
        print(json.dumps(block, indent=2))
        return 0

    target = Path(args.config_path).expanduser() if args.config_path else None
    if target is None:
        print(
            "Pass --config-path to merge into a Claude Desktop config, "
            "or --print-only to dump the block to stdout.",
            file=sys.stderr,
        )
        print(json.dumps(block, indent=2))
        return 0

    existing: dict[str, Any] = {}
    if target.exists():
        with open(target, "r", encoding="utf-8") as fh:
            existing = json.load(fh) or {}
    servers = existing.setdefault("mcpServers", {})
    servers[args.name] = block["mcpServers"][args.name]
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2)
    print(f"Wrote Claude config to {target}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uxarray-mcp",
        description="UXarray MCP server CLI: serve, configure, and diagnose.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the MCP server on stdio.")
    serve.set_defaults(func=cmd_serve)

    setup = sub.add_parser("setup", help="Write a starter user config.")
    setup.add_argument("--path", default=None, help="Override target path.")
    setup.add_argument(
        "--execution-mode",
        default="auto",
        choices=["local", "auto", "hpc"],
        help="Default execution mode (default: auto).",
    )
    setup.add_argument("--force", action="store_true", help="Overwrite existing file.")
    setup.set_defaults(func=cmd_setup)

    endpoints = sub.add_parser("endpoints", help="Manage Globus Compute endpoints.")
    ep_sub = endpoints.add_subparsers(dest="endpoints_command", required=True)

    ep_list = ep_sub.add_parser("list", help="Show configured endpoints.")
    ep_list.set_defaults(func=cmd_endpoints_list)

    ep_add = ep_sub.add_parser("add", help="Add or update an endpoint.")
    ep_add.add_argument("name")
    ep_add.add_argument("uuid")
    ep_add.add_argument(
        "--path-prefix",
        action="append",
        default=[],
        help="Filesystem prefix this endpoint owns. Repeatable.",
    )
    ep_add.add_argument("--timeout-seconds", type=int, default=None)
    ep_add.add_argument(
        "--set-default", action="store_true", help="Mark this endpoint as default."
    )
    ep_add.set_defaults(func=cmd_endpoints_add)

    ep_remove = ep_sub.add_parser("remove", help="Remove a named endpoint.")
    ep_remove.add_argument("name")
    ep_remove.set_defaults(func=cmd_endpoints_remove)

    doctor = sub.add_parser("doctor", help="Validate HPC readiness.")
    doctor.add_argument("--sample-path", action="append", default=[])
    doctor.add_argument("--timeout-seconds", type=int, default=180)
    doctor.add_argument("--endpoint", default=None)
    doctor.add_argument("--skip-remote-probe", action="store_true")
    doctor.add_argument("--no-netcdf", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    claude = sub.add_parser(
        "install-claude", help="Print or merge a Claude Desktop mcpServers block."
    )
    claude.add_argument("--name", default="uxarray", help="MCP server name.")
    claude.add_argument(
        "--config-path",
        default=None,
        help="Claude config to merge into (e.g. ~/Library/Application Support/Claude/claude_desktop_config.json).",
    )
    claude.add_argument(
        "--print-only",
        action="store_true",
        help="Print the JSON block without writing anywhere.",
    )
    claude.set_defaults(func=cmd_install_claude)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
