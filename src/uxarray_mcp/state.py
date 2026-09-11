"""Persistent state, workflow, and result storage for UXarray MCP tools."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from uxarray_mcp.json_safe import json_safe

_WRITE_LOCK = threading.RLock()


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_root() -> Path:
    configured = os.getenv("UXARRAY_MCP_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".uxarray_mcp_server"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# Kept as a module-local name because it is used throughout this file, but
# there is only one implementation: the same pass that runs on the wire also
# runs on what we persist, so a stored result and a returned one cannot
# disagree about how a NaN is written.
_json_safe = json_safe


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(
        _json_safe(payload), indent=2, sort_keys=True, allow_nan=False
    )
    with _WRITE_LOCK:
        _atomic_write(path, lambda temporary: temporary.write_text(serialized))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _record_path(kind: str, record_id: str) -> Path:
    return _ensure_dir(_state_root() / kind) / f"{record_id}.json"


def _artifacts_dir() -> Path:
    return _ensure_dir(_state_root() / "artifacts")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _result_path(result_id: str, suffix: str) -> Path:
    return _artifacts_dir() / f"{result_id}{suffix}"


def _atomic_write(path: Path, writer: Any) -> None:
    """Write through a sibling temporary file and atomically replace ``path``."""
    _ensure_dir(path.parent)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        writer(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sanitize_netcdf_attr_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (str, int, float)):
        return value
    if value is None:
        return ""
    return str(value)


def _sanitize_netcdf_attrs(data: Any) -> Any:
    cleaned = data.copy(deep=False)
    cleaned.attrs = {
        str(key): _sanitize_netcdf_attr_value(value)
        for key, value in getattr(data, "attrs", {}).items()
    }
    return cleaned


#: Connectivity names a UGRID ``grid_topology`` variable may point at. Kept
#: here rather than imported so the sanitizer does not depend on a private
#: uxarray module path.
_UGRID_CONNECTIVITY_NAMES = (
    "face_node_connectivity",
    "face_edge_connectivity",
    "face_face_connectivity",
    "edge_node_connectivity",
    "edge_face_connectivity",
    "node_edge_connectivity",
    "node_face_connectivity",
)


def _widen_narrow_fill_values(ds: xr.Dataset) -> xr.Dataset:
    """Widen integer arrays whose ``_FillValue`` does not fit their dtype.

    uxarray's ICON reader keeps the file's native int32 connectivity while
    attaching the UGRID attribute template, whose ``_FillValue`` is the int64
    sentinel ``np.iinfo(np.intp).min``. netCDF4 rejects that pairing at
    ``createVariable`` with ``OverflowError: Python integer
    -9223372036854775808 out of bounds for int32``, so an ICON grid cannot be
    written at all. The sentinel is the convention and the data is the thing
    that is too narrow, so widen the data rather than rewrite the attribute.
    """
    for name, var in ds.variables.items():
        fill = var.attrs.get("_FillValue")
        if fill is None or not np.issubdtype(var.dtype, np.integer):
            continue
        info = np.iinfo(var.dtype)
        if info.min <= int(fill) <= info.max:
            continue
        ds[name] = var.astype(np.int64)
        ds[name].attrs = dict(var.attrs)
    return ds


def _drop_phantom_topology_attrs(ds: xr.Dataset) -> xr.Dataset:
    """Strip ``grid_topology`` attributes that name something not in the file.

    uxarray's ``_encode_ugrid`` aliases its module-level attribute template
    instead of copying it, then mutates it per grid. So the first grid a
    process exports leaves its own connectivity names on the template, and
    every later grid inherits them whether or not it has those variables.
    Reading such a file back raises ``ValueError: cannot rename
    'face_edge_connectivity' because it is not a variable or dimension in this
    dataset`` -- ordering-dependent, and silent until someone reopens it.
    """
    topology = ds.variables.get("grid_topology")
    if topology is None:
        return ds
    present = set(ds.variables)
    kept = {}
    for key, value in topology.attrs.items():
        # `topology_dimension` is an integer rank, not the name of anything --
        # only string-valued attributes name variables or dimensions.
        if not isinstance(value, str):
            kept[key] = value
            continue
        if key in _UGRID_CONNECTIVITY_NAMES and value not in present:
            continue
        if key.endswith("_coordinates") and not set(value.split()) <= present:
            continue
        if key.endswith("_dimension") and value not in ds.dims:
            continue
        kept[key] = value
    ds["grid_topology"].attrs = kept
    return ds


def summarize_grid(grid: Any) -> dict[str, Any]:
    return {
        "format": str(getattr(grid, "source_grid_spec", "Unknown")),
        "n_face": int(getattr(grid, "n_face", 0)),
        "n_node": int(getattr(grid, "n_node", 0)),
        "n_edge": int(getattr(grid, "n_edge", 0)),
    }


def summarize_array(data: xr.DataArray) -> dict[str, Any]:
    """Shape, dtype and statistics over the values that are actually there.

    The statistics skip non-finite entries, and say so when they had to. The
    plain reductions this used to call propagate NaN, so a single missing
    value made ``min``, ``max`` and ``mean`` all NaN -- measured on a temporal
    mean whose field was masked over half its faces, where three faces held
    finite means and the summary reported none of them. Land masks are
    ordinary in this data, so that was most fields.

    ``NaN`` was also going out on the wire. ``json.dumps`` writes it as the
    bare token ``NaN``, which is not JSON, and a client parsing strictly
    rejects the payload rather than the number. Nothing finite reports
    ``None`` instead.

    ``n_finite``/``n_total`` appear only when they differ. A count that is
    always equal to the size costs payload on every call and tells the caller
    nothing they could not read off ``shape``.
    """
    values = np.asarray(data.values)
    summary: dict[str, Any] = {
        "dims": list(data.dims),
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "name": str(data.name) if data.name is not None else None,
    }
    if values.size == 0:
        return summary

    with suppress(Exception):
        if np.issubdtype(values.dtype, np.inexact):
            finite = np.isfinite(values)
            n_finite = int(finite.sum())
            if n_finite != values.size:
                summary["n_finite"] = n_finite
                summary["n_total"] = int(values.size)
            usable = values[finite]
            summary["min"] = float(usable.min()) if n_finite else None
            summary["max"] = float(usable.max()) if n_finite else None
            summary["mean"] = float(usable.mean()) if n_finite else None
        else:
            # Integers and booleans carry no missing value to skip, and
            # datetimes raise on float() -- which the suppression handles the
            # same way it did before.
            summary["min"] = float(values.min())
            summary["max"] = float(values.max())
            summary["mean"] = float(values.mean())
    return summary


def summarize_dataset(dataset: xr.Dataset) -> dict[str, Any]:
    return {
        "variables": list(dataset.data_vars),
        "dims": {k: int(v) for k, v in dataset.sizes.items()},
    }


def create_session(name: str | None = None) -> dict[str, Any]:
    session_id = _new_id("session")
    record: dict[str, Any] = {
        "session_id": session_id,
        "name": name,
        "created_at": _now_utc(),
        "updated_at": _now_utc(),
        "datasets": {},
        "results": {},
        "workflow_ids": [],
        "operation_ids": [],
        "last_result_handle": None,
    }
    _write_json(_record_path("sessions", session_id), record)
    return record


def get_session(session_id: str) -> dict[str, Any]:
    path = _record_path("sessions", session_id)
    if not path.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")
    return _read_json(path)


def save_session(session: dict[str, Any]) -> dict[str, Any]:
    session["updated_at"] = _now_utc()
    _write_json(_record_path("sessions", session["session_id"]), session)
    return session


def register_dataset(
    session_id: str,
    *,
    grid_path: str,
    data_path: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    session = get_session(session_id)
    dataset_handle = _new_id("dataset")
    dataset_record = {
        "dataset_handle": dataset_handle,
        "name": name or Path(data_path or grid_path).stem,
        "grid_path": grid_path,
        "data_path": data_path,
        "registered_at": _now_utc(),
    }
    session["datasets"][dataset_handle] = dataset_record
    save_session(session)
    return dataset_record


def create_operation(
    *,
    tool_name: str,
    session_id: str | None = None,
    workflow_id: str | None = None,
    endpoint_id: str | None = None,
    task_id: str | None = None,
    submitted_at: str | None = None,
) -> dict[str, Any]:
    operation_id = _new_id("op")
    record = {
        "operation_id": operation_id,
        "tool_name": tool_name,
        "session_id": session_id,
        "workflow_id": workflow_id,
        # Written as None up front and filled in at submit. A record that
        # never reaches an endpoint keeps them None, which is the honest
        # answer; records written before these keys existed simply lack
        # them, so every reader goes through .get().
        "endpoint_id": endpoint_id,
        "task_id": task_id,
        "submitted_at": submitted_at,
        "status": "running",
        "stage": "started",
        "created_at": _now_utc(),
        "updated_at": _now_utc(),
        "events": [
            {
                "timestamp_utc": _now_utc(),
                "stage": "started",
                "message": f"{tool_name} started",
            }
        ],
    }
    _write_json(_record_path("operations", operation_id), record)
    if session_id:
        session = get_session(session_id)
        session["operation_ids"].append(operation_id)
        save_session(session)
    return record


def get_operation(operation_id: str) -> dict[str, Any]:
    path = _record_path("operations", operation_id)
    if not path.exists():
        raise FileNotFoundError(f"Operation not found: {operation_id}")
    return _read_json(path)


def save_operation(operation: dict[str, Any]) -> dict[str, Any]:
    operation["updated_at"] = _now_utc()
    _write_json(_record_path("operations", operation["operation_id"]), operation)
    return operation


def append_operation_event(
    operation_id: str,
    *,
    stage: str,
    message: str,
    status: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operation = get_operation(operation_id)
    operation["stage"] = stage
    if status is not None:
        operation["status"] = status
    event: dict[str, Any] = {
        "timestamp_utc": _now_utc(),
        "stage": stage,
        "message": message,
    }
    if details:
        event["details"] = details
    operation["events"].append(event)
    return save_operation(operation)


def record_task_handle(
    operation_id: str,
    *,
    task_id: str | None,
    endpoint_id: str | None = None,
) -> dict[str, Any]:
    """Persist the Globus Compute handle for work that is now in flight.

    Until this exists a process that dies while waiting on a remote task
    leaves nothing behind that could find that task again: the job keeps
    running on the cluster and the only record of it was in the memory that
    just went away.
    """
    operation = get_operation(operation_id)
    operation["task_id"] = task_id
    if endpoint_id is not None:
        operation["endpoint_id"] = endpoint_id
    operation["submitted_at"] = _now_utc()
    operation["events"].append(
        {
            "timestamp_utc": operation["submitted_at"],
            "stage": operation.get("stage", "submitted"),
            "message": f"Remote task {task_id or 'unknown'} accepted.",
        }
    )
    return save_operation(operation)


def finalize_operation(
    operation_id: str, *, status: str, summary: str | None = None
) -> dict[str, Any]:
    operation = get_operation(operation_id)
    operation["status"] = status
    operation["stage"] = status
    if summary:
        operation["summary"] = summary
        operation["events"].append(
            {
                "timestamp_utc": _now_utc(),
                "stage": status,
                "message": summary,
            }
        )
    return save_operation(operation)


def list_operations(session_id: str | None = None) -> list[dict[str, Any]]:
    operations_dir = _ensure_dir(_state_root() / "operations")
    operations = [_read_json(path) for path in operations_dir.glob("*.json")]
    operations.sort(key=lambda item: item.get("created_at", ""))
    if session_id is None:
        return operations
    return [op for op in operations if op.get("session_id") == session_id]


def persist_result(
    *,
    kind: str,
    name: str,
    summary: dict[str, Any],
    session_id: str | None = None,
    artifact_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result_handle = _new_id("result")
    record = {
        "result_handle": result_handle,
        "kind": kind,
        "name": name,
        "summary": summary,
        "artifact_path": artifact_path,
        "metadata": metadata or {},
        "created_at": _now_utc(),
        "session_id": session_id,
    }
    _write_json(_record_path("results", result_handle), record)
    if session_id:
        session = get_session(session_id)
        session["results"][result_handle] = {
            "kind": kind,
            "name": name,
            "created_at": record["created_at"],
        }
        session["last_result_handle"] = result_handle
        save_session(session)
    return record


def get_result(result_handle: str) -> dict[str, Any]:
    path = _record_path("results", result_handle)
    if not path.exists():
        raise FileNotFoundError(f"Result not found: {result_handle}")
    return _read_json(path)


def save_result(result: dict[str, Any]) -> dict[str, Any]:
    _write_json(_record_path("results", result["result_handle"]), result)
    return result


def write_grid_artifact(grid: Any, result_id: str) -> str:
    path = _result_path(result_id, ".nc")
    # Two upstream defects make a bare `grid.to_xarray().to_netcdf(...)`
    # unreliable: an int32 grid cannot be written at all, and a grid exported
    # after a richer one is written with attributes it does not have and
    # cannot be read back. Both are repaired here, on the dataset, not on the
    # grid -- see tests/test_upstream_roundtrip.py for the reproducers.
    encoded = _drop_phantom_topology_attrs(_widen_narrow_fill_values(grid.to_xarray()))
    with _WRITE_LOCK:
        _atomic_write(path, lambda temporary: encoded.to_netcdf(temporary))
    return str(path)


def write_dataarray_artifact(data: Any, result_id: str) -> str:
    path = _result_path(result_id, ".nc")
    with _WRITE_LOCK:
        _atomic_write(
            path, lambda temporary: _sanitize_netcdf_attrs(data).to_netcdf(temporary)
        )
    return str(path)


def write_dataset_artifact(data: Any, result_id: str) -> str:
    path = _result_path(result_id, ".nc")
    sanitized = _sanitize_netcdf_attrs(data)
    sanitized = sanitized.assign_attrs(
        {
            str(key): _sanitize_netcdf_attr_value(value)
            for key, value in getattr(sanitized, "attrs", {}).items()
        }
    )
    for name in getattr(sanitized, "data_vars", {}):
        sanitized[name].attrs = {
            str(key): _sanitize_netcdf_attr_value(value)
            for key, value in sanitized[name].attrs.items()
        }
    with _WRITE_LOCK:
        _atomic_write(path, lambda temporary: sanitized.to_netcdf(temporary))
    return str(path)


def write_json_artifact(payload: dict[str, Any], result_id: str) -> str:
    path = _result_path(result_id, ".json")
    _write_json(path, payload)
    return str(path)


def copy_artifact(src: str, dest: str) -> str:
    destination = Path(dest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, destination)
    return str(destination)


def create_workflow(
    *,
    template: str,
    inputs: dict[str, Any],
    session_id: str | None = None,
    steps: list[str],
) -> dict[str, Any]:
    workflow_id = _new_id("workflow")
    record = {
        "workflow_id": workflow_id,
        "template": template,
        "session_id": session_id,
        "inputs": _json_safe(inputs),
        "status": "pending",
        "created_at": _now_utc(),
        "updated_at": _now_utc(),
        "events": [],
        "steps": [
            {"name": name, "status": "pending", "summary": None, "error": None}
            for name in steps
        ],
        "result_handle": None,
    }
    _write_json(_record_path("workflows", workflow_id), record)
    if session_id:
        session = get_session(session_id)
        session["workflow_ids"].append(workflow_id)
        save_session(session)
    return record


def get_workflow(workflow_id: str) -> dict[str, Any]:
    path = _record_path("workflows", workflow_id)
    if not path.exists():
        raise FileNotFoundError(f"Workflow not found: {workflow_id}")
    return _read_json(path)


def save_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    workflow["updated_at"] = _now_utc()
    _write_json(_record_path("workflows", workflow["workflow_id"]), workflow)
    return workflow


def append_workflow_event(
    workflow_id: str, *, stage: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    event: dict[str, Any] = {
        "timestamp_utc": _now_utc(),
        "stage": stage,
        "message": message,
    }
    if details:
        event["details"] = details
    workflow["events"].append(event)
    return save_workflow(workflow)


def update_workflow_step(
    workflow_id: str,
    step_name: str,
    *,
    status: str,
    summary: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    workflow = get_workflow(workflow_id)
    for step in workflow["steps"]:
        if step["name"] == step_name:
            step["status"] = status
            step["summary"] = summary
            step["error"] = error
            break
    return save_workflow(workflow)


def reset_session(session_id: str, *, clear_artifacts: bool = False) -> dict[str, Any]:
    session = get_session(session_id)
    result_handles = list(session["results"])
    workflow_ids = list(session["workflow_ids"])
    operation_ids = list(session["operation_ids"])

    removed_artifacts: list[str] = []
    if clear_artifacts:
        for result_handle in result_handles:
            with suppress(FileNotFoundError):
                result = get_result(result_handle)
                artifact_path = result.get("artifact_path")
                if artifact_path and Path(artifact_path).exists():
                    Path(artifact_path).unlink()
                    removed_artifacts.append(artifact_path)

    for result_handle in result_handles:
        with suppress(FileNotFoundError):
            _record_path("results", result_handle).unlink()
    for workflow_id in workflow_ids:
        with suppress(FileNotFoundError):
            _record_path("workflows", workflow_id).unlink()
    for operation_id in operation_ids:
        with suppress(FileNotFoundError):
            _record_path("operations", operation_id).unlink()

    session["results"] = {}
    session["workflow_ids"] = []
    session["operation_ids"] = []
    session["last_result_handle"] = None
    save_session(session)

    return {
        "session_id": session_id,
        "cleared_results": result_handles,
        "cleared_workflows": workflow_ids,
        "cleared_operations": operation_ids,
        "removed_artifacts": removed_artifacts,
    }


@dataclass
class OperationTracker:
    """Simple persistent operation tracker for long-running tools."""

    tool_name: str
    session_id: str | None = None
    workflow_id: str | None = None
    endpoint_id: str | None = None
    task_id: str | None = field(init=False, default=None)
    operation_id: str = field(init=False)

    def __post_init__(self) -> None:
        record = create_operation(
            tool_name=self.tool_name,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
            endpoint_id=self.endpoint_id,
        )
        self.operation_id = record["operation_id"]

    def record_submission(
        self, task_id: str | None, endpoint_id: str | None = None
    ) -> None:
        """Store the handle for a task the endpoint has acknowledged."""
        self.task_id = task_id
        if endpoint_id is not None:
            self.endpoint_id = endpoint_id
        record_task_handle(
            self.operation_id, task_id=task_id, endpoint_id=self.endpoint_id
        )

    def stage(
        self, stage: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        append_operation_event(
            self.operation_id,
            stage=stage,
            message=message,
            status="running",
            details=details,
        )

    def succeed(self, summary: str) -> None:
        finalize_operation(self.operation_id, status="completed", summary=summary)

    def fail(self, summary: str) -> None:
        finalize_operation(self.operation_id, status="failed", summary=summary)


#: The operation the current call is being tracked under, if any.
#:
#: The tracker is created in ``tools/remote_tools.py`` but the task id only
#: exists deep inside ``remote/agent.py``, past a dozen tool-specific agent
#: methods. Threading an extra argument through all of them to carry one
#: string would put the plumbing in every signature; a context variable
#: keeps it out of the API and, unlike an attribute on the shared agent,
#: does not mix up two tools submitting at once.
CURRENT_OPERATION: ContextVar[OperationTracker | None] = ContextVar(
    "uxarray_mcp_current_operation", default=None
)
