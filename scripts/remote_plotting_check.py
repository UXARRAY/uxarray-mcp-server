#!/usr/bin/env python3
"""Exercise the three remote plotting functions on an endpoint and save PNGs.

Manual live check, not a pytest module: it submits real Globus Compute work to
a configured endpoint. Paths are cluster-specific, so pass them explicitly::

    uv run python scripts/remote_plotting_check.py \
        --endpoint chrysalis \
        --grid-path /lcrc/group/e3sm/.../grid.nc \
        --data-path /lcrc/group/e3sm/.../data.nc \
        --variable bottomDepth
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path
from typing import Any

from uxarray_mcp.remote.compute_functions import (
    remote_plot_mesh,
    remote_plot_variable,
    remote_plot_zonal_mean,
)
from uxarray_mcp.remote.config import load_config


def _wait(label: str, future: Any, timeout_seconds: int, poll_seconds: int) -> Any:
    deadline = time.monotonic() + timeout_seconds
    while not future.done():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{label} timed out after {timeout_seconds}s")
        print(f"  [wait] {label} still running...")
        time.sleep(poll_seconds)
    return future.result()


def _save_png(out_dir: Path, label: str, result: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{label}.png"
    out_path.write_bytes(base64.b64decode(result["png_b64"]))
    return out_path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", default=None, help="Configured endpoint name.")
    p.add_argument("--grid-path", required=True, help="Grid path on the worker.")
    p.add_argument("--data-path", required=True, help="Data path on the worker.")
    p.add_argument("--variable", required=True, help="Variable to plot.")
    p.add_argument("--out-dir", type=Path, default=Path("tmp/remote_plots"))
    p.add_argument("--timeout-seconds", type=int, default=300)
    p.add_argument("--poll-seconds", type=int, default=10)
    args = p.parse_args()

    config = load_config().for_endpoint(endpoint=args.endpoint)
    if not config.endpoint_id:
        raise SystemExit(f"No endpoint_id resolved for {args.endpoint!r}")

    from globus_compute_sdk import Executor
    from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

    executor = Executor(
        endpoint_id=config.endpoint_id,
        serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
    )

    submissions = (
        ("plot_mesh", remote_plot_mesh, (args.grid_path,)),
        (
            "plot_variable",
            remote_plot_variable,
            (args.grid_path, args.data_path, args.variable),
        ),
        (
            "plot_zonal_mean",
            remote_plot_zonal_mean,
            (args.grid_path, args.data_path, args.variable),
        ),
    )

    results: dict[str, dict] = {}
    try:
        for index, (label, func, call_args) in enumerate(submissions, start=1):
            print(f"\n[{index}/{len(submissions)}] Submitting remote_{label}...")
            started = time.perf_counter()
            future = executor.submit(func, *call_args)
            results[label] = _wait(
                label, future, args.timeout_seconds, args.poll_seconds
            )
            elapsed = round(time.perf_counter() - started, 2)
            saved = _save_png(args.out_dir, label, results[label])
            size = results[label]["image_size_bytes"]
            print(f"  OK  {elapsed}s  {size} bytes -> {saved}")
    finally:
        executor.shutdown(wait=False)

    summary = {
        key: {k: v for k, v in value.items() if k != "png_b64"}
        for key, value in results.items()
    }
    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))
    print(f"\nPNGs saved to: {args.out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
