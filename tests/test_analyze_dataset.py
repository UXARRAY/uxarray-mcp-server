"""Tests for analyze_dataset (issue #32).

The tool runs a fixed pipeline of inspection, validation, and analysis
calls and returns a single structured result with provenance and
recommended next steps.
"""

from uxarray_mcp.tools import (
    analyze_dataset,
    create_session,
    register_dataset,
)


def test_analyze_dataset_healpix_no_data():
    """Without a data file the mesh-only stages should still run."""
    result = analyze_dataset("healpix:2", include_plots=False)

    assert result["mesh"] is not None
    assert result["mesh"]["n_face"] == 192
    assert result["area"] is not None
    assert result["validation"] is None
    assert result["variables"] is None
    assert result["zonal_mean"] is None
    assert result["selected_variable"] is None
    assert result["warnings"] == []
    assert "inspect_mesh" in result["stages_run"]
    assert "calculate_area" in result["stages_run"]
    # No data, so first hint should ask the agent to provide a data file.
    assert any("data_path" in s for s in result["recommended_next_steps"])
    assert result["_provenance"]["tool"] == "analyze_dataset"


def test_analyze_dataset_with_data_runs_full_pipeline(synthetic_mesh_with_data):
    grid_file, data_file = synthetic_mesh_with_data
    result = analyze_dataset(grid_file, data_file, include_plots=False)

    assert result["mesh"] is not None
    assert result["validation"] is not None
    assert result["validation"]["passed"] is True
    assert result["variables"] is not None
    assert result["area"] is not None
    assert result["selected_variable"] in {"temperature", "pressure"}
    assert result["zonal_mean"] is not None
    for required in (
        "inspect_mesh",
        "validate_dataset",
        "inspect_variable",
        "calculate_area",
        "calculate_zonal_mean",
    ):
        assert required in result["stages_run"]


def test_analyze_dataset_includes_plots_by_default():
    """Plot stages should produce base64 PNGs when include_plots=True."""
    result = analyze_dataset("healpix:2")

    assert result["mesh_plot"] is not None
    assert result["mesh_plot"]["png_b64"]
    assert "plot_mesh" in result["stages_run"]


def test_analyze_dataset_resolves_session_dataset_handle(synthetic_mesh_with_data):
    grid_file, data_file = synthetic_mesh_with_data
    session = create_session("analyze-handle-test")
    registered = register_dataset(
        session_id=session["session_id"],
        grid_path=grid_file,
        data_path=data_file,
        name="grid-and-data",
    )

    result = analyze_dataset(
        session_id=session["session_id"],
        dataset_handle=registered["dataset_handle"],
        include_plots=False,
    )

    assert result["grid_path"] == grid_file
    assert result["data_path"] == data_file
    assert result["mesh"]["n_face"] == 1
    assert result["validation"]["passed"] is True
    assert result["selected_variable"] in {"temperature", "pressure"}


def test_analyze_dataset_failure_in_one_stage_does_not_abort(monkeypatch):
    """A stage error should be captured in warnings; other stages still run."""
    from uxarray_mcp.tools import remote_tools

    def boom(*args, **kwargs):
        raise RuntimeError("simulated area failure")

    monkeypatch.setattr(remote_tools, "calculate_area", boom)

    result = analyze_dataset("healpix:2", include_plots=False)

    assert result["mesh"] is not None
    assert result["area"] is None
    assert any("calculate_area" in w for w in result["warnings"])
    assert "inspect_mesh" in result["stages_run"]
    assert "calculate_area" not in result["stages_run"]


def test_analyze_dataset_recommended_next_steps_present(synthetic_mesh_with_data):
    grid_file, data_file = synthetic_mesh_with_data
    result = analyze_dataset(grid_file, data_file, include_plots=False)

    steps = result["recommended_next_steps"]
    assert isinstance(steps, list) and len(steps) >= 1
    joined = " ".join(steps)
    # With a face-centered variable in scope, the chain should suggest
    # plotting / cross-section / subsetting follow-ups.
    assert any(
        kw in joined
        for kw in ("plot_zonal_mean", "extract_cross_section", "subset_bbox")
    )


def test_validation_failure_blocks_downstream_statistics(
    monkeypatch, synthetic_mesh_with_data
):
    """Validation failure must prevent zonal statistics and variable plots."""
    from uxarray_mcp.tools import inspection, remote_tools

    grid_file, data_file = synthetic_mesh_with_data
    monkeypatch.setattr(
        inspection,
        "validate_dataset",
        lambda *args, **kwargs: {
            "passed": False,
            "n_variables_checked": 2,
            "n_variables_failed": 1,
            "_provenance": {"warnings": ["invalid values"]},
        },
    )
    monkeypatch.setattr(
        remote_tools,
        "calculate_zonal_mean",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("zonal mean must not run")
        ),
    )
    monkeypatch.setattr(
        remote_tools,
        "plot_variable",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("variable plot must not run")
        ),
    )

    result = analyze_dataset(grid_file, data_file, include_plots=True)
    assert result["zonal_mean"] is None
    assert result["variable_plot"] is None
    assert any("validation failed" in warning for warning in result["warnings"])
    assert result["_provenance"]["validation_summary"]["passed"] is False


def test_requested_remote_with_local_stages_reports_actual_venue(
    monkeypatch, synthetic_mesh_with_data
):
    """Aggregate venue comes from stage provenance, not the use_remote request."""
    from uxarray_mcp.tools import remote_tools

    grid_file, data_file = synthetic_mesh_with_data

    def force_local(result):
        result["_provenance"]["execution_venue"] = "local"
        return result

    original_inspect = remote_tools.inspect_mesh
    original_variables = remote_tools.inspect_variable
    original_area = remote_tools.calculate_area
    original_zonal = remote_tools.calculate_zonal_mean
    monkeypatch.setattr(
        remote_tools,
        "inspect_mesh",
        lambda *args, **kwargs: force_local(original_inspect(args[0])),
    )
    monkeypatch.setattr(
        remote_tools,
        "inspect_variable",
        lambda *args, **kwargs: force_local(
            original_variables(args[0], args[1], args[2])
        ),
    )
    monkeypatch.setattr(
        remote_tools,
        "calculate_area",
        lambda *args, **kwargs: force_local(original_area(args[0])),
    )
    monkeypatch.setattr(
        remote_tools,
        "calculate_zonal_mean",
        lambda *args, **kwargs: force_local(original_zonal(args[0], args[1], args[2])),
    )
    result = analyze_dataset(grid_file, data_file, use_remote=True, include_plots=False)
    assert result["_provenance"]["execution_venue"] == "local"
