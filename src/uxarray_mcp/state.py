"""Persistent state, workflow, and result storage for UXarray MCP tools."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import xarray as xr


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


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    with suppress(Exception):
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True))


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


def summarize_grid(grid: Any) -> dict[str, Any]:
    return {
        "format": str(getattr(grid, "source_grid_spec", "Unknown")),
        "n_face": int(getattr(grid, "n_face", 0)),
        "n_node": int(getattr(grid, "n_node", 0)),
        "n_edge": int(getattr(grid, "n_edge", 0)),
    }


def summarize_array(data: xr.DataArray) -> dict[str, Any]:
    values = data.values
    summary: dict[str, Any] = {
        "dims": list(data.dims),
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "name": str(data.name) if data.name is not None else None,
    }
    if values.size > 0:
        with suppress(Exception):
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
) -> dict[str, Any]:
    operation_id = _new_id("op")
    record = {
        "operation_id": operation_id,
        "tool_name": tool_name,
        "session_id": session_id,
        "workflow_id": workflow_id,
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
    grid.to_xarray().to_netcdf(path)
    return str(path)


def write_dataarray_artifact(data: Any, result_id: str) -> str:
    path = _result_path(result_id, ".nc")
    _sanitize_netcdf_attrs(data).to_netcdf(path)
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
    sanitized.to_netcdf(path)
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
    operation_id: str = field(init=False)

    def __post_init__(self) -> None:
        record = create_operation(
            tool_name=self.tool_name,
            session_id=self.session_id,
            workflow_id=self.workflow_id,
        )
        self.operation_id = record["operation_id"]

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
