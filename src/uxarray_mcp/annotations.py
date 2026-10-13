"""MCP tool annotations: what a client may auto-approve, and what it may not.

``ToolAnnotations`` carries four hints -- ``readOnlyHint``,
``destructiveHint``, ``idempotentHint``, ``openWorldHint`` -- that a client
uses to decide whether to run a tool without asking. We published none, so
every tool looked alike: a client had no way to tell ``get_capabilities``,
which opens a file and reports what is in it, from ``transfer_put``, which
copies data to another machine.

Three rules govern what is written here, because a wrong hint is worse than
no hint. A tool marked read-only that writes will be auto-approved, and the
user will never see the prompt that would have caught it.

1. **Read-only means no side effect anywhere.** Not "does not write the file
   it was given". Operations that persist a result artifact under the state
   directory are not read-only, however read-only they look from the caller's
   side.
2. **Silence beats a guess.** A tool absent from this map gets no annotation
   at all, which is what every tool had before. Clients treat the absence as
   "unknown", which is the honest answer for anything not deliberately
   classified.
3. **Destructive means it can overwrite or move data the user cares about**,
   not merely that it writes something. Rendering a figure into the artifact
   store is a write; uploading over a path on a cluster is destructive.

The hints are advisory by specification -- a client may ignore them -- so
nothing here is a security control. The actual enforcement for remote paths
lives in the precondition layer and in the endpoint's own read/write roots.
"""

from __future__ import annotations

from typing import Any

#: Tools that read and compute but leave nothing behind.
#:
#: Being on this list is a claim that the tool writes no file, mutates no
#: session, and submits no remote work. ``idempotentHint`` is implied by
#: read-only and is not repeated.
_READ_ONLY: frozenset[str] = frozenset(
    {
        # Capability and schema queries: pure introspection of this server.
        "get_capabilities",
        "discover_tools",
        "contract-describe_response_contract",
        "contract-validate_response",
        # Inspecting data already on disk.
        "inspect-inspect_mesh",
        "inspect-inspect_variable",
        "inspect-validate_dataset",
        "io-list_datasets",
        # Reading back state that some earlier call created. These observe a
        # store rather than change it.
        "get_result",
        "get_status",
        "session-get_operation_status",
        "session-get_result_handle",
        "session-get_session_state",
        "session-get_workflow_status",
        "session-list_operations",
        # Diagnostics. They probe a configuration and report; the remote
        # probes submit nothing and run no user code.
        "diagnose_endpoint",
        "probe_path_access",
        "hpc-endpoint_status",
        "hpc-get_execution_mode",
        "hpc-validate_hpc_setup",
        # Listing a remote directory reads the collection; it moves nothing.
        "transfer-transfer_ls",
        "transfer-transfer_status",
    }
)

#: Tools that can overwrite or relocate data outside this server's own
#: scratch space. These are the ones a client should confirm.
_DESTRUCTIVE: frozenset[str] = frozenset(
    {
        # Both directions of a transfer land a file at a path the user named,
        # on a machine that is not necessarily this one. Globus overwrites a
        # colliding destination without asking.
        "transfer-transfer_put",
        "transfer-transfer_get",
        # Exports write to a caller-supplied path rather than the artifact
        # store, so they can land on top of something that matters.
        "io-export_to_csv",
        "io-export_to_netcdf",
        "io-write_result",
    }
)

#: Tools that reach beyond this machine: a cluster, a Globus collection, a
#: data archive. ``openWorldHint`` tells a client the result depends on
#: systems it cannot see, so a failure is not necessarily a bug in the call.
_OPEN_WORLD: frozenset[str] = frozenset(
    {
        "transfer-transfer_put",
        "transfer-transfer_get",
        "transfer-transfer_ls",
        "transfer-transfer_status",
        "diagnose_endpoint",
        "probe_path_access",
        "hpc-endpoint_status",
        "hpc-validate_hpc_setup",
        "hpc-check_remote_yac",
        "agent-run_scientific_agent",
    }
)


def annotations_for(tool_name: str) -> dict[str, bool] | None:
    """Return the annotation hints for ``tool_name``, or ``None``.

    ``None`` -- rather than an empty dict -- for anything unclassified, so the
    caller omits the field entirely instead of publishing a ``ToolAnnotations``
    that asserts nothing. The two are different on the wire: an empty object
    reads as "classified, no hints apply".
    """
    read_only = tool_name in _READ_ONLY
    destructive = tool_name in _DESTRUCTIVE
    open_world = tool_name in _OPEN_WORLD

    if not (read_only or destructive or open_world):
        return None

    hints: dict[str, bool] = {}
    if read_only:
        # Read-only implies non-destructive and idempotent. Saying so
        # explicitly means a client does not have to infer it, and the
        # specification's default for destructiveHint is True.
        hints["readOnlyHint"] = True
        hints["destructiveHint"] = False
        hints["idempotentHint"] = True
    elif destructive:
        hints["readOnlyHint"] = False
        hints["destructiveHint"] = True
    if open_world:
        hints["openWorldHint"] = True
    return hints


def apply_tool_annotations(server: Any) -> Any:
    """Wrap a server's ``tools/list`` so its results carry annotations.

    Upstream's ``make_mcp_tool`` builds every ``Tool`` and takes no
    annotations argument, so there is no seam to pass them through at
    construction: the handler is a closure created inside
    ``toolregistry_server``. Wrapping the registered handler is the one place
    both server construction paths converge, and it degrades to a no-op on an
    SDK whose ``Tool`` has no ``annotations`` field.

    Returns the server so callers can wrap a constructor call in place.
    """
    handlers = getattr(server, "_request_handlers", None) or getattr(
        server, "request_handlers", None
    )
    if not isinstance(handlers, dict):  # pragma: no cover - defensive
        return server

    entry = handlers.get("tools/list")
    if entry is None:  # pragma: no cover - defensive
        return server

    # mcp 2.x stores a ``HandlerEntry(handler, params_type)`` rather than a
    # bare callable, and the dispatcher reads ``.params_type`` off it before
    # calling. Replacing the entry with a plain function makes every
    # ``tools/list`` fail with ``'function' object has no attribute
    # 'params_type'``, so the wrapper has to be rebuilt as the same kind of
    # object. mcp 1.x stores the callable directly; both are handled.
    original: Any = getattr(entry, "handler", entry)

    try:
        from mcp.types import Tool, ToolAnnotations
    except ImportError:  # pragma: no cover - MCP SDK is a hard dep of serving
        return server

    if "annotations" not in getattr(Tool, "model_fields", {}):  # pragma: no cover
        return server

    async def on_list_tools(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        for tool in getattr(result, "tools", []):
            if getattr(tool, "annotations", None) is not None:
                continue
            hints = annotations_for(tool.name)
            if hints:
                tool.annotations = ToolAnnotations(**hints)
        return result

    if hasattr(entry, "handler"):
        handlers["tools/list"] = type(entry)(
            handler=on_list_tools, params_type=entry.params_type
        )
    else:
        handlers["tools/list"] = on_list_tools
    return server
