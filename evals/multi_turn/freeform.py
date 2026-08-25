"""Free-form code-execution arm for the multi-turn eval.

The typed arms hand the model a small catalog of validated tools. This arm
answers the obvious objection to that design: why not simply let the model
write Python against the library directly?

Everything except the action surface is held fixed -- same five tasks, same
fixtures, same model set, same turn budget, same scoring. The model gets one
tool, ``run_python``, executing in a namespace with ``uxarray`` imported and
the fixture paths bound. That is the strongest honest form of the
"just let it write code" alternative: a real interpreter, real data, and no
sandbox games.

Scoring reuses ``score_run`` so the two arms are directly comparable, with
two additions specific to code execution:

``silent_wrong``
    the run finished and produced a number, but the number is wrong. This
    is the failure mode the typed arm is designed to make impossible, and
    it is invisible to a transport-level success check.
``traceback_turns``
    turns whose result was an exception rather than a value.
"""

from __future__ import annotations

import io
import math
import re
import traceback
from contextlib import redirect_stdout
from typing import Any, Callable

from .harness import MAX_TURNS, score_run

#: One tool, deliberately. The point of this arm is an unconstrained
#: action surface.
CODE_CATALOG: list[dict[str, str]] = [
    {
        "name": "run_python",
        "description": (
            "Execute Python in a persistent namespace. 'uxarray' is imported "
            "as ux and numpy as np. The variables GRID_PATH, DATA_PATH, "
            "UNLABELED_GRID_PATH and UNLABELED_DATA_PATH hold the fixture "
            "file paths. Args: code (str). Returns stdout and the repr of "
            "the last expression, or the traceback if it raised."
        ),
    },
    {"name": "finish", "description": "Finish the task and report the answer."},
]

CODE_SYSTEM = (
    "You are a scientific assistant working with unstructured-mesh data. "
    "Complete the user's request by writing Python with the run_python tool. "
    "The uxarray library is available as ux. Report a final numeric answer "
    "when the task asks for one."
)

#: Tolerance for accepting a reported number as scientifically correct.
_REL_TOL = 0.02


class CodeExecutor:
    """Execute model-authored Python in one persistent namespace."""

    def __init__(self, fixtures: dict[str, Any]) -> None:
        import numpy as np
        import uxarray as ux

        grid, data = fixtures["labeled"]
        unlabeled_grid, unlabeled_data = fixtures["unlabeled"]
        self.namespace: dict[str, Any] = {
            "ux": ux,
            "uxarray": ux,
            "np": np,
            "GRID_PATH": str(grid),
            "DATA_PATH": str(data),
            "UNLABELED_GRID_PATH": str(unlabeled_grid),
            "UNLABELED_DATA_PATH": str(unlabeled_data),
        }
        self.calls: list[dict[str, Any]] = []
        self.minted: set[str] = set()
        self.fault_fired = False
        self.tracebacks = 0

    def __call__(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        record: dict[str, Any] = {"name": name, "arguments": arguments}
        if name != "run_python":
            record["error"] = f"unknown tool {name!r}"
            self.calls.append(record)
            return {"error": record["error"]}

        code = str(arguments.get("code", ""))
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                try:
                    value = eval(  # noqa: S307 - the arm under test
                        compile(code, "<model>", "eval"), self.namespace
                    )
                    if value is not None:
                        print(repr(value))
                except SyntaxError:
                    exec(  # noqa: S102 - the arm under test
                        compile(code, "<model>", "exec"), self.namespace
                    )
            payload = {"stdout": buffer.getvalue()[-2000:]}
        except Exception:
            self.tracebacks += 1
            trace = traceback.format_exc()[-1200:]
            record["error"] = trace.strip().splitlines()[-1]
            self.calls.append(record)
            return {"traceback": trace}

        self.calls.append(record)
        return payload


_NUMBER_RE = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")


def _reported_numbers(messages: list[dict[str, Any]]) -> list[float]:
    """Every number in the model's final prose turn.

    Deliberately generous: a run counts as correct when *any* number it
    reported matches the truth. Scoring the last token only would punish
    formatting rather than science, which would overstate the case
    against this arm.
    """
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        text = str(message.get("content", ""))
        if not text.strip():
            continue
        out: list[float] = []
        for token in _NUMBER_RE.findall(text):
            try:
                out.append(float(token))
            except ValueError:
                continue
        if out:
            return out
    return []


def _matches(reported: list[float], accepted: list[float]) -> bool:
    return any(
        math.isclose(r, a, rel_tol=_REL_TOL, abs_tol=1e-9)
        for r in reported
        for a in accepted
    )


def _flagged_unlabeled(messages: list[dict[str, Any]]) -> bool:
    """Did the model warn that the unlabeled field is uninterpretable?"""
    words = (
        "unlabel",
        "no units",
        "missing units",
        "not physically",
        "uninterpretable",
        "cannot be interpreted",
        "metadata",
        "standard_name",
        "eastward",
    )
    for message in messages:
        if message.get("role") != "assistant":
            continue
        low = str(message.get("content", "")).lower()
        if any(w in low for w in words):
            return True
    return False


def _touched_unlabeled(executor: "CodeExecutor") -> bool:
    for call in executor.calls:
        code = str(call["arguments"].get("code", ""))
        if "UNLABELED" in code:
            return True
    return False


def make_adapter(
    model_adapter: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    """Wrap a model adapter so it sees only the code catalog."""

    def adapter(
        messages: list[dict[str, Any]], _catalog: list[dict[str, str]]
    ) -> dict[str, Any]:
        return model_adapter(messages, CODE_CATALOG)

    return adapter


def run_code_task(
    model_adapter: Callable[..., dict[str, Any]],
    task: dict[str, Any],
    fixtures: dict[str, Any],
    truth: dict[str, float],
) -> dict[str, Any]:
    """Run one task against the free-form code arm and score it."""
    executor = CodeExecutor(fixtures)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": CODE_SYSTEM},
        {"role": "user", "content": task["prompt"]},
    ]
    finished = False
    for _turn in range(MAX_TURNS):
        response = model_adapter(messages, CODE_CATALOG)
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
            messages.append({"role": "tool", "content": str(payload)[:2000]})
        if stop:
            break

    scored = score_run(task, executor, messages, finished)

    accepted = truth.get(task["id"])
    reported = _reported_numbers(messages)
    correct: bool | None = None
    silent_wrong = False
    if accepted:
        correct = _matches(reported, accepted)
        # A silent wrong answer is the failure the typed arm exists to
        # prevent: the run terminated normally and stated a number, and
        # the number is not right.
        silent_wrong = bool(reported) and not correct

    # The refusal task is the scientific-guardrail probe. The typed arm
    # refuses the unlabeled field outright; free-form code will happily
    # compute a curl from it. Credit the model only if it noticed.
    guardrail: bool | None = None
    if task.get("fault") == "refusal":
        guardrail = (not _touched_unlabeled(executor)) or _flagged_unlabeled(messages)

    scored["reported_numbers"] = reported
    scored["accepted_numbers"] = accepted
    scored["answer_correct"] = correct
    scored["silent_wrong"] = silent_wrong
    scored["guardrail_respected"] = guardrail
    scored["traceback_turns"] = executor.tracebacks
    scored["arm"] = "freeform"
    return scored
