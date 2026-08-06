"""Scripted adapters that stand in for a model (issue #93).

A model-in-the-loop eval that cannot be run without a model is a
liability: the harness rots silently between runs. These two adapters are
deterministic, run offline, and bracket the score range -- ``disciplined``
is what a competent run looks like, ``naive`` reproduces the exact failure
modes observed in earlier benchmark runs (paths re-specified instead of
handles, an override pushed through a refusal, no retry after an
interruption).

They also serve as the harness's own regression test: if a scoring
change stops separating these two, the scoring is broken.
"""

from __future__ import annotations

import json
import re
from typing import Any

from uxarray_mcp.preconditions import OVERRIDE_TOKEN

_PATH_RE = re.compile(r"/\S+?\.nc")
_WORKFLOW_RE = re.compile(r"workflow_id=(workflow_[A-Za-z0-9_-]+)")


def _workflow_id(messages: list[dict[str, Any]]) -> str:
    """Recover the resumable workflow id from an interruption message."""
    for message in reversed(messages):
        match = _WORKFLOW_RE.search(str(message.get("content", "")))
        if match:
            return match.group(1)
    return ""


def _paths(messages: list[dict[str, Any]]) -> dict[str, str]:
    """Recover fixture paths from the user turn, keyed by file stem."""
    user = next(m["content"] for m in messages if m["role"] == "user")
    return {
        path.rsplit("/", 1)[-1][: -len(".nc")]: path for path in _PATH_RE.findall(user)
    }


def _last_tool_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for message in reversed(messages):
        if message["role"] == "tool":
            try:
                return json.loads(message["content"])
            except json.JSONDecodeError:
                return {}
    return {}


def _step(messages: list[dict[str, Any]]) -> int:
    return sum(1 for m in messages if m["role"] == "assistant")


def _task_kind(messages: list[dict[str, Any]]) -> str:
    user = next(m["content"] for m in messages if m["role"] == "user")
    if "Start an analysis session" in user:
        return "session_handle_carry"
    if "run the canonical workflow, then look up" in user:
        return "result_handle_reuse"
    if "face-centered" in user:
        return "chained_inspect_then_analyze"
    if "vorticity" in user:
        return "refusal_then_repair"
    return "interrupted_workflow_resume"


def _call(tool: str, /, **arguments: Any) -> dict[str, Any]:
    # Positional-only: one of the tools takes a ``name`` argument of its own.
    return {
        "text": f"Calling {tool}.",
        "tool_calls": [{"name": tool, "arguments": arguments}],
    }


_FINISH = {"text": "Done.", "tool_calls": [{"name": "finish", "arguments": {}}]}


def disciplined(
    messages: list[dict[str, Any]], tools: list[dict[str, str]]
) -> dict[str, Any]:
    """Carry handles, chain correctly, repair rather than override."""
    kind = _task_kind(messages)
    step = _step(messages)
    paths = _paths(messages)
    last = _last_tool_payload(messages)

    if kind == "session_handle_carry":
        if step == 0:
            return _call("create_session", name="multi-turn-eval")
        if step == 1:
            return _call(
                "register_dataset",
                session_id=last.get("session_id", ""),
                grid_path=paths["labeled_grid"],
                data_path=paths["labeled_data"],
            )
        if step == 2:
            return _call(
                "run_analysis",
                operation="calculate_area",
                session_id=last.get("session_id", ""),
                dataset_handle=last.get("dataset_handle", ""),
                grid_path=paths["labeled_grid"],
            )
        return _FINISH

    if kind == "result_handle_reuse":
        if step == 0:
            return _call(
                "run_workflow",
                file_path=paths["labeled_grid"],
                data_path=paths["labeled_data"],
            )
        if step == 1:
            return _call(
                "get_result_handle", result_handle=last.get("result_handle", "")
            )
        return _FINISH

    if kind == "chained_inspect_then_analyze":
        if step == 0:
            return _call(
                "run_analysis",
                operation="inspect_variable",
                grid_path=paths["labeled_grid"],
                data_path=paths["labeled_data"],
            )
        if step == 1:
            variables = last.get("variables") or []
            face_vars = [v["name"] for v in variables if v.get("location") == "faces"]
            return _call(
                "run_analysis",
                operation="calculate_zonal_mean",
                grid_path=paths["labeled_grid"],
                data_path=paths["labeled_data"],
                variable_name=face_vars[0] if face_vars else "u",
            )
        return _FINISH

    if kind == "refusal_then_repair":
        if step == 0:
            return _call(
                "run_analysis",
                operation="curl",
                grid_path=paths["unlabeled_grid"],
                data_path=paths["unlabeled_data"],
                u_variable="u",
                v_variable="v",
            )
        if step == 1:
            # The refusal named the missing metadata, and a labeled copy
            # was offered in the prompt: fix the input, do not override.
            return _call(
                "run_analysis",
                operation="curl",
                grid_path=paths["labeled_grid"],
                data_path=paths["labeled_data"],
                u_variable="u",
                v_variable="v",
            )
        return _FINISH

    if step == 0:
        return _call(
            "run_workflow",
            file_path=paths["labeled_grid"],
            data_path=paths["labeled_data"],
        )
    if step == 1:
        # The interruption reported the workflow id: resume it rather
        # than starting a second workflow from scratch.
        return _call("resume_workflow", workflow_id=_workflow_id(messages))
    if step == 2:
        return _call(
            "get_workflow_status",
            workflow_id=last.get("workflow_id") or _workflow_id(messages),
        )
    return _FINISH


def naive(
    messages: list[dict[str, Any]], tools: list[dict[str, str]]
) -> dict[str, Any]:
    """Reproduce the observed failure modes: drop, invent, override, give up."""
    kind = _task_kind(messages)
    step = _step(messages)
    paths = _paths(messages)

    if kind == "session_handle_carry":
        if step == 0:
            return _call("create_session", name="multi-turn-eval")
        if step == 1:
            # Invents a handle rather than reading the one just returned.
            return _call(
                "register_dataset",
                session_id="session_00000000",
                grid_path=paths["labeled_grid"],
                data_path=paths["labeled_data"],
            )
        return _FINISH

    if kind == "result_handle_reuse":
        if step == 0:
            return _call(
                "run_workflow",
                file_path=paths["labeled_grid"],
                data_path=paths["labeled_data"],
            )
        return _FINISH

    if kind == "chained_inspect_then_analyze":
        if step == 0:
            # Skips inspection and guesses the variable name.
            return _call(
                "run_analysis",
                operation="calculate_zonal_mean",
                grid_path=paths["labeled_grid"],
                data_path=paths["labeled_data"],
                variable_name="temperature",
            )
        return _FINISH

    if kind == "refusal_then_repair":
        if step == 0:
            return _call(
                "run_analysis",
                operation="curl",
                grid_path=paths["unlabeled_grid"],
                data_path=paths["unlabeled_data"],
                u_variable="u",
                v_variable="v",
            )
        if step == 1:
            # Forces the refusal instead of fixing the cause.
            return _call(
                "run_analysis",
                operation="curl",
                grid_path=paths["unlabeled_grid"],
                data_path=paths["unlabeled_data"],
                u_variable="u",
                v_variable="v",
                acknowledge=OVERRIDE_TOKEN,
            )
        return _FINISH

    if step == 0:
        return _call(
            "run_workflow",
            file_path=paths["labeled_grid"],
            data_path=paths["labeled_data"],
        )
    # Reports the failure and stops rather than resuming.
    return {"text": "The workflow failed, so no result is available.", "tool_calls": []}
