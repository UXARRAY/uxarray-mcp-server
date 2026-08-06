"""Task definitions for the multi-turn eval (issue #93).

Every task here is deliberately impossible to finish in a single tool
call. That is the whole point: the median session in earlier benchmark
runs made one or two calls, so a benchmark that can be satisfied by one
call measures nothing about the machinery this server actually ships --
``create_session``, ``dataset_handle``, ``result_handle``,
``run_workflow``, ``resume_workflow``.

Each task is a dict with:

- ``id``: short slug used in the report
- ``prompt``: the user turn handed to the model
- ``requires``: tool names that must all appear, in order, for the task
  to count as chained rather than guessed
- ``fault``: optional fault injected mid-sequence, one of
  ``"refusal"`` (an operation whose preconditions fail) or
  ``"transient"`` (one call raises once, then works)
- ``recovery_ok``: predicate name describing what a recovered run looks
  like; ``None`` when the task injects no fault
"""

from __future__ import annotations

from typing import Any


def build_tasks(fixtures: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the task list, parameterized by on-disk fixture paths."""
    grid, data = fixtures["labeled"]
    unlabeled_grid, unlabeled_data = fixtures["unlabeled"]

    return [
        {
            "id": "session_handle_carry",
            "prompt": (
                "Start an analysis session, register the grid at "
                f"{grid} with data {data}, then compute the face-area "
                "statistics for that registered dataset using its handle. "
                "Do not pass the file path again once it is registered."
            ),
            "requires": ["create_session", "register_dataset", "run_analysis"],
            "fault": None,
            "recovery_ok": None,
        },
        {
            "id": "result_handle_reuse",
            "prompt": (
                f"Using the grid {grid} and data {data}, run the canonical "
                "workflow, then look up the result handle it returned and "
                "report where the artifact was written."
            ),
            "requires": ["run_workflow", "get_result_handle"],
            "fault": None,
            "recovery_ok": None,
        },
        {
            "id": "chained_inspect_then_analyze",
            "prompt": (
                f"For the dataset {grid} / {data}, first find out which "
                "variables are face-centered, then compute the zonal mean "
                "of one of them. Pick the variable from what you find; do "
                "not assume a name."
            ),
            "requires": ["run_analysis", "run_analysis"],
            "fault": None,
            "recovery_ok": None,
        },
        {
            "id": "refusal_then_repair",
            "prompt": (
                "Compute the vorticity (curl) of the wind field in "
                f"{unlabeled_data} on grid {unlabeled_grid} using u and v. "
                f"A properly labeled copy of the same field exists at {data} "
                f"on grid {grid}. Report a physically interpretable number."
            ),
            "requires": ["run_analysis", "run_analysis"],
            "fault": "refusal",
            # Recovered = the run ends on a `complete` curl result that was
            # not obtained by pushing the override token through.
            "recovery_ok": "repaired_not_overridden",
        },
        {
            "id": "interrupted_workflow_resume",
            "prompt": (
                f"Run the canonical workflow on {grid} / {data}. If it does "
                "not finish, resume it rather than starting over, and report "
                "the final status."
            ),
            "requires": ["run_workflow", "resume_workflow", "get_workflow_status"],
            "fault": "transient",
            "recovery_ok": "resumed_same_workflow",
        },
    ]
