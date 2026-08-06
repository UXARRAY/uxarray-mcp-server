#!/usr/bin/env python3
"""Run a repeated, provenance-preserving UXarray MCP facility matrix.

This runner deliberately separates comparable endpoint checks from native-data
demonstrations.  The ``portable`` workload uses a generated HEALPix fixture
(``healpix:8``) understood by UXarray on every worker.  Native workloads are
endpoint-specific paths and are reported only as deployment demonstrations.

It does *not* fabricate a cross-facility benchmark: each result retains the
endpoint, worker software version, operation, requested workload, timing
sample, and error.  Run after workers are live, for example:

  uv run --extra hpc python scripts/facility_matrix.py \
    --endpoints chrysalis improv ucar --repetitions 10 \
    --native-manifest artifacts/facility_matrix/native_paths.json

The optional manifest is ``{endpoint: {grid_path: ..., label: ...}}``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any


def _percentile(values: list[float], percentile: float) -> float:
    values = sorted(values)
    if not values:
        return float("nan")
    index = (len(values) - 1) * percentile
    low, high = int(index), min(int(index) + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    times = [sample["wall_seconds"] for sample in samples if sample.get("ok")]
    return {
        "attempts": len(samples),
        "successes": len(times),
        "failures": len(samples) - len(times),
        "median_seconds": statistics.median(times) if times else None,
        "iqr_seconds": (_percentile(times, 0.75) - _percentile(times, 0.25))
        if times
        else None,
        "min_seconds": min(times) if times else None,
        "max_seconds": max(times) if times else None,
    }


def _call(endpoint: str, operation: str, grid_path: str) -> dict[str, Any]:
    from uxarray_mcp.tools import run_analysis

    started = time.perf_counter()
    try:
        result = run_analysis(
            operation=operation, grid_path=grid_path, use_remote=True, endpoint=endpoint
        )
        elapsed = time.perf_counter() - started
        provenance = result.get("_provenance", {})
        return {
            "ok": True,
            "wall_seconds": elapsed,
            "provenance": provenance,
            "result_summary": {
                key: value for key, value in result.items() if key != "_provenance"
            },
        }
    except Exception as exc:  # results must retain endpoint failures
        return {
            "ok": False,
            "wall_seconds": time.perf_counter() - started,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoints", nargs="+", required=True)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--portable-grid", default="healpix:8")
    parser.add_argument("--native-manifest", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("evals/results/facility_matrix.json")
    )
    args = parser.parse_args()
    if args.repetitions < 2:
        parser.error("--repetitions must be at least 2")

    native = (
        json.loads(args.native_manifest.read_text()) if args.native_manifest else {}
    )
    report: dict[str, Any] = {
        "protocol": {
            "portable_grid": args.portable_grid,
            "repetitions": args.repetitions,
            "native_comparability": "deployment demonstration only",
        },
        "endpoints": {},
    }

    from uxarray_mcp.tools import diagnose_endpoint

    for endpoint in args.endpoints:
        entry: dict[str, Any] = {
            "preflight": diagnose_endpoint(action="status", endpoint=endpoint),
            "portable": {},
            "native": None,
        }
        for operation in ("inspect_mesh", "calculate_area"):
            samples = [
                _call(endpoint, operation, args.portable_grid)
                for _ in range(args.repetitions)
            ]
            entry["portable"][operation] = {
                "samples": samples,
                "summary": _summary(samples),
            }
        config = native.get(endpoint)
        if config:
            # One call deliberately demonstrates a facility-local production path.
            sample = _call(endpoint, "inspect_mesh", config["grid_path"])
            entry["native"] = {
                "label": config.get("label", config["grid_path"]),
                "sample": sample,
            }
        report["endpoints"][endpoint] = entry

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2))
    for endpoint, entry in report["endpoints"].items():
        print(endpoint)
        for operation, result in entry["portable"].items():
            summary = result["summary"]
            print(
                f"  portable {operation}: {summary['successes']}/{summary['attempts']} ok; median={summary['median_seconds']}"
            )
        print(f"  native: {'configured' if entry['native'] else 'not configured'}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
