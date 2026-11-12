"""Build the ``ToolRegistry`` the server exposes: one flat list of tools."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from toolregistry import ToolRegistry, ToolTag

from uxarray_mcp.server import tools as _tools
from uxarray_mcp.server.contract import json_safe

#: Every public tool, in the order clients see them.
TOOL_NAMES: tuple[str, ...] = (
    "list_datasets",
    "inspect_dataset",
    "compute",
    "vector_calc",
    "compare",
    "remap",
    "subset",
    "plot",
    "export",
    "session",
    "endpoint",
    "get_operation",
)

#: Tools that change something on disk or in session state.
_WRITES: frozenset[str] = frozenset({"export", "session", "endpoint"})
#: Tools that may run for minutes.
_SLOW: frozenset[str] = frozenset(
    {"compute", "vector_calc", "remap", "plot", "compare"}
)

_WIRE_SAFE = "_uxarray_mcp_wire_safe"


def _wire_safe(func: Callable[..., Any]) -> Callable[..., Any]:
    """Every result is made JSON-representable before it leaves."""
    if getattr(func, _WIRE_SAFE, False):
        return func

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return json_safe(func(*args, **kwargs))

    setattr(wrapper, _WIRE_SAFE, True)
    return wrapper


def _trim_schema(tool: Any) -> None:
    """Drop ``toolcall_reason`` and Pydantic ``title`` noise from the served schema.

    ``RouteTable`` serves ``tool.parameters`` raw, so upstream's cleaning in
    ``get_schema()`` never reaches clients. The title strip recurses only
    into property *values*, so a real parameter named ``title`` survives.
    """
    params = getattr(tool, "parameters", None)
    if not isinstance(params, dict):
        return
    props = params.get("properties")
    if isinstance(props, dict):
        props.pop("toolcall_reason", None)
    required = params.get("required")
    if isinstance(required, list):
        params["required"] = [r for r in required if r != "toolcall_reason"]
    _drop_titles(params)
    _fix_unions(params)


def _drop_titles(schema: Any) -> None:
    if not isinstance(schema, dict):
        return
    schema.pop("title", None)
    props = schema.get("properties")
    if isinstance(props, dict):
        for spec in props.values():
            _drop_titles(spec)
    items = schema.get("items")
    if isinstance(items, dict):
        _drop_titles(items)


_UNION_FIXES: dict[str, dict[str, Any]] = {
    "lat_spec": {
        "anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"}}]
    },
}


def _fix_unions(schema: Any) -> None:
    """Upstream renders ``float | list`` with duplicated, untyped branches."""
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict):
        return
    for name, fix in _UNION_FIXES.items():
        spec = props.get(name)
        if isinstance(spec, dict):
            spec.pop("type", None)
            spec.pop("anyOf", None)
            spec.update(fix)


def _tags_for(name: str, func: Callable[..., Any]) -> set[ToolTag]:
    tags: set[ToolTag] = set()
    params = inspect.signature(func).parameters
    if "grid_path" in params or "data_path" in params or "path" in params:
        tags.add(ToolTag.FILE_SYSTEM)
    if "use_remote" in params or name == "endpoint":
        tags.add(ToolTag.NETWORK)
    if name in _SLOW:
        tags.add(ToolTag.SLOW)
    if name not in _WRITES:
        tags.add(ToolTag.READ_ONLY)
    return tags


def build_registry(name: str = "uxarray") -> ToolRegistry:
    """Register every tool in :data:`TOOL_NAMES`, tagged and trimmed."""
    registry = ToolRegistry(name=name)
    for tool_name in TOOL_NAMES:
        func = getattr(_tools, tool_name)
        registry.register(func)
        tool = registry.get_tool(tool_name)
        if tool is None:  # pragma: no cover - register() raised first
            raise RuntimeError(f"{tool_name} did not register")
        callable_ = getattr(tool, "callable", None)
        inner = getattr(callable_, "fn", None)
        if callable_ is not None and inner is not None:
            callable_.fn = _wire_safe(inner)
        if tool.metadata is not None:
            tool.metadata.tags.update(_tags_for(tool_name, func))
            registry.update_tool_metadata(
                tool_name,
                read_only_hint=tool_name not in _WRITES,
                destructive_hint=False,
                idempotent_hint=tool_name not in {"session", "export"},
                open_world_hint=tool_name == "endpoint",
            )
        _trim_schema(tool)
    return registry
