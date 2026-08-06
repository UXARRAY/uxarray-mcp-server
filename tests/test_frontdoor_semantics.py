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


def test_remap_zero_coverage_is_not_physically_interpretable():
    result = _finalize_analysis_result(
        "remap_to_rectilinear",
        {
            "stats": {"mean": 1.0},
            "source_coverage": {
                "points_in_source": 0,
                "n_target_points": 25,
                "warning_codes": [
                    "REMAP_COVERAGE_ZERO",
                    "REMAP_METHOD_NOT_CONSERVATIVE",
                ],
            },
        },
    )

    assert result["scientific_status"] == {
        "status": "warning",
        "physically_interpretable": False,
        "warning_codes": [
            "REMAP_COVERAGE_ZERO",
            "REMAP_METHOD_NOT_CONSERVATIVE",
        ],
    }
