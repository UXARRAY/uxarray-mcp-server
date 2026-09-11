"""Move files between this machine and an HPC collection, as MCP tools.

Three verbs rather than one ``transfer(op=...)`` dispatcher: a model picks
better from three schemas that each name their own arguments than from one
that takes an operation string and a bag of maybe-required fields, and an
upload and a download are not the same authorization decision.

They are registered only when some endpoint actually carries a
``globus_transfer`` block. An install that moves no files shows no sign of
these -- an unconfigured tool that exists only to explain that it is
unconfigured is a tool the model can still call, and calling it is the wrong
thing to have learned.

Nothing here submits without checking paths first: the service refuses out of
root before it fetches a submission id, so a rejected request costs no network
and leaves no half-made task on the Globus side.
"""

from __future__ import annotations

from typing import Any, Dict

from uxarray_mcp.provenance import attach_provenance
from uxarray_mcp.remote.transfer import (
    TransferError,
    TransferService,
)
from uxarray_mcp.state import OperationTracker

__all__ = [
    "transfer_get",
    "transfer_ls",
    "transfer_put",
    "transfer_status",
    "transfers_are_configured",
]


def _config():
    from uxarray_mcp.tools.execution_control import _load_config_for_tools

    return _load_config_for_tools()


def transfers_are_configured() -> bool:
    """Whether any configured endpoint declares where its files live.

    Read at registry build time to decide whether the transfer tools exist at
    all, so it answers ``False`` for every failure -- an unreadable or absent
    config is not a reason to raise on startup for a feature the user has not
    asked for.
    """
    try:
        config, _ = _config()
    except Exception:
        return False
    return any(
        getattr(profile, "globus_transfer", None) is not None
        for profile in getattr(config, "endpoints", {}).values()
    )


def _service_for(endpoint: str | None) -> tuple[TransferService, str]:
    """Resolve an endpoint to a service, or say what the config is missing."""
    config, _ = _config()
    profile = config.resolve_endpoint(endpoint=endpoint)
    if profile is None:
        configured = ", ".join(config.endpoint_names) or "none"
        raise TransferError(
            f"No endpoint resolved for transfers. Configured endpoints: "
            f"{configured}. Pass endpoint='name'."
        )
    transfer_profile = getattr(profile, "globus_transfer", None)
    if transfer_profile is None:
        raise TransferError(
            f"Endpoint {profile.name!r} has no globus_transfer block in "
            f"config.yaml, so it moves no files. Add remote_collection_id and "
            f"remote_write_root to enable transfers for it."
        )
    return TransferService(transfer_profile), profile.name


def _failure(
    tool: str, inputs: Dict[str, Any], tracker: OperationTracker, exc: Exception
) -> Dict[str, Any]:
    """Report a refusal as a result, not a traceback.

    A path that failed containment is an answer -- the caller asked to move a
    file somewhere it may not go -- so it comes back shaped like every other
    result, with the reason in it.
    """
    result = attach_provenance(
        {
            "submitted": False,
            "reason": type(exc).__name__,
            "message": str(exc),
        },
        tool=tool,
        inputs=inputs,
        venue="local",
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    tracker.fail(str(exc))
    return result


def transfer_ls(
    remote_path: str = "/",
    endpoint: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    """List a directory on the HPC collection.

    ``remote_path`` is interpreted under the endpoint's read root, so a
    relative path stays inside the configured tree and an absolute one outside
    it is refused rather than listed.

    Parameters
    ----------
    remote_path : str
        Directory to list, relative to the endpoint's read root or absolute
        within it.
    endpoint : str | None
        Configured endpoint name. Defaults to the resolved default endpoint.
    session_id : str | None
        Session to track this operation under.
    """
    tracker = OperationTracker("transfer_ls", session_id=session_id)
    inputs = {
        "remote_path": remote_path,
        "endpoint": endpoint,
        "session_id": session_id,
    }
    try:
        service, name = _service_for(endpoint)
        tracker.stage("listing", f"Listing {remote_path!r} on {name}.")
        entries = service.ls(remote_path)
    except Exception as exc:
        return _failure("transfer_ls", inputs, tracker, exc)
    result = attach_provenance(
        {
            "endpoint": name,
            "remote_path": remote_path,
            "entry_count": len(entries),
            "entries": entries,
        },
        tool="transfer_ls",
        inputs=inputs,
        venue="globus_transfer",
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    tracker.succeed(f"Listed {len(entries)} entries.")
    return result


def transfer_put(
    local_path: str,
    remote_path: str,
    endpoint: str | None = None,
    label: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    """Upload a local file or directory to the HPC collection.

    The destination must resolve inside the endpoint's ``remote_write_root``;
    a read root does not widen where an upload may land. Directories transfer
    recursively. The call returns as soon as Globus accepts the task -- poll
    ``transfer_status`` with the returned ``task_id`` for completion.

    Parameters
    ----------
    local_path : str
        File or directory on this machine.
    remote_path : str
        Destination under the endpoint's write root.
    endpoint : str | None
        Configured endpoint name.
    label : str | None
        Label shown in the Globus web app for this task.
    session_id : str | None
        Session to track this operation under.
    """
    tracker = OperationTracker("transfer_put", session_id=session_id)
    inputs = {
        "local_path": local_path,
        "remote_path": remote_path,
        "endpoint": endpoint,
        "label": label,
        "session_id": session_id,
    }
    try:
        service, name = _service_for(endpoint)
        plan = service.plan_put(local_path, remote_path, label=label)
        tracker.stage("submitted", f"Uploading to {plan.destination_path} on {name}.")
        submitted = service.submit(plan)
    except Exception as exc:
        return _failure("transfer_put", inputs, tracker, exc)
    result = attach_provenance(
        {"submitted": True, "endpoint": name, "direction": "upload", **submitted},
        tool="transfer_put",
        inputs=inputs,
        venue="globus_transfer",
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    tracker.succeed(f"Submitted upload task {submitted.get('task_id')}.")
    return result


def transfer_get(
    remote_path: str,
    local_path: str,
    recursive: bool = False,
    endpoint: str | None = None,
    label: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    """Download a file or directory from the HPC collection.

    The source is read under the endpoint's read root, which falls back to the
    write root when unset -- never to the whole remote filesystem. A
    ``local_root`` in the endpoint's config, if set, bounds where the download
    may land on this machine, checked after symlinks are resolved.

    Parameters
    ----------
    remote_path : str
        Source under the endpoint's read root.
    local_path : str
        Destination on this machine.
    recursive : bool
        Set for a directory. A remote directory cannot be detected from here
        without a listing, so this is explicit rather than guessed.
    endpoint : str | None
        Configured endpoint name.
    label : str | None
        Label shown in the Globus web app for this task.
    session_id : str | None
        Session to track this operation under.
    """
    tracker = OperationTracker("transfer_get", session_id=session_id)
    inputs = {
        "remote_path": remote_path,
        "local_path": local_path,
        "recursive": recursive,
        "endpoint": endpoint,
        "label": label,
        "session_id": session_id,
    }
    try:
        service, name = _service_for(endpoint)
        plan = service.plan_get(
            remote_path, local_path, recursive=recursive, label=label
        )
        tracker.stage("submitted", f"Downloading {plan.source_path} from {name}.")
        submitted = service.submit(plan)
    except Exception as exc:
        return _failure("transfer_get", inputs, tracker, exc)
    result = attach_provenance(
        {"submitted": True, "endpoint": name, "direction": "download", **submitted},
        tool="transfer_get",
        inputs=inputs,
        venue="globus_transfer",
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    tracker.succeed(f"Submitted download task {submitted.get('task_id')}.")
    return result


def transfer_status(
    task_id: str,
    endpoint: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    """Report what a submitted transfer task has done so far.

    ``transfer_put`` and ``transfer_get`` return as soon as Globus accepts the
    task, so without this the returned ``task_id`` names something nothing can
    read back.

    Parameters
    ----------
    task_id : str
        Task id returned by ``transfer_put`` or ``transfer_get``.
    endpoint : str | None
        Configured endpoint name whose credentials own the task.
    session_id : str | None
        Session to track this operation under.
    """
    tracker = OperationTracker("transfer_status", session_id=session_id)
    inputs = {"task_id": task_id, "endpoint": endpoint, "session_id": session_id}
    try:
        service, name = _service_for(endpoint)
        tracker.stage("polling", f"Reading task {task_id} on {name}.")
        status = service.status(task_id)
    except Exception as exc:
        return _failure("transfer_status", inputs, tracker, exc)
    result = attach_provenance(
        {"endpoint": name, **status},
        tool="transfer_status",
        inputs=inputs,
        venue="globus_transfer",
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    tracker.succeed(f"Task {task_id} is {status.get('status')}.")
    return result
