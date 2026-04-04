#!/usr/bin/env python3
"""Example sequential remote workflow using Globus Compute futures directly."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from uxarray_mcp.remote.compute_functions import (
    remote_calculate_area,
    remote_calculate_zonal_mean,
    remote_inspect_mesh,
    remote_inspect_variable,
    remote_probe_path,
    remote_runtime_probe,
)
from uxarray_mcp.remote.config import load_config


def _wait_for_future(label: str, future, poll_seconds: float, timeout_seconds: int):
    """Poll a Globus Compute future until it resolves or times out."""
    deadline = time.monotonic() + timeout_seconds
    while not future.done():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{label} did not finish within {timeout_seconds}s")
        print(f"[wait] {label} still running...")
        time.sleep(poll_seconds)
    return future.result()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Submit a sequence of remote jobs, poll them, and decide the next "
            "step from the previous result."
        )
    )
    parser.add_argument("--grid-path", required=True, help="Remote grid file path")
    parser.add_argument("--data-path", help="Remote data file path")
    parser.add_argument("--variable-name", help="Optional face-centered variable name")
    parser.add_argument(
        "--poll-seconds", type=float, default=5.0, help="Polling interval"
    )
    parser.add_argument(
        "--timeout-seconds", type=int, default=300, help="Per-step timeout"
    )
    args = parser.parse_args()

    config = load_config()
    if not config.has_endpoint:
        raise SystemExit("No endpoint_id configured in config.yaml")

    from globus_compute_sdk import Executor
    from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

    executor = Executor(
        endpoint_id=config.endpoint_id,
        serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
    )

    results: dict[str, Any] = {}

    runtime_future = executor.submit(remote_runtime_probe)
    results["runtime_probe"] = _wait_for_future(
        "runtime_probe", runtime_future, args.poll_seconds, args.timeout_seconds
    )

    grid_probe_future = executor.submit(remote_probe_path, args.grid_path, True)
    results["grid_probe"] = _wait_for_future(
        "grid_probe", grid_probe_future, args.poll_seconds, args.timeout_seconds
    )
    if not results["grid_probe"].get("readable"):
        raise SystemExit("Grid path is not readable remotely")

    if args.data_path:
        data_probe_future = executor.submit(remote_probe_path, args.data_path, True)
        results["data_probe"] = _wait_for_future(
            "data_probe", data_probe_future, args.poll_seconds, args.timeout_seconds
        )
        if not results["data_probe"].get("readable"):
            raise SystemExit("Data path is not readable remotely")

    mesh_future = executor.submit(remote_inspect_mesh, args.grid_path)
    results["mesh_summary"] = _wait_for_future(
        "inspect_mesh", mesh_future, args.poll_seconds, args.timeout_seconds
    )

    if args.data_path:
        variable_future = executor.submit(
            remote_inspect_variable, args.grid_path, args.data_path, args.variable_name
        )
        results["variable_summary"] = _wait_for_future(
            "inspect_variable", variable_future, args.poll_seconds, args.timeout_seconds
        )

    area_future = executor.submit(remote_calculate_area, args.grid_path)
    results["area_results"] = _wait_for_future(
        "calculate_area", area_future, args.poll_seconds, args.timeout_seconds
    )

    target_variable = args.variable_name
    if not target_variable and args.data_path:
        for variable in results["variable_summary"].get("variables", []):
            if variable.get("location") == "faces":
                target_variable = variable["name"]
                break

    if target_variable and args.data_path:
        zonal_future = executor.submit(
            remote_calculate_zonal_mean,
            args.grid_path,
            args.data_path,
            target_variable,
            None,
            False,
        )
        results["zonal_mean_results"] = _wait_for_future(
            "calculate_zonal_mean",
            zonal_future,
            args.poll_seconds,
            args.timeout_seconds,
        )
        results["selected_variable"] = target_variable

    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
