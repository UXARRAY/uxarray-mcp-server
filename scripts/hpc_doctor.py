#!/usr/bin/env python3
"""Run UXarray MCP HPC diagnostics from the command line."""

from __future__ import annotations

import argparse
import json

from uxarray_mcp.tools.execution_control import probe_path_access, validate_hpc_setup


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate local Globus auth, endpoint status, and optional remote "
            "path readability for UXarray MCP."
        )
    )
    parser.add_argument(
        "--sample-path",
        action="append",
        default=[],
        help="Exact remote path to probe after the runtime probe succeeds. Repeatable.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Timeout to use for remote probes.",
    )
    parser.add_argument(
        "--skip-remote-probe",
        action="store_true",
        help="Only validate config and endpoint status, without submitting work.",
    )
    parser.add_argument(
        "--no-netcdf",
        action="store_true",
        help="Skip the generic NetCDF open when probing sample paths.",
    )
    args = parser.parse_args()

    sample_path = args.sample_path[0] if args.sample_path else None
    report = validate_hpc_setup(
        run_remote_probe=not args.skip_remote_probe,
        probe_timeout_seconds=args.timeout_seconds,
        sample_path=sample_path,
    )

    if len(args.sample_path) > 1:
        report["additional_path_probes"] = [
            probe_path_access(path, use_remote=True, inspect_netcdf=not args.no_netcdf)
            for path in args.sample_path[1:]
        ]

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
