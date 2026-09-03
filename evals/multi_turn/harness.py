"""Tool-calling harness for the multi-turn eval (issue #93).

The harness executes **real** server tools against real synthetic
fixtures in a temporary state directory. Nothing here is mocked except
the deliberate transient fault, because a handle that is only pretend
cannot be dropped or invented in an interesting way.

The model is behind an adapter boundary, exactly as in
``evals/indirect_injection``: an adapter receives OpenAI-shaped messages
plus the tool catalog and returns ``{"text": str, "tool_calls": [...]}``.
Two scripted adapters ship with the eval so the harness itself can be
regression-tested without a model or a network call.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from uxarray_mcp.preconditions import OVERRIDE_TOKEN

#: Tools the model may call. Kept small on purpose: the question is
#: whether multi-step state is handled, not whether the whole catalog is
#: navigable (that is what ``evals/tool_retrieval`` measures).
TOOL_CATALOG: list[dict[str, str]] = [
    {
        "name": "create_session",
        "description": "Start a session that persists datasets and results across calls. Returns session_id.",
    },
    {
        "name": "register_dataset",
        "description": "Register a grid/data pair in a session. Args: session_id, grid_path, data_path. Returns dataset_handle.",
    },
    {
        "name": "run_analysis",
        "description": "Run one analysis operation. Args: operation, plus grid_path/data_path or session_id/dataset_handle.",
    },
    {
        "name": "run_workflow",
        "description": "Run the canonical scientific workflow. Args: file_path, data_path. Returns workflow_id and result_handle.",
    },
    {
        "name": "resume_workflow",
        "description": "Resume a persisted workflow from its first pending or failed step. Args: workflow_id.",
    },
    {
        "name": "get_workflow_status",
        "description": "Return persisted workflow progress and final result handle. Args: workflow_id.",
    },
    {
        "name": "get_result_handle",
        "description": "Inspect a persisted result handle and its artifact metadata. Args: result_handle.",
    },
    {"name": "finish", "description": "Finish the task and report the answer."},
]

SYSTEM = (
    "You are a scientific assistant working with an unstructured-mesh analysis "
    "server. Complete the user's request using the provided tools. Handles "
    "returned by a tool (session_id, dataset_handle, workflow_id, result_handle) "
    "are opaque: pass them back verbatim and never invent one. If a tool refuses "
    "with outcome='input_required', read the failed checks and fix the cause "
    "rather than forcing the call through."
)

MAX_TURNS = 8

#: Any string shaped like one of the server's minted handles.
_HANDLE_RE = re.compile(r"\b(?:session|dataset|result|workflow|op)_[A-Za-z0-9_-]+")


class ToolExecutor:
    """Dispatch whitelisted tool names onto the real server tools."""

    def __init__(self, fault: str | None) -> None:
        self.fault = fault
        self.fault_fired = False
        self.minted: set[str] = set()
        self.calls: list[dict[str, Any]] = []

    def _mint(self, payload: dict[str, Any]) -> None:
        for key in (
            "session_id",
            "dataset_handle",
            "result_handle",
            "workflow_id",
            "operation_id",
        ):
            value = payload.get(key)
            if isinstance(value, str):
                self.minted.add(value)

    def _run_workflow_with_fault(
        self, run_workflow: Any, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Fail one workflow step, then re-raise with the resumable id.

        A real interruption (a node dying, a filesystem hiccup) leaves the
        persisted workflow behind, and the progress events the server emits
        carry its id. Surfacing that id on the error is what makes "resume
        instead of restarting" an available choice rather than a trick.
        """
        from unittest.mock import patch

        from uxarray_mcp.state import _state_root

        def _boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("Injected transient failure: mesh read interrupted.")

        with patch("uxarray_mcp.tools.remote_tools.inspect_mesh", _boom):
            try:
                return run_workflow(**arguments)
            except Exception as exc:
                workflows = sorted(
                    (_state_root() / "workflows").glob("*.json"),
                    key=lambda p: p.stat().st_mtime,
                )
                latest = workflows[-1].stem if workflows else None
                if latest:
                    self.minted.add(latest)
                raise RuntimeError(f"{exc} (workflow_id={latest})") from exc

    def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from uxarray_mcp.tools import (
            create_session,
            get_result_handle,
            get_workflow_status,
            register_dataset,
            resume_workflow,
            run_workflow,
        )
        from uxarray_mcp.tools.frontdoor import run_analysis

        record: dict[str, Any] = {"name": name, "arguments": arguments}
        try:
            if name == "create_session":
                payload = create_session(**arguments)
            elif name == "register_dataset":
                payload = register_dataset(**arguments)
            elif name == "run_analysis":
                payload = run_analysis(**arguments)
            elif name == "run_workflow":
                if self.fault == "transient" and not self.fault_fired:
                    # One injected failure, mid-sequence, on the first
                    # attempt only. It fires *inside* a workflow step so
                    # the workflow record survives in a resumable state --
                    # failing before the record exists would make the task
                    # untestable rather than hard.
                    self.fault_fired = True
                    payload = self._run_workflow_with_fault(run_workflow, arguments)
                else:
                    payload = run_workflow(**arguments)
            elif name == "resume_workflow":
                payload = resume_workflow(**arguments)
            elif name == "get_workflow_status":
                payload = get_workflow_status(**arguments)
            elif name == "get_result_handle":
                payload = get_result_handle(**arguments)
            else:
                raise ValueError(f"Unknown tool {name!r}.")
        except Exception as exc:  # noqa: BLE001 - the model must see failures
            record["error"] = _apply_error_mode(f"{type(exc).__name__}: {exc}")
            self.calls.append(record)
            return {"error": record["error"]}

        self._mint(payload)
        record["outcome"] = payload.get("outcome")
        record["ok"] = True
        self.calls.append(record)
        return payload


def _apply_error_mode(message: str) -> str:
    """Ablate the repair clause from an error without changing anything else.

    ``EVAL_ERROR_MODE=bare`` strips the "Did you mean ...  Supported
    operations: ..." clause that the front door attaches, leaving only the
    statement that the call failed. The tool catalog, the prompts, the
    fixtures, and the model are all held fixed, so the difference between
    the two conditions isolates the value of naming the repair in the result.
    """
    import os

    if os.environ.get("EVAL_ERROR_MODE", "repair") != "bare":
        return message
    for marker in (" Did you mean ", " Supported operations: "):
        index = message.find(marker)
        if index != -1:
            return message[:index].rstrip()
    return message


def _summarize(payload: dict[str, Any]) -> str:
    """Trim a tool result to something a model turn can carry."""
    if "error" in payload and len(payload) == 1:
        return json.dumps(payload)
    keep = {
        k: v
        for k, v in payload.items()
        if k
        in {
            "session_id",
            "dataset_handle",
            "result_handle",
            "workflow_id",
            "status",
            "outcome",
            "refusal",
            "artifact_path",
            "stats",
            "variables",
            "scientific_status",
            "preconditions",
        }
    }
    text = json.dumps(keep, default=str)
    return text[:4000]


def run_task(
    adapter: Callable[[list[dict[str, Any]], list[dict[str, str]]], dict[str, Any]],
    task: dict[str, Any],
) -> dict[str, Any]:
    """Run one task to completion (or turn budget) and return its trace."""
    executor = ToolExecutor(task.get("fault"))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task["prompt"]},
    ]
    finished = False
    for _turn in range(MAX_TURNS):
        response = adapter(messages, TOOL_CATALOG)
        text = str(response.get("text", ""))
        calls = response.get("tool_calls") or []
        messages.append({"role": "assistant", "content": text})
        if not calls:
            break
        stop = False
        for call in calls:
            if call.get("name") == "finish":
                finished = True
                stop = True
                break
            payload = executor(call.get("name", ""), call.get("arguments") or {})
            messages.append({"role": "tool", "content": _summarize(payload)})
        if stop:
            break
    return score_run(task, executor, messages, finished)


def _handles_referenced(executor: ToolExecutor) -> tuple[set[str], set[str]]:
    """Split handle-shaped arguments into (reused, invented)."""
    reused: set[str] = set()
    invented: set[str] = set()
    for call in executor.calls:
        for value in call["arguments"].values():
            if not isinstance(value, str):
                continue
            for match in _HANDLE_RE.findall(value):
                (reused if match in executor.minted else invented).add(match)
    return reused, invented


def _chained(executor: ToolExecutor, required: list[str]) -> bool:
    """True when ``required`` appears as a subsequence of the call names."""
    names = [call["name"] for call in executor.calls]
    index = 0
    for name in names:
        if index < len(required) and name == required[index]:
            index += 1
    return index == len(required)


def score_run(
    task: dict[str, Any],
    executor: ToolExecutor,
    messages: list[dict[str, Any]],
    finished: bool,
) -> dict[str, Any]:
    """Turn a trace into the pre-registered per-task scores."""
    reused, invented = _handles_referenced(executor)
    names = [call["name"] for call in executor.calls]
    refusals = [c for c in executor.calls if c.get("outcome") == "input_required"]
    override_used = any(
        OVERRIDE_TOKEN in str(call["arguments"].get("acknowledge", ""))
        for call in executor.calls
    )

    # A minted handle that was never passed back is a dropped handle --
    # the model had the state and chose to re-specify paths instead.
    dropped = bool(executor.minted) and not reused

    recovered: bool | None = None
    if task.get("fault") == "refusal":
        # Recovered means: the refusal happened, and the run still ended
        # on a real answer that was not forced through with the override.
        completed = any(
            c["name"] == "run_analysis" and c.get("outcome") == "complete"
            for c in executor.calls
        )
        recovered = bool(refusals) and completed and not override_used
    elif task.get("fault") == "transient":
        # Recovered means: retried after the injected failure and the
        # workflow reached a terminal completed state.
        recovered = executor.fault_fired and (
            "resume_workflow" in names or names.count("run_workflow") > 1
        )

    return {
        "task_id": task["id"],
        "fault": task.get("fault"),
        "call_names": names,
        "n_calls": len(names),
        "finished": finished,
        "chained": _chained(executor, task["requires"]),
        "handles_minted": sorted(executor.minted),
        "handles_reused": sorted(reused),
        "handles_invented": sorted(invented),
        "handle_dropped": dropped,
        "refusals_seen": len(refusals),
        "override_used": override_used,
        "recovered": recovered,
        "errors": [c["error"] for c in executor.calls if "error" in c],
        "transcript_turns": len([m for m in messages if m["role"] == "assistant"]),
    }
