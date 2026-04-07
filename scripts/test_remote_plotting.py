#!/usr/bin/env python3
"""Test all three remote plotting functions on Improv and save PNGs locally."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from uxarray_mcp.remote.compute_functions import (
    remote_plot_mesh,
    remote_plot_variable,
    remote_plot_zonal_mean,
)
from uxarray_mcp.remote.config import load_config

GRID_PATH = "/home/jain/uxarray/test/meshfiles/mpas/QU/480/grid.nc"
DATA_PATH = "/home/jain/uxarray/test/meshfiles/mpas/QU/480/data.nc"
VARIABLE = "bottomDepth"
POLL_SECONDS = 10
TIMEOUT_SECONDS = 300
OUT_DIR = Path(__file__).parent.parent / "test_plots"


def _wait(label: str, future):
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while not future.done():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{label} timed out after {TIMEOUT_SECONDS}s")
        print(f"  [wait] {label} still running...")
        time.sleep(POLL_SECONDS)
    return future.result()


def _save_png(label: str, result: dict) -> Path:
    OUT_DIR.mkdir(exist_ok=True)
    png_bytes = base64.b64decode(result["png_b64"])
    out_path = OUT_DIR / f"{label}.png"
    out_path.write_bytes(png_bytes)
    return out_path


def main() -> int:
    config = load_config()
    if not config.has_endpoint:
        raise SystemExit("No endpoint_id configured in config.yaml")

    from globus_compute_sdk import Executor
    from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

    executor = Executor(
        endpoint_id=config.endpoint_id,
        serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
    )

    results = {}

    # --- plot_mesh ---
    print("\n[1/3] Submitting remote_plot_mesh...")
    t0 = time.perf_counter()
    f = executor.submit(remote_plot_mesh, GRID_PATH)
    results["plot_mesh"] = _wait("plot_mesh", f)
    elapsed = round(time.perf_counter() - t0, 2)
    path = _save_png("plot_mesh", results["plot_mesh"])
    print(
        f"  OK  {elapsed}s  {results['plot_mesh']['image_size_bytes']} bytes -> {path}"
    )

    # --- plot_variable ---
    print("\n[2/3] Submitting remote_plot_variable...")
    t0 = time.perf_counter()
    f = executor.submit(remote_plot_variable, GRID_PATH, DATA_PATH, VARIABLE)
    results["plot_variable"] = _wait("plot_variable", f)
    elapsed = round(time.perf_counter() - t0, 2)
    path = _save_png("plot_variable", results["plot_variable"])
    print(
        f"  OK  {elapsed}s  {results['plot_variable']['image_size_bytes']} bytes -> {path}"
    )

    # --- plot_zonal_mean ---
    print("\n[3/3] Submitting remote_plot_zonal_mean...")
    t0 = time.perf_counter()
    f = executor.submit(remote_plot_zonal_mean, GRID_PATH, DATA_PATH, VARIABLE)
    results["plot_zonal_mean"] = _wait("plot_zonal_mean", f)
    elapsed = round(time.perf_counter() - t0, 2)
    path = _save_png("plot_zonal_mean", results["plot_zonal_mean"])
    print(
        f"  OK  {elapsed}s  {results['plot_zonal_mean']['image_size_bytes']} bytes -> {path}"
    )

    # Summary (drop png_b64 from output)
    summary = {
        k: {kk: vv for kk, vv in v.items() if kk != "png_b64"}
        for k, v in results.items()
    }
    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))
    print(f"\nPNGs saved to: {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
