"""Run the free-form code arm across the model set.

Usage:

    uv run python -m evals.multi_turn.run_freeform \
        --models argo:gpt-4o,argo:gpt-5 --out evals/results/freeform.json
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from .freeform import run_code_task
from .run import make_fixtures
from .tasks import build_tasks


def _truth(fixtures: dict[str, Any]) -> dict[str, list[float]]:
    """Accepted answers per task, computed from the fixtures themselves."""
    import numpy as np
    import uxarray as ux

    grid_path, data_path = fixtures["labeled"]
    uxgrid = ux.open_grid(grid_path)
    areas = np.asarray(uxgrid.face_areas.values)

    # The area task asks for "face-area statistics"; accept any of the
    # summary values a reasonable answer would quote.
    area_stats = [
        float(areas.sum()),
        float(areas.mean()),
        float(areas.min()),
        float(areas.max()),
        float(uxgrid.n_face),
    ]
    return {
        "session_handle_carry": area_stats,
        "chained_inspect_then_analyze": area_stats,
    }


def run_model(model_id: str) -> dict[str, Any]:
    from ..live_model import adapter as live_adapter

    previous_model = os.environ.get("EVAL_MODEL_ID")
    os.environ["EVAL_MODEL_ID"] = model_id

    with tempfile.TemporaryDirectory(prefix="freeform_eval_") as td:
        tmp_dir = Path(td)
        previous_state = os.environ.get("UXARRAY_MCP_STATE_DIR")
        os.environ["UXARRAY_MCP_STATE_DIR"] = str(tmp_dir / "state")
        try:
            fixtures = make_fixtures(tmp_dir)
            tasks = build_tasks(fixtures)
            truth = _truth(fixtures)
            runs: list[dict[str, Any]] = []
            for task in tasks:
                try:
                    runs.append(run_code_task(live_adapter, task, fixtures, truth))
                except Exception:  # noqa: BLE001 - a crashed task still scores
                    runs.append(
                        {
                            "task_id": task["id"],
                            "arm": "freeform",
                            "finished": False,
                            "chained": False,
                            "n_calls": 0,
                            "silent_wrong": False,
                            "answer_correct": None,
                            "guardrail_respected": None,
                            "traceback_turns": 0,
                            "errors": [traceback.format_exc()[:500]],
                        }
                    )
        finally:
            if previous_state is None:
                os.environ.pop("UXARRAY_MCP_STATE_DIR", None)
            else:
                os.environ["UXARRAY_MCP_STATE_DIR"] = previous_state
            if previous_model is None:
                os.environ.pop("EVAL_MODEL_ID", None)
            else:
                os.environ["EVAL_MODEL_ID"] = previous_model

    scored = [r for r in runs if r.get("answer_correct") is not None]
    guarded = [r for r in runs if r.get("guardrail_respected") is not None]
    return {
        "model_id": model_id,
        "arm": "freeform",
        "summary": {
            "tasks": len(runs),
            "finished": sum(bool(r.get("finished")) for r in runs),
            "scored_tasks": len(scored),
            "answer_correct": sum(bool(r.get("answer_correct")) for r in scored),
            "silent_wrong": sum(bool(r.get("silent_wrong")) for r in runs),
            "guardrail_tasks": len(guarded),
            "guardrail_respected": sum(
                bool(r.get("guardrail_respected")) for r in guarded
            ),
            "traceback_turns": sum(int(r.get("traceback_turns", 0)) for r in runs),
            "mean_calls": (
                round(sum(int(r.get("n_calls", 0)) for r in runs) / len(runs), 2)
                if runs
                else 0.0
            ),
        },
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    reports = []
    for model_id in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"=== {model_id}", flush=True)
        try:
            report = run_model(model_id)
        except Exception as exc:  # noqa: BLE001
            print(f"    FAILED {exc}", flush=True)
            continue
        print(f"    {report['summary']}", flush=True)
        reports.append(report)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "protocol_version": 1,
                "arm": "freeform",
                "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "reports": reports,
            },
            indent=1,
        )
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
