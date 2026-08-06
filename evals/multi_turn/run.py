"""Run the multi-turn behavior eval (issue #93).

Scores three things across a small fixed task set, per model:

- **chaining**: did the run make the calls the task actually requires, in
  order, rather than answering from one call
- **handle discipline**: were minted handles reused, invented, or dropped
- **recovery**: after an injected mid-sequence fault (a precondition
  refusal, or a transient workflow failure), did the run repair and
  continue, or proceed on bad state

Run it offline against the two scripted adapters to check the harness:

    uv run python -m evals.multi_turn.run

Run it against a real deployment by naming an adapter and the exact
model identifier, as in ``evals/indirect_injection``:

    uv run python -m evals.multi_turn.run --adapter my.module:fn --model-id <id>
"""

from __future__ import annotations

import argparse
import importlib
import json
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from evals.multi_turn.harness import run_task
from evals.multi_turn.tasks import build_tasks

Adapter = Callable[[list[dict[str, Any]], list[dict[str, str]]], dict[str, Any]]


def _load_adapter(spec: str) -> Adapter:
    module, name = spec.split(":", 1)
    return getattr(importlib.import_module(module), name)


def make_fixtures(tmp_dir: Path) -> dict[str, tuple[str, str]]:
    """Write a labeled and an unlabeled copy of the same wind field.

    The unlabeled copy is what makes ``refusal_then_repair`` a real test:
    the two datasets are numerically identical, so the only thing that
    can distinguish a repair from a guess is the metadata the refusal
    complained about.
    """
    import numpy as np
    import uxarray as ux
    import xarray as xr

    lon = np.arange(0, 360, 20.0)
    lat = np.arange(-80, 81, 20.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid_ds = grid.to_xarray()
    grid_ds.attrs["sphere_radius"] = 6371000.0

    rng = np.random.default_rng(93)
    u = rng.standard_normal(grid.n_face)
    v = rng.standard_normal(grid.n_face)

    fixtures: dict[str, tuple[str, str]] = {}
    for kind, attrs in (
        (
            "labeled",
            (
                {"units": "m s-1", "standard_name": "eastward_wind"},
                {"units": "m s-1", "standard_name": "northward_wind"},
            ),
        ),
        ("unlabeled", ({}, {})),
    ):
        grid_file = tmp_dir / f"{kind}_grid.nc"
        data_file = tmp_dir / f"{kind}_data.nc"
        grid_ds.to_netcdf(grid_file)
        xr.Dataset(
            {"u": (["n_face"], u, attrs[0]), "v": (["n_face"], v, attrs[1])}
        ).to_netcdf(data_file)
        fixtures[kind] = (str(grid_file), str(data_file))
    return fixtures


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-task scores into the reported numbers."""
    fault_runs = [r for r in runs if r["recovered"] is not None]
    return {
        "tasks": len(runs),
        "finished": sum(r["finished"] for r in runs),
        "chained": sum(r["chained"] for r in runs),
        "handles_invented": sum(bool(r["handles_invented"]) for r in runs),
        "handles_dropped": sum(r["handle_dropped"] for r in runs),
        "overrides_used": sum(r["override_used"] for r in runs),
        "fault_tasks": len(fault_runs),
        "recovered": sum(bool(r["recovered"]) for r in fault_runs),
        "mean_calls": (
            round(sum(r["n_calls"] for r in runs) / len(runs), 2) if runs else 0.0
        ),
    }


def _print_table(runs: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    header = f"{'task':<32}{'calls':>6}{'chain':>7}{'inv':>5}{'drop':>6}{'recov':>7}"
    print(header)
    print("-" * len(header))
    for run in runs:
        recovered = "-" if run["recovered"] is None else str(bool(run["recovered"]))
        print(
            f"{run['task_id']:<32}{run['n_calls']:>6}{str(run['chained']):>7}"
            f"{str(bool(run['handles_invented'])):>5}"
            f"{str(run['handle_dropped']):>6}{recovered:>7}"
        )
    print("-" * len(header))
    print(json.dumps(summary, indent=2))


def run_suite(adapter: Adapter, adapter_name: str, model_id: str) -> dict[str, Any]:
    """Run every task once against one adapter in an isolated state dir."""
    import os

    with tempfile.TemporaryDirectory(prefix="multi_turn_eval_") as td:
        tmp_dir = Path(td)
        previous = os.environ.get("UXARRAY_MCP_STATE_DIR")
        os.environ["UXARRAY_MCP_STATE_DIR"] = str(tmp_dir / "state")
        try:
            tasks = build_tasks(make_fixtures(tmp_dir))
            runs: list[dict[str, Any]] = []
            for task in tasks:
                try:
                    runs.append(run_task(adapter, task))
                except Exception:  # noqa: BLE001 - a crashed task still scores
                    runs.append(
                        {
                            "task_id": task["id"],
                            "fault": task.get("fault"),
                            "call_names": [],
                            "n_calls": 0,
                            "finished": False,
                            "chained": False,
                            "handles_minted": [],
                            "handles_reused": [],
                            "handles_invented": [],
                            "handle_dropped": False,
                            "refusals_seen": 0,
                            "override_used": False,
                            "recovered": False if task.get("fault") else None,
                            "errors": [traceback.format_exc()[:500]],
                            "transcript_turns": 0,
                        }
                    )
        finally:
            if previous is None:
                os.environ.pop("UXARRAY_MCP_STATE_DIR", None)
            else:
                os.environ["UXARRAY_MCP_STATE_DIR"] = previous

    return {
        "adapter": adapter_name,
        "model_id": model_id,
        "summary": summarize(runs),
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--adapter",
        action="append",
        default=None,
        help="module:function adapter; repeat to compare. Defaults to the "
        "two scripted adapters.",
    )
    parser.add_argument(
        "--model-id",
        default="scripted",
        help="Exact model/deployment identifier recorded in the artifact.",
    )
    args = parser.parse_args()

    specs = args.adapter or [
        "evals.multi_turn.scripted:disciplined",
        "evals.multi_turn.scripted:naive",
    ]
    reports = []
    for spec in specs:
        report = run_suite(_load_adapter(spec), spec, args.model_id)
        print(f"\n=== {spec} ===")
        _print_table(report["runs"], report["summary"])
        reports.append(report)

    payload = {
        "protocol_version": 1,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system_prompt_hash": None,
        "reports": reports,
    }
    out_dir = Path(__file__).resolve().parent.parent / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"multi_turn_{int(time.time())}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nWrote {out_path}")

    # Non-zero only when the reference adapter regresses: a real model
    # scoring badly is a finding, not a broken build.
    reference = next(
        (r for r in reports if r["adapter"].endswith(":disciplined")),
        None,
    )
    if reference is None:
        return 0
    good = reference["summary"]
    ok = (
        good["chained"] == good["tasks"]
        and good["handles_invented"] == 0
        and good["recovered"] == good["fault_tasks"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
