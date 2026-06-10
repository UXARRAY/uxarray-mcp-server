"""Run the schema-rejection eval.

What this does: build a small set of synthetic mesh fixtures, then call
run_analysis / plot_dataset with a fixed set of deliberately-bad inputs.
Classify each outcome and write a JSON report.

The goal is not to test individual functions (the unit tests do that). It is
to put a number on "how often does the typed boundary catch bad calls before
they spend compute." See README.md.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

from evals.schema_rejection.cases import build_cases


def _make_fixtures(tmp_dir: Path) -> tuple[str, tuple[str, str]]:
    """Create a synthetic grid and (grid, data) pair on disk. Returns paths."""
    import xarray as xr

    # Single-triangle UGRID
    grid_ds = xr.Dataset(
        {
            "Mesh2": (
                [],
                0,
                {
                    "cf_role": "mesh_topology",
                    "topology_dimension": 2,
                    "node_coordinates": "Mesh2_node_x Mesh2_node_y",
                    "face_node_connectivity": "Mesh2_face_nodes",
                },
            ),
            "Mesh2_node_x": (["nMesh2_node"], [0.0, 1.0, 0.5]),
            "Mesh2_node_y": (["nMesh2_node"], [0.0, 0.0, 1.0]),
            "Mesh2_face_nodes": (
                ["nMesh2_face", "nMaxMesh2_face_nodes"],
                [[0, 1, 2]],
                {"cf_role": "face_node_connectivity", "start_index": 0},
            ),
        }
    )
    data_ds = xr.Dataset(
        {
            "temperature": (
                ["nMesh2_face"],
                [288.15],
                {"units": "K", "long_name": "Temperature"},
            ),
        }
    )
    grid_only = tmp_dir / "grid_only.nc"
    grid_for_data = tmp_dir / "grid.nc"
    data_path = tmp_dir / "data.nc"
    grid_ds.to_netcdf(grid_only)
    grid_ds.to_netcdf(grid_for_data)
    data_ds.to_netcdf(data_path)
    return str(grid_only), (str(grid_for_data), str(data_path))


def _classify(outcome: str, exc_type: str | None) -> str:
    """Bucket the outcome into one of the four reporting categories."""
    if outcome == "ok":
        return "silent_pass"
    if exc_type is None:
        return "silent_pass"
    if exc_type in ("ValueError", "TypeError", "KeyError"):
        # Front-door _require raises ValueError; missing kwargs raise TypeError
        return "schema_rejected"
    if exc_type in ("FileNotFoundError", "OSError", "PermissionError"):
        return "io_rejected"
    return "runtime_error"


def run_case(case: dict) -> dict:
    """Execute one case, classify result. Never propagates exceptions."""
    from uxarray_mcp.tools import plot_dataset as plot_dataset_tool
    from uxarray_mcp.tools import run_analysis as run_analysis_tool

    tool_fn = run_analysis_tool if case["tool"] == "run_analysis" else plot_dataset_tool
    t0 = time.perf_counter()
    outcome: str = "ok"
    exc_type: str | None = None
    exc_msg: str | None = None
    try:
        tool_fn(**case["kwargs"])
    except BaseException as exc:  # noqa: BLE001
        outcome = "error"
        exc_type = type(exc).__name__
        exc_msg = str(exc)[:200]
    elapsed_ms = (time.perf_counter() - t0) * 1000

    classification = _classify(outcome, exc_type)
    # Baseline cases (expected='accept') invert the success criterion:
    # silent_pass is GOOD; rejection is BAD.
    if case["expected"] == "accept":
        is_correct = classification == "silent_pass"
    else:
        is_correct = classification != "silent_pass"

    return {
        "id": case["id"],
        "description": case["description"],
        "tool": case["tool"],
        "expected": case["expected"],
        "classification": classification,
        "exc_type": exc_type,
        "exc_msg": exc_msg,
        "is_correct": is_correct,
        "elapsed_ms": round(elapsed_ms, 2),
    }


def summarize(results: list[dict]) -> dict:
    total = len(results)
    reject_cases = [r for r in results if r["expected"] == "reject"]
    accept_cases = [r for r in results if r["expected"] == "accept"]
    rejects_total = len(reject_cases)

    counts = {
        "schema_rejected": 0,
        "io_rejected": 0,
        "runtime_error": 0,
        "silent_pass": 0,
    }
    for r in reject_cases:
        counts[r["classification"]] += 1

    caught = counts["schema_rejected"] + counts["io_rejected"] + counts["runtime_error"]
    silent_failures = counts["silent_pass"]

    return {
        "total_cases": total,
        "baseline_cases": len(accept_cases),
        "baseline_correct": sum(1 for r in accept_cases if r["is_correct"]),
        "malformed_cases": rejects_total,
        "counts": counts,
        "caught_rate": round(caught / rejects_total, 3) if rejects_total else None,
        "silent_failures": silent_failures,
        "by_layer_pct": {
            "schema": round(100 * counts["schema_rejected"] / rejects_total, 1)
            if rejects_total
            else None,
            "io": round(100 * counts["io_rejected"] / rejects_total, 1)
            if rejects_total
            else None,
            "runtime": round(100 * counts["runtime_error"] / rejects_total, 1)
            if rejects_total
            else None,
            "silent": round(100 * silent_failures / rejects_total, 1)
            if rejects_total
            else None,
        },
    }


def _print_table(results: list[dict], summary: dict) -> None:
    print()
    print(f"{'id':38s} {'expect':8s} {'classification':18s} {'ok'}")
    print("-" * 80)
    for r in results:
        mark = "✓" if r["is_correct"] else "✗"
        print(f"{r['id']:38s} {r['expected']:8s} {r['classification']:18s} {mark}")
    print()
    print("SUMMARY")
    print(f"  Total cases:            {summary['total_cases']}")
    print(
        f"  Baseline OK:            "
        f"{summary['baseline_correct']}/{summary['baseline_cases']} "
        f"(well-formed calls that ran)"
    )
    print(f"  Malformed caught rate:  {summary['caught_rate']}")
    print(f"  Silent failures (bugs): {summary['silent_failures']}")
    pct = summary["by_layer_pct"]
    print(
        f"  By layer: schema={pct['schema']}%  io={pct['io']}%  "
        f"runtime={pct['runtime']}%  silent={pct['silent']}%"
    )
    print()
    if summary["silent_failures"] == 0:
        print("PASS — no silent failures on malformed inputs.")
    else:
        print("FAIL — at least one malformed call returned a result silently.")


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="schema_eval_") as td:
        grid_only, grid_with_data = _make_fixtures(Path(td))
        cases = build_cases(grid_only, grid_with_data)
        results = []
        for case in cases:
            try:
                results.append(run_case(case))
            except Exception:  # noqa: BLE001
                results.append(
                    {
                        "id": case["id"],
                        "description": case["description"],
                        "tool": case["tool"],
                        "expected": case["expected"],
                        "classification": "runner_error",
                        "exc_type": "RunnerError",
                        "exc_msg": traceback.format_exc()[:500],
                        "is_correct": False,
                        "elapsed_ms": 0.0,
                    }
                )

    summary = summarize(results)
    _print_table(results, summary)

    out_dir = Path(__file__).resolve().parent.parent / "results"
    out_dir.mkdir(exist_ok=True)
    ts = int(time.time())
    out_path = out_dir / f"schema_{ts}.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(f"\nWrote {out_path}")
    return 0 if summary["silent_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
