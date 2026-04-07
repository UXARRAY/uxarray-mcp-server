"""Tests for session, workflow, and persisted result tools."""

from pathlib import Path

from uxarray_mcp.tools import (
    create_session,
    get_result_handle,
    get_session_state,
    get_workflow_status,
    list_operations,
    register_dataset,
    reset_session_state,
    run_workflow,
)


def test_create_session_and_register_dataset(state_dir, synthetic_mesh_with_data):
    """Sessions should persist datasets and stay inspectable."""
    grid_file, data_file = synthetic_mesh_with_data

    session = create_session("integration-session")
    dataset = register_dataset(
        session["session_id"],
        grid_path=grid_file,
        data_path=data_file,
        name="sample-dataset",
    )
    state = get_session_state(session["session_id"])

    assert session["session_id"].startswith("session_")
    assert dataset["dataset_handle"].startswith("dataset_")
    assert state["datasets"][dataset["dataset_handle"]]["name"] == "sample-dataset"
    assert Path(state_dir, "sessions", f"{session['session_id']}.json").exists()


def test_run_workflow_persists_status_result_and_operations(
    monkeypatch, state_dir, synthetic_mesh_with_data
):
    """Workflows should persist status, result handles, and progress records."""
    grid_file, data_file = synthetic_mesh_with_data
    monkeypatch.setattr(
        "uxarray_mcp.tools.execution_control.validate_hpc_setup",
        lambda **kwargs: {"passed": True, "checks": [], "_provenance": {}},
    )

    session = create_session("workflow-session")
    dataset = register_dataset(
        session["session_id"],
        grid_path=grid_file,
        data_path=data_file,
    )

    workflow = run_workflow(
        session_id=session["session_id"],
        dataset_handle=dataset["dataset_handle"],
        variable_name="temperature",
    )
    workflow_status = get_workflow_status(workflow["workflow_id"])
    result = get_result_handle(workflow["result_handle"])
    operations = list_operations(session["session_id"])

    assert workflow["status"] == "completed"
    assert workflow_status["status"] == "completed"
    assert workflow_status["result_handle"] == workflow["result_handle"]
    assert Path(result["artifact_path"]).exists()
    assert any(
        operation["tool_name"] == "run_workflow"
        for operation in operations["operations"]
    )
    assert Path(state_dir, "workflows", f"{workflow['workflow_id']}.json").exists()


def test_reset_session_state_clears_results_workflows_and_operations(
    monkeypatch, state_dir, synthetic_mesh_with_data
):
    """Reset should clear persisted result, workflow, and operation records."""
    grid_file, data_file = synthetic_mesh_with_data
    monkeypatch.setattr(
        "uxarray_mcp.tools.execution_control.validate_hpc_setup",
        lambda **kwargs: {"passed": True, "checks": [], "_provenance": {}},
    )

    session = create_session("reset-session")
    dataset = register_dataset(
        session["session_id"],
        grid_path=grid_file,
        data_path=data_file,
    )
    workflow = run_workflow(
        session_id=session["session_id"],
        dataset_handle=dataset["dataset_handle"],
        variable_name="temperature",
    )
    cleared = reset_session_state(session["session_id"], clear_artifacts=True)
    state = get_session_state(session["session_id"])

    assert workflow["result_handle"] in cleared["cleared_results"]
    assert workflow["workflow_id"] in cleared["cleared_workflows"]
    assert state["results"] == {}
    assert state["workflow_ids"] == []
    assert state["operation_ids"] == []
    assert not Path(
        state_dir, "results", f"{workflow['result_handle']}.json"
    ).exists()
