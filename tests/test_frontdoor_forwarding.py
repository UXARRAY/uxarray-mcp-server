"""Every front-door parameter must reach the function it dispatches to.

``run_analysis`` and ``plot_dataset`` are the only MCP-reachable entry
points, so a parameter they accept but drop cannot be worked around: the
caller gets a plausible number computed with defaults and no signal that
the request was ignored. ``calculate_zonal_mean`` accepted ``lat_spec``,
``conservative`` and ``time_index`` and forwarded none of them.

Rather than re-check the three that broke, this walks every dispatch
branch and compares what the front door accepts against what it passes
on, so a branch added later is covered without anyone remembering to.
"""

from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import pytest

import uxarray_mcp.tools.frontdoor as frontdoor

_SEARCH_MODULES = (
    "frontdoor",
    "inspection",
    "plotting",
    "remote_tools",
    "vector_calc",
    "stateful",
    "advanced",
    "execution_control",
)

# Parameters that are deliberately consumed by the front door itself rather
# than forwarded: they select the branch or gate it, they are not inputs to
# the underlying computation.
_FRONT_DOOR_ONLY = {"operation", "plot_type", "acknowledge", "verdict_policy"}


def _tree() -> ast.Module:
    path = Path(frontdoor.__file__)
    return ast.parse(path.read_text())


def _resolve(name: str):
    fn = getattr(frontdoor, name, None)
    if fn is not None:
        return fn
    for mod in _SEARCH_MODULES:
        try:
            module = importlib.import_module(f"uxarray_mcp.tools.{mod}")
        except ImportError:
            continue
        if hasattr(module, name):
            return getattr(module, name)
    return None


def _passed_names(call: ast.Call) -> set[str]:
    """Names the call hands on, whether by keyword, positionally, or via _require."""
    passed = {kw.arg for kw in call.keywords if kw.arg}
    for arg in call.args:
        if isinstance(arg, ast.Name):
            passed.add(arg.id)
        elif (
            isinstance(arg, ast.Call)
            and getattr(arg.func, "id", "") == "_require"
            and arg.args
            and isinstance(arg.args[0], ast.Name)
        ):
            passed.add(arg.args[0].id)
    return passed


def _dispatch_branches(func_name: str, dispatch_var: str):
    node = next(
        n
        for n in _tree().body
        if isinstance(n, ast.FunctionDef) and n.name == func_name
    )
    accepted = {a.arg for a in node.args.args + node.args.kwonlyargs} - _FRONT_DOOR_ONLY
    for branch in ast.walk(node):
        if not isinstance(branch, ast.If):
            continue
        test = branch.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == dispatch_var
            and test.comparators
            and isinstance(test.comparators[0], ast.Constant)
        ):
            continue
        operation = test.comparators[0].value
        for sub in ast.walk(branch):
            if not isinstance(sub, ast.Return) or not isinstance(sub.value, ast.Call):
                continue
            call = sub.value
            target = (
                call.func.id
                if isinstance(call.func, ast.Name)
                else getattr(call.func, "attr", "")
            )
            yield operation, target, accepted, _passed_names(call)


@pytest.mark.parametrize(
    ("entry_point", "dispatch_var", "min_branches"),
    [("run_analysis", "op", 20), ("plot_dataset", "kind", 4)],
)
def test_no_front_door_parameter_is_silently_dropped(
    entry_point, dispatch_var, min_branches
):
    examined = 0
    dropped: list[str] = []
    for operation, target, accepted, passed in _dispatch_branches(
        entry_point, dispatch_var
    ):
        examined += 1
        func = _resolve(target)
        assert func is not None, f"{entry_point}/{operation} calls unknown {target!r}"
        takes = set(inspect.signature(func).parameters)
        missing = sorted((accepted & takes) - passed - {"self"})
        if missing:
            dropped.append(f"{operation} -> {target}() drops {missing}")

    # A parsing regression that found zero branches would pass vacuously.
    assert examined >= min_branches, (
        f"only {examined} dispatch branches found in {entry_point}; "
        "the AST walk is probably no longer matching the dispatch shape"
    )
    assert not dropped, (
        "front door accepts parameters it never forwards:\n" + "\n".join(dropped)
    )
