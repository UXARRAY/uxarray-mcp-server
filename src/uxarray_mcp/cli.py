"""Command-line interface for the UXarray MCP server.

Subcommands
-----------
- ``serve`` — run the MCP server (stdio by default)
- ``endpoints`` — discover, list, add, remove Globus Compute endpoints
- ``doctor`` — validate the install and, when configured, an endpoint
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
    discover_config_search_paths,
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
    """Run the MCP server."""
    from uxarray_mcp.server.app import UXarrayApp

    transport = args.transport
    UXarrayApp().serve_mcp(
        transport="streamable-http" if transport == "http" else transport,
        host=args.host,
        port=args.port,
    )
    return 0


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
    loaded = discover_config_path()
    if not cfg.endpoints and not cfg.endpoint_id:
        if loaded is None:
            print("No endpoints configured. No config file was found. Searched:")
            for p in discover_config_search_paths():
                print(f"  - {p}")
            print(
                "\nAdd one with:  uxarray-mcp endpoints add <name> <uuid> --path-prefix /..."
            )
        else:
            print(f"No endpoints configured in {loaded}.")
            print("\nAdd one with:  uxarray-mcp endpoints add <name> <uuid>")
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


#: Filesystem prefixes worth suggesting for a known site. Only a hint: the
#: user still has to confirm, because an endpoint's useful prefix depends on
#: where *their* data lives, not on the machine's name.
_PREFIX_HINTS: dict[str, tuple[str, ...]] = {
    "casper": ("/glade/",),
    "derecho": ("/glade/",),
    "glade": ("/glade/",),
    "ucar": ("/glade/",),
    "ncar": ("/glade/",),
    "chrysalis": ("/lcrc/",),
    "improv": ("/gpfs/fs1/", "/home/"),
    "lcrc": ("/lcrc/",),
    "perlmutter": ("/pscratch/", "/global/"),
    "nersc": ("/pscratch/", "/global/"),
}


def _suggest_prefixes(endpoint_name: str) -> tuple[str, ...]:
    lowered = (endpoint_name or "").lower()
    for marker, prefixes in _PREFIX_HINTS.items():
        if marker in lowered:
            return prefixes
    return ()


def cmd_endpoints_discover(args: argparse.Namespace) -> int:
    """List the Globus Compute endpoints this identity can already see.

    The question every new user hits first is "where do I get a UUID". Until
    now the answer was "someone gives it to you", which is true for a shared
    facility endpoint and useless for anyone who just started their own: the
    UUID is printed once when the endpoint first registers and is easy to
    lose. The Globus Compute service knows the answer, so ask it.
    """
    try:
        from globus_compute_sdk import Client
    except ImportError:
        print(
            "The HPC extra is not installed. Install it with:\n"
            "  uv tool install --python 3.12 --extra hpc uxarray-mcp",
            file=sys.stderr,
        )
        return 2

    try:
        endpoints = Client().get_endpoints()
    except Exception as exc:  # pragma: no cover - needs a live Globus session
        print(f"Could not reach Globus Compute: {exc}", file=sys.stderr)
        print(
            "\nIf this is an authentication error, the first command that "
            "needs Globus opens a browser to log in. Try again, or run "
            "`uxarray-mcp doctor --endpoint <name>`.",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(json.dumps(endpoints, indent=2, default=str))
        return 0

    if not endpoints:
        print("No Globus Compute endpoints are visible to your identity.")
        print("\nThat means one of:")
        print("  - you have not started an endpoint on the HPC machine yet")
        print("    (see docs/hpc.md), or")
        print("  - the endpoint belongs to someone else and they have not")
        print("    shared it with you -- ask them for the UUID directly.")
        return 0

    configured = {p.endpoint_id: name for name, p in load_config().endpoints.items()}

    print(f"{len(endpoints)} endpoint(s) visible to your Globus identity:\n")
    for entry in endpoints:
        uuid = str(entry.get("uuid", "") or "")
        name = str(entry.get("name", "") or "(unnamed)")
        known = configured.get(uuid)
        mark = f"  [configured as {known!r}]" if known else ""
        print(f"  {name}{mark}")
        print(f"    {uuid}")
        if not known:
            hint = _suggest_prefixes(name)
            prefix_args = " ".join(f"--path-prefix {p}" for p in hint) or (
                "--path-prefix /your/data/root/"
            )
            # Prefer the site word over the first token: an endpoint called
            # "uxarray-chrysalis" should be suggested as `chrysalis`, not
            # `uxarray`, which says nothing about which machine it is.
            lowered = name.lower()
            local = next(
                (m for m in _PREFIX_HINTS if m in lowered),
                (name.split("-")[0] or "hpc"),
            )
            print(
                f"    add it:  uxarray-mcp endpoints add {local} {uuid} {prefix_args}"
            )
        print()

    if any(str(e.get("uuid")) not in configured for e in endpoints):
        print(
            "--path-prefix tells the dispatcher which file paths belong to "
            "which\nmachine. Check the suggestion against where your data "
            "actually lives."
        )
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
    """Validate local install and, when configured, one endpoint."""
    from uxarray_mcp.server.tools import endpoint

    report = endpoint(
        action="validate",
        endpoint=args.endpoint,
        path=args.sample_path,
        probe_timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed") else 1


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

    # --- serve (MCP) ---
    serve = sub.add_parser("serve", help="Run the MCP server.")
    serve.add_argument(
        "--transport",
        choices=("stdio", "sse", "http"),
        default="stdio",
        help="MCP transport. stdio for subprocess use by MCP clients.",
    )
    serve.add_argument("--host", default="127.0.0.1", help="Bind host for SSE/HTTP.")
    serve.add_argument("--port", type=int, default=8001, help="Port for SSE/HTTP.")
    serve.set_defaults(func=cmd_serve)

    endpoints = sub.add_parser("endpoints", help="Manage Globus Compute endpoints.")
    ep_sub = endpoints.add_subparsers(dest="endpoints_command", required=True)

    ep_discover = ep_sub.add_parser(
        "discover",
        help="Find endpoint UUIDs your Globus identity can already see.",
        description=(
            "Ask Globus Compute which endpoints you have access to, and print "
            "the `endpoints add` line for each one that is not configured yet. "
            "Use this when you do not know your endpoint's UUID -- it is "
            "printed once when the endpoint first registers and is easy to lose."
        ),
    )
    ep_discover.add_argument(
        "--json", action="store_true", help="Print the raw service response."
    )
    ep_discover.set_defaults(func=cmd_endpoints_discover)

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

    doctor = sub.add_parser(
        "doctor", help="Check the install and, if configured, an endpoint."
    )
    doctor.add_argument("--endpoint", default=None, help="Named endpoint to validate.")
    doctor.add_argument(
        "--sample-path", default=None, help="Remote file to test-read on the worker."
    )
    doctor.add_argument("--timeout-seconds", type=int, default=180)
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
