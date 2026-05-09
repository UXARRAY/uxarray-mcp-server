"""Session, workflow, and progress-aware tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uxarray_mcp.provenance import attach_provenance
from uxarray_mcp.state import (
    OperationTracker,
    append_workflow_event,
    create_workflow,
    get_operation,
    get_result,
    get_session,
    get_workflow,
    persist_result,
    save_result,
    save_workflow,
    update_workflow_step,
    write_json_artifact,
)
from uxarray_mcp.state import (
    create_session as create_session_record,
)
from uxarray_mcp.state import (
    list_operations as list_operation_records,
)
from uxarray_mcp.state import (
    register_dataset as register_dataset_record,
)
from uxarray_mcp.state import (
    reset_session as reset_session_record,
)


def create_session(name: str | None = None) -> dict[str, Any]:
    """Create a persistent scientific session for datasets and results."""
    session = create_session_record(name)
    return attach_provenance(
        {
            "session_id": session["session_id"],
            "name": session["name"],
            "created_at": session["created_at"],
        },
        tool="create_session",
        inputs={"name": name},
    )


def register_dataset(
    session_id: str,
    grid_path: str,
    data_path: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Register a grid/data pair in a persistent session."""
    if not Path(grid_path).exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")
    if data_path is not None and not Path(data_path).exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    dataset = register_dataset_record(
        session_id,
        grid_path=grid_path,
        data_path=data_path,
        name=name,
    )
    session = get_session(session_id)
    return attach_provenance(
        {
            "session_id": session_id,
            "dataset_handle": dataset["dataset_handle"],
            "dataset": dataset,
            "dataset_count": len(session["datasets"]),
        },
        tool="register_dataset",
        inputs={
            "session_id": session_id,
            "grid_path": grid_path,
            "data_path": data_path,
            "name": name,
        },
    )


def get_session_state(session_id: str) -> dict[str, Any]:
    """Return the persisted state for a scientific session."""
    return attach_provenance(
        get_session(session_id),
        tool="get_session_state",
        inputs={"session_id": session_id},
    )


def reset_session_state(
    session_id: str, clear_artifacts: bool = False
) -> dict[str, Any]:
    """Clear persisted results, operations, and workflows for a session."""
    result = reset_session_record(session_id, clear_artifacts=clear_artifacts)
    return attach_provenance(
        result,
        tool="reset_session_state",
        inputs={"session_id": session_id, "clear_artifacts": clear_artifacts},
    )


def get_result_handle(result_handle: str) -> dict[str, Any]:
    """Inspect a persisted result handle and its artifact metadata."""
    return attach_provenance(
        get_result(result_handle),
        tool="get_result_handle",
        inputs={"result_handle": result_handle},
    )


def get_operation_status(operation_id: str) -> dict[str, Any]:
    """Return the latest stage and event history for a tracked operation."""
    return attach_provenance(
        get_operation(operation_id),
        tool="get_operation_status",
        inputs={"operation_id": operation_id},
    )


def list_operations(session_id: str | None = None) -> dict[str, Any]:
    """List tracked operations globally or for one session."""
    operations = list_operation_records(session_id=session_id)
    return attach_provenance(
        {"operations": operations},
        tool="list_operations",
        inputs={"session_id": session_id},
    )


def _resolve_workflow_inputs(
    *,
    file_path: str | None,
    data_path: str | None,
    session_id: str | None,
    dataset_handle: str | None,
) -> tuple[str, str | None]:
    if dataset_handle is not None:
        if session_id is None:
            raise ValueError("session_id is required when dataset_handle is provided.")
        dataset = get_session(session_id)["datasets"].get(dataset_handle)
        if dataset is None:
            raise FileNotFoundError(
                f"Dataset handle {dataset_handle!r} not found in session {session_id!r}"
            )
        return dataset["grid_path"], dataset.get("data_path")
    if file_path is None:
        raise ValueError("file_path is required when dataset_handle is not provided.")
    return file_path, data_path


def _execute_workflow(workflow_id: str, *, resume: bool) -> dict[str, Any]:
    from uxarray_mcp.tools.execution_control import (
        probe_path_access,
        validate_hpc_setup,
    )
    from uxarray_mcp.tools.inspection import validate_dataset
    from uxarray_mcp.tools.remote_tools import (
        calculate_area,
        calculate_zonal_mean,
        inspect_mesh,
        inspect_variable,
    )

    workflow = get_workflow(workflow_id)
    workflow["status"] = "running"
    save_workflow(workflow)

    tracker = OperationTracker(
        tool_name="run_workflow",
        session_id=workflow.get("session_id"),
        workflow_id=workflow_id,
    )
    tracker.stage("planning", "Preparing canonical scientific workflow.")

    file_path = workflow["inputs"]["file_path"]
    data_path = workflow["inputs"].get("data_path")
    variable_name = workflow["inputs"].get("variable_name")
    sample_path = workflow["inputs"].get("sample_path")
    session_id = workflow.get("session_id")

    steps: list[tuple[str, Any]] = [
        (
            "validate_hpc_setup",
            lambda: validate_hpc_setup(
                run_remote_probe=True,
                sample_path=sample_path,
            ),
        ),
        (
            "probe_path_access",
            lambda: probe_path_access(sample_path or file_path, use_remote=False),
        ),
        ("inspect_mesh", lambda: inspect_mesh(file_path)),
        (
            "inspect_variable",
            lambda: (
                inspect_variable(file_path, data_path, variable_name)
                if data_path is not None
                else {"skipped": True}
            ),
        ),
        (
            "validate_dataset",
            lambda: (
                validate_dataset(file_path, data_path)
                if data_path is not None
                else {"skipped": True}
            ),
        ),
        ("calculate_area", lambda: calculate_area(file_path)),
    ]

    # `calculate_zonal_mean` depends on inspected variables and validation.
    zonal_step_name = "calculate_zonal_mean"
    last_results: dict[str, Any] = {}

    for step_name, runner in steps:
        current = get_workflow(workflow_id)
        state = next(step for step in current["steps"] if step["name"] == step_name)
        if resume and state["status"] == "completed":
            continue
        append_workflow_event(
            workflow_id, stage=step_name, message=f"Running {step_name}"
        )
        tracker.stage(step_name, f"Running {step_name}")
        update_workflow_step(workflow_id, step_name, status="running")
        try:
            result = runner()
            last_results[step_name] = result
            step_summary = "skipped" if result.get("skipped") else "completed"
            update_workflow_step(
                workflow_id,
                step_name,
                status="completed",
                summary=step_summary,
            )
            append_workflow_event(
                workflow_id,
                stage=step_name,
                message=f"{step_name} completed",
            )
        except Exception as exc:
            update_workflow_step(
                workflow_id,
                step_name,
                status="failed",
                error=str(exc),
            )
            workflow = get_workflow(workflow_id)
            workflow["status"] = "failed"
            save_workflow(workflow)
            tracker.fail(f"{step_name} failed: {exc}")
            raise

    inspected = last_results.get("inspect_variable", {})
    validation_result = last_results.get("validate_dataset", {})
    selected_variable = variable_name
    if data_path is not None and selected_variable is None:
        for variable in inspected.get("variables", []):
            if variable.get("location") == "faces":
                selected_variable = variable["name"]
                break

    should_run_zonal = (
        data_path is not None
        and selected_variable is not None
        and validation_result.get("passed", True) is not False
    )
    zonal_state = next(
        step
        for step in get_workflow(workflow_id)["steps"]
        if step["name"] == zonal_step_name
    )
    if should_run_zonal:
        if not (resume and zonal_state["status"] == "completed"):
            append_workflow_event(
                workflow_id,
                stage=zonal_step_name,
                message=f"Running {zonal_step_name} for {selected_variable}",
            )
            tracker.stage(zonal_step_name, f"Running {zonal_step_name}")
            update_workflow_step(workflow_id, zonal_step_name, status="running")
            zonal_result = calculate_zonal_mean(file_path, data_path, selected_variable)
            last_results[zonal_step_name] = zonal_result
            update_workflow_step(
                workflow_id,
                zonal_step_name,
                status="completed",
                summary="completed",
            )
    else:
        update_workflow_step(
            workflow_id,
            zonal_step_name,
            status="completed",
            summary="skipped",
        )

    workflow_summary: dict[str, Any] = {
        "mesh_summary": last_results.get("inspect_mesh"),
        "variable_results": last_results.get("inspect_variable"),
        "validation_summary": last_results.get("validate_dataset"),
        "area_results": last_results.get("calculate_area"),
        "zonal_mean_results": last_results.get(zonal_step_name),
    }
    result_record = persist_result(
        kind="workflow_summary",
        name=f"workflow:{workflow_id}",
        summary={"workflow_id": workflow_id, "status": "completed"},
        session_id=session_id,
        metadata=workflow_summary,
    )
    artifact_path = write_json_artifact(
        workflow_summary, result_record["result_handle"]
    )
    result_record["artifact_path"] = artifact_path
    save_result(result_record)
    workflow = get_workflow(workflow_id)
    workflow["result_handle"] = result_record["result_handle"]
    workflow["status"] = "completed"
    save_workflow(workflow)
    tracker.succeed("Workflow completed")
    append_workflow_event(
        workflow_id,
        stage="completed",
        message="Workflow completed successfully.",
    )
    return workflow


def run_workflow(
    file_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    sample_path: str | None = None,
) -> dict[str, Any]:
    """Run the canonical scientific workflow with persisted state and progress."""
    resolved_grid, resolved_data = _resolve_workflow_inputs(
        file_path=file_path,
        data_path=data_path,
        session_id=session_id,
        dataset_handle=dataset_handle,
    )
    workflow = create_workflow(
        template="scientific_analysis",
        inputs={
            "file_path": resolved_grid,
            "data_path": resolved_data,
            "variable_name": variable_name,
            "sample_path": sample_path,
        },
        session_id=session_id,
        steps=[
            "validate_hpc_setup",
            "probe_path_access",
            "inspect_mesh",
            "inspect_variable",
            "validate_dataset",
            "calculate_area",
            "calculate_zonal_mean",
        ],
    )
    workflow = _execute_workflow(workflow["workflow_id"], resume=False)
    return attach_provenance(
        workflow,
        tool="run_workflow",
        inputs={
            "file_path": file_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
            "sample_path": sample_path,
        },
    )


def resume_workflow(workflow_id: str) -> dict[str, Any]:
    """Resume a persisted workflow from the first pending or failed step."""
    workflow = _execute_workflow(workflow_id, resume=True)
    return attach_provenance(
        workflow,
        tool="resume_workflow",
        inputs={"workflow_id": workflow_id},
    )


def get_workflow_status(workflow_id: str) -> dict[str, Any]:
    """Return persisted workflow progress, events, and final result handle."""
    return attach_provenance(
        get_workflow(workflow_id),
        tool="get_workflow_status",
        inputs={"workflow_id": workflow_id},
    )
