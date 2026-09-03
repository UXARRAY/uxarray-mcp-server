"""Structured scientific contract fields on the MCP analysis front door."""

from __future__ import annotations

import pytest

from uxarray_mcp.preconditions import OVERRIDE_TOKEN, PreconditionRefusal
from uxarray_mcp.tools.frontdoor import (
    _finalize_analysis_result,
    _resolve_optional_session,
    run_analysis,
)


def test_run_analysis_signature_is_preserved():
    assert "operation" in run_analysis.__annotations__
    assert "grid_path" in run_analysis.__annotations__


def test_complete_operation_has_explicit_unverified_postconditions():
    result = _finalize_analysis_result("remap_to_rectilinear", {"stats": {"mean": 1.0}})

    assert result["scientific_status"] == {
        "status": "complete",
        "physically_interpretable": None,
        "warning_codes": [],
    }
    assert result["postconditions"] == {
        "status": "not_evaluated",
        "checks": [],
        "independent_verification": False,
    }


def test_failed_validation_is_invalid():
    result = _finalize_analysis_result("validate_dataset", {"passed": False})

    assert result["scientific_status"] == {
        "status": "invalid",
        "physically_interpretable": None,
        "warning_codes": ["DATASET_VALIDATION_FAILED"],
    }


def test_vector_warning_now_refuses_instead_of_warning():
    """#86: unverifiable components refuse rather than return a number."""
    with pytest.raises(PreconditionRefusal) as excinfo:
        _finalize_analysis_result(
            "curl", {"component_warnings": ["components lack velocity units"]}
        )

    payload = excinfo.value.payload
    assert payload["result_type"] == "input_required"
    assert {c["id"] for c in payload["refusal"]["failed_checks"]} == {
        "velocity_units",
        "component_identity",
        "radius_scaling",
    }
    assert payload["refusal"]["override"]["value"] == OVERRIDE_TOKEN
    assert payload["request_state"].startswith("precondition:curl:")


def test_override_returns_the_number_but_never_claims_it_is_physical():
    result = _finalize_analysis_result(
        "curl",
        {"component_warnings": ["components lack velocity units"]},
        acknowledge=OVERRIDE_TOKEN,
    )

    assert result["preconditions"]["status"] == "overridden"
    assert result["preconditions"]["override_used"] is True
    assert result["scientific_status"]["status"] == "unverified"
    assert result["scientific_status"]["physically_interpretable"] is False
    assert (
        "PRECONDITION_FAILED_VELOCITY_UNITS"
        in result["scientific_status"]["warning_codes"]
    )


def test_wrong_override_token_still_refuses():
    """A plausible-looking guess must not buy the number."""
    with pytest.raises(PreconditionRefusal) as excinfo:
        _finalize_analysis_result(
            "curl",
            {"component_warnings": ["components lack velocity units"]},
            acknowledge="yes",
        )

    assert "is not the override token" in excinfo.value.payload["refusal"]["hint"]


def test_refusal_reports_only_repairs_for_checks_that_failed():
    with pytest.raises(PreconditionRefusal) as excinfo:
        _finalize_analysis_result(
            "curl",
            {
                "u_variable": "uo",
                "v_variable": "vo",
                "component_warnings": [],
                "component_evidence": {
                    "u": {"units": "m s-1", "velocity_units": True, "eastward": True},
                    "v": {"units": "m s-1", "velocity_units": True, "northward": True},
                    "units_supported": True,
                    "component_identity_supported": True,
                },
                "scale_by_radius": False,
            },
        )

    refusal = excinfo.value.payload["refusal"]
    assert [c["id"] for c in refusal["failed_checks"]] == ["radius_scaling"]
    assert len(refusal["repairs"]) == 1


def test_supported_vector_is_physically_interpretable():
    result = _finalize_analysis_result(
        "divergence",
        {
            "component_warnings": [],
            "component_evidence": {
                "units_supported": True,
                "component_identity_supported": True,
            },
            "scale_by_radius": True,
        },
    )

    assert result["scientific_status"] == {
        "status": "complete",
        "physically_interpretable": True,
        "warning_codes": [],
    }
    assert result["preconditions"]["status"] == "satisfied"
    assert result["result_type"] == "complete"


def test_unscaled_curl_refuses_on_the_radius_scaling_precondition():
    with pytest.raises(PreconditionRefusal) as excinfo:
        _finalize_analysis_result(
            "curl",
            {
                "component_warnings": [],
                "component_evidence": {
                    "units_supported": True,
                    "component_identity_supported": True,
                },
                "scale_by_radius": False,
            },
        )

    assert "radius_scaling" in [
        c["id"] for c in excinfo.value.payload["refusal"]["failed_checks"]
    ]


def test_unscaled_divergence_refuses_on_the_radius_scaling_precondition():
    """Divergence takes ``scale_by_radius`` exactly as curl does, so unit-sphere
    output must be refused for it too rather than returned as if physical."""
    with pytest.raises(PreconditionRefusal) as excinfo:
        _finalize_analysis_result(
            "divergence",
            {
                "component_warnings": [],
                "component_evidence": {
                    "units_supported": True,
                    "component_identity_supported": True,
                },
                "scale_by_radius": False,
            },
        )

    assert "radius_scaling" in [
        c["id"] for c in excinfo.value.payload["refusal"]["failed_checks"]
    ]


def test_validate_dataset_reports_failure_instead_of_refusing():
    """Refusing to report an invalid dataset would be circular: saying so
    IS the answer this operation exists to give."""
    result = _finalize_analysis_result("validate_dataset", {"passed": False})

    assert result["scientific_status"]["status"] == "invalid"
    assert result["preconditions"]["status"] == "failed"
    assert result["preconditions"]["failed_checks"] == ["dataset_valid"]


def test_unchecked_operation_is_not_evaluated_not_failed():
    """#84 and #86 are different states and must stay distinct."""
    result = _finalize_analysis_result("calculate_area", {"stats": {"mean": 1.0}})

    assert result["preconditions"]["status"] == "not_evaluated"
    assert result["preconditions"]["checks"] == []


def test_nonexistent_optional_session_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path))

    assert _resolve_optional_session("correlation-label", None) is None


def test_dataset_handle_keeps_strict_session_resolution():
    assert (
        _resolve_optional_session("required-session", "dataset_123")
        == "required-session"
    )


class TestDatasetHandleDereference:
    """A minted handle must stand in for the paths it was minted from.

    Callers are instructed to pass server-minted handles back verbatim rather
    than re-derive file paths. An operation that then demands the paths makes
    the handle a dead token, so every front-door operation resolves it.
    """

    def test_handle_supplies_paths_to_operations(
        self, synthetic_mesh_with_data, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path / "state"))
        from uxarray_mcp.tools import create_session, register_dataset

        grid_file, data_file = synthetic_mesh_with_data
        session = create_session("handle-deref")
        registered = register_dataset(
            session_id=session["session_id"],
            grid_path=grid_file,
            data_path=data_file,
        )

        for operation in ("inspect_mesh", "calculate_area", "validate_dataset"):
            result = run_analysis(
                operation=operation,
                session_id=session["session_id"],
                dataset_handle=registered["dataset_handle"],
            )
            assert result["scientific_status"]["status"] != "invalid"

    def test_explicit_path_overrides_the_handle(
        self, synthetic_mesh_with_data, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path / "state"))
        from uxarray_mcp.tools import create_session, register_dataset
        from uxarray_mcp.tools.frontdoor import _paths_from_handle

        grid_file, data_file = synthetic_mesh_with_data
        session = create_session("handle-override")
        registered = register_dataset(
            session_id=session["session_id"],
            grid_path=grid_file,
            data_path=data_file,
        )

        resolved = _paths_from_handle(
            session["session_id"],
            registered["dataset_handle"],
            "/explicit/grid.nc",
            None,
        )
        assert resolved == ("/explicit/grid.nc", data_file)

    def test_unknown_handle_names_the_registered_ones(self, monkeypatch, tmp_path):
        monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path / "state"))
        from uxarray_mcp.tools import create_session
        from uxarray_mcp.tools.frontdoor import _paths_from_handle

        session = create_session("handle-unknown")
        with pytest.raises(FileNotFoundError, match="Registered handles"):
            _paths_from_handle(session["session_id"], "dataset_missing", None, None)

    def test_handle_without_session_names_the_repair(self):
        from uxarray_mcp.tools.frontdoor import _paths_from_handle

        with pytest.raises(ValueError, match="session_id returned by create_session"):
            _paths_from_handle(None, "dataset_123", None, None)


ZERO_COVERAGE_RESULT = {
    "stats": {"mean": 1.0},
    "source_coverage": {
        "points_in_source": 0,
        "n_target_points": 25,
        "source_bbox": {
            "lon_min": 40.0,
            "lon_max": 47.0,
            "lat_min": -2.0,
            "lat_max": 2.0,
        },
        "warning_codes": [
            "REMAP_COVERAGE_ZERO",
            "REMAP_METHOD_NOT_CONSERVATIVE",
        ],
    },
}


def test_remap_zero_coverage_refuses():
    with pytest.raises(PreconditionRefusal) as excinfo:
        _finalize_analysis_result("remap_to_rectilinear", dict(ZERO_COVERAGE_RESULT))

    payload = excinfo.value.payload
    assert payload["result_type"] == "input_required"
    assert [c["id"] for c in payload["refusal"]["failed_checks"]] == [
        "remap_coverage_nonzero"
    ]
    # The refusal names the extent the caller has to overlap, otherwise the
    # only available repair is guessing.
    assert "40" in payload["refusal"]["failed_checks"][0]["detail"]


def test_remap_zero_coverage_override_is_unverified():
    result = _finalize_analysis_result(
        "remap_to_rectilinear",
        dict(ZERO_COVERAGE_RESULT),
        acknowledge=OVERRIDE_TOKEN,
    )

    assert result["preconditions"]["status"] == "overridden"
    assert result["scientific_status"] == {
        "status": "unverified",
        "physically_interpretable": False,
        "warning_codes": [
            "REMAP_COVERAGE_ZERO",
            "REMAP_METHOD_NOT_CONSERVATIVE",
            "PRECONDITION_FAILED_REMAP_COVERAGE_NONZERO",
        ],
    }


def test_remap_partial_coverage_still_only_warns():
    result = _finalize_analysis_result(
        "remap_to_rectilinear",
        {
            "stats": {"mean": 1.0},
            "source_coverage": {
                "points_in_source": 9,
                "n_target_points": 25,
                "warning_codes": ["REMAP_COVERAGE_PARTIAL"],
            },
        },
    )

    assert result["preconditions"]["status"] == "satisfied"
    assert result["scientific_status"] == {
        "status": "warning",
        "physically_interpretable": False,
        "warning_codes": ["REMAP_COVERAGE_PARTIAL"],
    }


def test_front_door_preserves_domain_warning_codes():
    """A code only the computation can raise must survive the front door.

    ``SPHERE_RADIUS_UNAVAILABLE`` is emitted by UXarray inside ``curl``/
    ``gradient`` and attached by the domain layer. The front door used to
    assign a fresh ``scientific_status`` dict, which dropped the code and
    reset the verdict to an unqualified ``complete`` -- presenting a result
    the domain had already marked uninterpretable as a clean one.
    """
    result = _finalize_analysis_result(
        "curl",
        {
            "component_warnings": [],
            "component_evidence": {
                "units_supported": True,
                "component_identity_supported": True,
            },
            "scale_by_radius": True,
            "scientific_status": {
                "status": "warning",
                "physically_interpretable": False,
                "warning_codes": ["SPHERE_RADIUS_UNAVAILABLE"],
                "warnings": ["grid has no 'sphere_radius' attribute"],
                "physical_scaling_requested": True,
                "physical_scaling_applied": False,
            },
        },
    )

    status = result["scientific_status"]
    assert "SPHERE_RADIUS_UNAVAILABLE" in status["warning_codes"]
    assert status["physically_interpretable"] is False
    assert status["status"] == "warning"
    # Domain-only detail keys survive the merge rather than being dropped.
    assert status["physical_scaling_applied"] is False


def test_front_door_status_merge_keeps_the_stricter_verdict():
    """Neither layer may upgrade the other's negative judgment.

    Both directions must hold. The front door may downgrade a domain verdict
    it knows to be too generous (the override path), and it must not upgrade
    a domain verdict that is stricter than its own -- the latter is the case
    that regressed when the block was assigned rather than merged.
    """
    # Front door is stricter: domain saw nothing wrong, but the caller
    # overrode a failed precondition, so the result cannot claim to be clean.
    overridden = _finalize_analysis_result(
        "curl",
        {
            "component_warnings": [],
            "component_evidence": {},
            "scale_by_radius": True,
            "scientific_status": {
                "status": "complete",
                "physically_interpretable": True,
                "warning_codes": [],
            },
        },
        OVERRIDE_TOKEN,
    )
    assert overridden["scientific_status"]["status"] == "unverified"
    assert overridden["scientific_status"]["physically_interpretable"] is False

    # Domain is stricter: the front door's own checks all pass, so on its own
    # it would report `complete`. It must not overwrite the domain's warning.
    domain_stricter = _finalize_analysis_result(
        "curl",
        {
            "component_warnings": [],
            "component_evidence": {
                "units_supported": True,
                "component_identity_supported": True,
            },
            "scale_by_radius": True,
            "scientific_status": {
                "status": "warning",
                "physically_interpretable": False,
                "warning_codes": ["SPHERE_RADIUS_UNAVAILABLE"],
            },
        },
    )
    assert domain_stricter["scientific_status"]["status"] == "warning"
    assert domain_stricter["scientific_status"]["physically_interpretable"] is False
    assert domain_stricter["scientific_status"]["warning_codes"] == [
        "SPHERE_RADIUS_UNAVAILABLE"
    ]

    # Codes from both layers accumulate instead of one replacing the other.
    both = _finalize_analysis_result(
        "curl",
        {
            "component_warnings": [],
            "component_evidence": {},
            "scale_by_radius": True,
            "scientific_status": {
                "status": "warning",
                "physically_interpretable": False,
                "warning_codes": ["SPHERE_RADIUS_UNAVAILABLE"],
            },
        },
        OVERRIDE_TOKEN,
    )
    codes = both["scientific_status"]["warning_codes"]
    assert "SPHERE_RADIUS_UNAVAILABLE" in codes
    assert any(c.startswith("PRECONDITION_FAILED_") for c in codes)
    assert both["scientific_status"]["status"] == "unverified"


def _comparison_result(units_a, units_b, **overrides):
    result = {
        "variable_name": "tas",
        "metrics": {"bias": 273.15, "rmse": 273.15, "pattern_correlation": 1.0},
        "area_weighting": {"weighted": True, "equal_area": True},
        "units": {"a": units_a, "b": units_b, "comparable": None},
    }
    left = units_a and units_a.strip()
    right = units_b and units_b.strip()
    if left and right:
        result["units"]["comparable"] = left.lower() == right.lower()
    result.update(overrides)
    return result


@pytest.mark.parametrize("operation", ["compare_fields", "bias", "rmse"])
def test_mismatched_units_refuse_before_the_difference_is_reported(operation):
    """K minus degC is 273.15, which reads as a huge model error rather than
    as the unit offset it actually is. That is the case worth refusing."""
    with pytest.raises(PreconditionRefusal) as excinfo:
        _finalize_analysis_result(operation, _comparison_result("K", "degC"))

    payload = excinfo.value.payload
    assert "units_comparable" in [c["id"] for c in payload["refusal"]["failed_checks"]]
    assert "stats" not in payload and "metrics" not in payload


def test_matching_units_are_not_refused():
    result = _finalize_analysis_result("compare_fields", _comparison_result("K", "K"))

    assert result["preconditions"]["status"] == "satisfied"
    assert result["scientific_status"]["status"] == "complete"


def test_undeclared_units_warn_rather_than_refuse():
    """Comparing two unlabeled fields is ordinary; refusing would make it
    impossible. The result has to say the scale is unconfirmed, though."""
    result = _finalize_analysis_result(
        "compare_fields",
        _comparison_result(
            None,
            "K",
            scientific_status={
                "status": "warning",
                "physically_interpretable": False,
                "warning_codes": ["UNITS_UNDECLARED"],
                "warnings": ["units unconfirmed"],
            },
        ),
    )

    assert result["preconditions"]["status"] == "satisfied"
    assert result["scientific_status"]["status"] == "warning"
    assert "UNITS_UNDECLARED" in result["scientific_status"]["warning_codes"]


def test_the_override_token_still_returns_the_mismatched_comparison():
    result = _finalize_analysis_result(
        "compare_fields", _comparison_result("K", "degC"), OVERRIDE_TOKEN
    )

    assert result["preconditions"]["override_used"] is True
    assert result["metrics"]["bias"] == 273.15
