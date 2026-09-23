"""Front-door refusals and dispatch branches that had no test reaching them.

Each of these is a gate the caller can hit with an ordinary request: a
misspelled operation, a box handed to a plot kind that cannot crop, a
verdict policy that is not one of the three, a session action that does
not exist. A gate nobody has ever tripped in a test is a gate whose
message may be wrong, whose branch may be dead, or whose refusal may have
quietly become a pass. This module trips every one.

It also covers the remote-URI guards in the tool layer. Every tool used
to check ``Path(p).exists()``; a URL fails that and, worse, ``Path``
collapses ``https://`` to ``https:/`` on the way through. The guards now
route a URI around both. Network is never touched: the loader is replaced
and the test asserts what string it was handed.
"""

from __future__ import annotations

import pytest

from uxarray_mcp.tools import (
    get_status,
    manage_session,
    plot_dataset,
    run_analysis,
)

REMOTE = "https://data.example.org/archive/grid.nc"


class TestUnknownOperationsAreNamedNotGuessed:
    def test_a_near_miss_suggests_the_real_name(self):
        with pytest.raises(ValueError) as excinfo:
            run_analysis(operation="calculate_zonal_means", grid_path="x.nc")
        message = str(excinfo.value)
        assert "Unsupported analysis operation" in message
        assert "Did you mean" in message
        assert "'calculate_zonal_mean'" in message

    def test_a_synonym_is_routed_through_the_hint_table(self):
        # "area" is not an operation; the hint table knows what it means.
        with pytest.raises(ValueError, match="'calculate_area'"):
            run_analysis(operation="area", grid_path="x.nc")

    def test_a_shared_token_still_produces_a_candidate(self):
        with pytest.raises(ValueError, match="Did you mean"):
            run_analysis(operation="mean_of_something", grid_path="x.nc")

    def test_gibberish_lists_the_catalog_without_a_guess(self):
        with pytest.raises(ValueError) as excinfo:
            run_analysis(operation="qzxv", grid_path="x.nc")
        message = str(excinfo.value)
        assert "Did you mean" not in message
        assert "Supported operations:" in message
        assert "get_capabilities" in message

    def test_a_missing_required_argument_names_the_operation(self):
        with pytest.raises(ValueError, match="'inspect_variable' requires data_path"):
            run_analysis(operation="inspect_variable", grid_path="g.nc")


class TestVerdictPolicyIsValidatedBeforeAnyWork:
    def test_an_unknown_policy_is_refused_up_front(self, state_dir):
        # The grid path does not exist: if the policy check ran after the
        # computation this would be a FileNotFoundError, not a ValueError.
        with pytest.raises(ValueError, match="verdict_policy must be one of"):
            run_analysis(
                operation="calculate_area",
                grid_path="/nonexistent/grid.nc",
                verdict_policy="maybe",
            )

    @pytest.mark.parametrize(
        "policy,status,has_residual",
        [
            ("full", "checked", True),
            ("reference_only", "reference_supplied", False),
            ("off", "not_evaluated", False),
        ],
    )
    def test_each_policy_shapes_the_postcondition_block(
        self, state_dir, structured_mesh_files, policy, status, has_residual
    ):
        grid_file, _ = structured_mesh_files
        result = run_analysis(
            operation="calculate_area",
            grid_path=grid_file,
            sphere_radius=6371000.0,
            verdict_policy=policy,
        )
        block = result["postconditions"]
        assert block["status"] == status
        if policy == "off":
            assert block["checks"] == []
            assert "no check was run" in block["not_evaluated_because"]
            return
        assert block["checks"], "a closed global mesh has an area identity to check"
        for check in block["checks"]:
            assert "reference" in check, check
            # reference_only withholds residual and verdict together: a
            # residual alone would let the caller infer the verdict.
            assert (check["residual"] is not None) is has_residual, check
            assert (check["passed"] is not None) is has_residual, check
            if not has_residual:
                assert check["caller_must_supply"] == ["residual", "passed"]
        assert block["independent_verification"] is (policy == "reference_only")

    def test_the_policy_survives_a_dash_spelling(self, state_dir, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        result = run_analysis(
            operation="calculate_area",
            grid_path=grid_file,
            sphere_radius=6371000.0,
            verdict_policy="reference-only",
        )
        assert result["postconditions"]["status"] == "reference_supplied"


class TestPlotKindsRefuseWhatTheyCannotHonor:
    def test_an_unknown_kind_lists_all_six(self):
        with pytest.raises(ValueError) as excinfo:
            plot_dataset(plot_type="hexbin", grid_path="x.nc")
        message = str(excinfo.value)
        for kind in ("mesh", "mesh_geo", "variable", "zonal_mean", "temporal_mean", "subset_bbox"):
            assert kind in message

    def test_mesh_refuses_a_box_and_names_the_kind_that_crops(self):
        with pytest.raises(ValueError, match="plot_type='subset_bbox'"):
            plot_dataset(plot_type="mesh", grid_path="x.nc", lon_bounds=[0, 10])

    def test_mesh_refuses_a_half_box_too(self):
        with pytest.raises(ValueError, match="cannot honor"):
            plot_dataset(plot_type="mesh", grid_path="x.nc", lat_bounds=[0, 10])

    def test_variable_refuses_a_box_and_names_temporal_mean(self):
        with pytest.raises(ValueError, match="plot_type='temporal_mean'"):
            plot_dataset(
                plot_type="variable",
                grid_path="x.nc",
                data_path="d.nc",
                variable_name="t",
                lon_bounds=[0, 10],
                lat_bounds=[0, 10],
            )

    def test_the_kind_is_normalised_before_matching(self):
        # "Temporal-Mean" reaches the temporal_mean branch, whose own
        # requirement (data) fires -- proof the spelling was accepted.
        with pytest.raises(ValueError, match="requires data_paths"):
            plot_dataset(plot_type="Temporal-Mean", grid_path="x.nc", variable_name="t")


class TestManageSessionActions:
    def test_create_then_get_round_trips(self, state_dir):
        created = manage_session(action="create", name="probe")
        session_id = created["session_id"]
        state = manage_session(action="get", session_id=session_id)
        assert state["session_id"] == session_id

    def test_register_dataset_then_look_it_up(self, state_dir, structured_mesh_files):
        grid_file, data_file = structured_mesh_files
        session_id = manage_session(action="create")["session_id"]
        registered = manage_session(
            action="register_dataset",
            session_id=session_id,
            grid_path=grid_file,
            data_path=data_file,
            name="mesh",
        )
        handle = registered["dataset_handle"]
        looked_up = manage_session(
            action="dataset", session_id=session_id, dataset_handle=handle
        )
        assert looked_up["dataset_handle"] == handle
        assert looked_up["dataset"]["grid_path"] == grid_file
        assert "_provenance" in looked_up

    def test_an_unknown_handle_is_a_not_found(self, state_dir):
        session_id = manage_session(action="create")["session_id"]
        with pytest.raises(FileNotFoundError, match="not found"):
            manage_session(
                action="dataset", session_id=session_id, dataset_handle="ds_nope"
            )

    def test_register_requires_a_session_and_a_grid(self, state_dir):
        with pytest.raises(ValueError, match="requires session_id"):
            manage_session(action="register_dataset", grid_path="g.nc")
        with pytest.raises(ValueError, match="requires grid_path"):
            manage_session(action="register_dataset", session_id="s")

    def test_list_operations_and_reset(self, state_dir, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        session_id = manage_session(action="create")["session_id"]
        run_analysis(
            operation="inspect_mesh", grid_path=grid_file, session_id=session_id
        )
        listed = manage_session(action="list_operations", session_id=session_id)
        assert listed["operations"], "the inspect_mesh call was tracked"
        reset = manage_session(action="reset", session_id=session_id)
        assert reset["session_id"] == session_id
        after = manage_session(action="list_operations", session_id=session_id)
        assert after["operations"] == []

    def test_an_unknown_action_lists_the_six(self):
        with pytest.raises(ValueError) as excinfo:
            manage_session(action="destroy")
        message = str(excinfo.value)
        for action in ("create", "register_dataset", "get", "reset", "list_operations", "dataset"):
            assert action in message

    def test_the_action_is_normalised(self, state_dir):
        # "Register-Dataset" reaches the branch; its own requirement fires.
        with pytest.raises(ValueError, match="requires session_id"):
            manage_session(action="Register-Dataset", grid_path="g.nc")


class TestGetStatusKinds:
    def test_operation_status_after_a_tracked_call(self, state_dir, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        result = run_analysis(operation="inspect_mesh", grid_path=grid_file)
        operation_id = result["_provenance"]["operation_id"]
        status = get_status(kind="operation", operation_id=operation_id)
        assert status["operation_id"] == operation_id
        assert status["status"] == "completed"

    def test_workflow_status_after_a_run(self, state_dir, structured_mesh_files):
        from uxarray_mcp.tools import run_workflow

        grid_file, data_file = structured_mesh_files
        run = run_workflow(
            file_path=grid_file, data_path=data_file, variable_name="temperature"
        )
        status = get_status(kind="workflow", workflow_id=run["workflow_id"])
        assert status["workflow_id"] == run["workflow_id"]
        assert status["status"] in {"succeeded", "completed", "failed"}

    def test_each_kind_requires_its_own_id(self):
        with pytest.raises(ValueError, match="requires workflow_id"):
            get_status(kind="workflow")
        with pytest.raises(ValueError, match="requires operation_id"):
            get_status(kind="operation")

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ValueError, match="kind must be one of"):
            get_status(kind="job", workflow_id="w")


class TestRemoteUrisPassTheToolGuardsIntact:
    """No ``Path(url).exists()``, no ``https:/`` corruption, no network."""

    @pytest.fixture
    def real_grid(self, structured_mesh_files):
        from uxarray_mcp.domain.mesh import load_grid

        grid_file, _ = structured_mesh_files
        return load_grid(grid_file)

    def test_inspect_mesh_hands_the_uri_through_and_reports_no_size(
        self, state_dir, monkeypatch, real_grid
    ):
        from uxarray_mcp.tools import inspection

        seen: list[str] = []

        def fake_load_grid(path):
            seen.append(path)
            return real_grid

        monkeypatch.setattr(inspection, "load_grid", fake_load_grid)
        result = run_analysis(operation="inspect_mesh", grid_path=REMOTE)
        assert seen == [REMOTE], "the URI must reach the loader unaltered"
        assert result["file_size_mb"] is None
        assert result["n_face"] == int(real_grid.n_face)

    def test_calculate_area_does_not_demand_a_local_file(
        self, state_dir, monkeypatch, real_grid
    ):
        from uxarray_mcp.tools import inspection

        monkeypatch.setattr(inspection, "load_grid", lambda path: real_grid)
        result = run_analysis(
            operation="calculate_area", grid_path=REMOTE, sphere_radius=6371000.0
        )
        assert result["total_area"] > 0

    def test_get_capabilities_does_not_demand_a_local_file(
        self, state_dir, monkeypatch, real_grid
    ):
        from uxarray_mcp.tools import capabilities, get_capabilities

        seen: list[str] = []

        def fake_load_grid(path):
            seen.append(path)
            return real_grid

        monkeypatch.setattr(capabilities, "load_grid", fake_load_grid)
        result = get_capabilities(grid_path=REMOTE)
        assert seen == [REMOTE]
        assert result["grid_summary"]["n_face"] == int(real_grid.n_face)

    def test_register_dataset_accepts_a_uri_it_cannot_stat(self, state_dir):
        session_id = manage_session(action="create")["session_id"]
        registered = manage_session(
            action="register_dataset",
            session_id=session_id,
            grid_path=REMOTE,
            data_path="s3://bucket/data.nc",
        )
        assert registered["dataset"]["grid_path"] == REMOTE
        assert registered["dataset"]["data_path"] == "s3://bucket/data.nc"

    def test_a_local_path_that_does_not_exist_is_still_refused(self, state_dir):
        session_id = manage_session(action="create")["session_id"]
        with pytest.raises(FileNotFoundError, match="Grid file not found"):
            manage_session(
                action="register_dataset",
                session_id=session_id,
                grid_path="/nonexistent/grid.nc",
            )

    def test_the_local_fallback_gate_treats_a_uri_as_reachable(self):
        from uxarray_mcp.tools.remote_tools import _path_is_locally_reachable

        assert _path_is_locally_reachable(REMOTE)
        assert _path_is_locally_reachable("s3://bucket/key.nc")
        assert _path_is_locally_reachable("healpix:3")
        assert _path_is_locally_reachable(None)
        assert not _path_is_locally_reachable("/nonexistent/grid.nc")
