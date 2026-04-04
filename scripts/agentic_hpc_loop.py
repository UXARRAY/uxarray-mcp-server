#!/usr/bin/env python3
"""Example sequential remote workflow using Globus Compute futures directly."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

import math

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


_COORDINATE_LIKE_NAMES = {
    "lat",
    "latitude",
    "lon",
    "longitude",
    "x",
    "y",
    "z",
}


def _is_coordinate_like(variable_name: str) -> bool:
    lowered = variable_name.lower()
    parts = lowered.replace("-", "_").split("_")
    return any(part in _COORDINATE_LIKE_NAMES for part in parts)


def _select_target_variable(variable_summary: dict[str, Any]) -> str | None:
    """Prefer face-centered science variables over coordinate-like variables."""
    face_variables = [
        variable
        for variable in variable_summary.get("variables", [])
        if variable.get("location") == "faces"
    ]
    for variable in face_variables:
        if not _is_coordinate_like(variable["name"]):
            return variable["name"]
    if face_variables:
        return face_variables[0]["name"]
    return None


def _nan_summary(zonal_mean_results: dict[str, Any]) -> dict[str, Any]:
    values = zonal_mean_results.get("zonal_mean_values", [])
    nan_count = sum(
        1 for value in values if isinstance(value, float) and math.isnan(value)
    )
    return {
        "n_values": len(values),
        "n_nan": nan_count,
        "all_nan": len(values) > 0 and nan_count == len(values),
    }


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
    timings: dict[str, float] = {}

    start = time.perf_counter()
    runtime_future = executor.submit(remote_runtime_probe)
    results["runtime_probe"] = _wait_for_future(
        "runtime_probe", runtime_future, args.poll_seconds, args.timeout_seconds
    )
    timings["runtime_probe_seconds"] = round(time.perf_counter() - start, 3)

    start = time.perf_counter()
    grid_probe_future = executor.submit(remote_probe_path, args.grid_path, True)
    results["grid_probe"] = _wait_for_future(
        "grid_probe", grid_probe_future, args.poll_seconds, args.timeout_seconds
    )
    timings["grid_probe_seconds"] = round(time.perf_counter() - start, 3)
    if not results["grid_probe"].get("readable"):
        raise SystemExit("Grid path is not readable remotely")

    if args.data_path:
        start = time.perf_counter()
        data_probe_future = executor.submit(remote_probe_path, args.data_path, True)
        results["data_probe"] = _wait_for_future(
            "data_probe", data_probe_future, args.poll_seconds, args.timeout_seconds
        )
        timings["data_probe_seconds"] = round(time.perf_counter() - start, 3)
        if not results["data_probe"].get("readable"):
            raise SystemExit("Data path is not readable remotely")

    start = time.perf_counter()
    mesh_future = executor.submit(remote_inspect_mesh, args.grid_path)
    results["mesh_summary"] = _wait_for_future(
        "inspect_mesh", mesh_future, args.poll_seconds, args.timeout_seconds
    )
    timings["inspect_mesh_seconds"] = round(time.perf_counter() - start, 3)

    if args.data_path:
        start = time.perf_counter()
        variable_future = executor.submit(
            remote_inspect_variable, args.grid_path, args.data_path, args.variable_name
        )
        results["variable_summary"] = _wait_for_future(
            "inspect_variable", variable_future, args.poll_seconds, args.timeout_seconds
        )
        timings["inspect_variable_seconds"] = round(time.perf_counter() - start, 3)

    start = time.perf_counter()
    area_future = executor.submit(remote_calculate_area, args.grid_path)
    results["area_results"] = _wait_for_future(
        "calculate_area", area_future, args.poll_seconds, args.timeout_seconds
    )
    timings["calculate_area_seconds"] = round(time.perf_counter() - start, 3)

    target_variable = args.variable_name
    if not target_variable and args.data_path:
        target_variable = _select_target_variable(results["variable_summary"])

    if target_variable and args.data_path:
        start = time.perf_counter()
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
        timings["calculate_zonal_mean_seconds"] = round(time.perf_counter() - start, 3)
        results["selected_variable"] = target_variable
        results["zonal_mean_summary"] = _nan_summary(results["zonal_mean_results"])

    results["timings_seconds"] = timings

    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
