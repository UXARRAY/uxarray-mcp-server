"""Structured scientific contract fields on the MCP analysis front door."""

from __future__ import annotations

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


def test_vector_warning_marks_result_not_physically_interpretable():
    result = _finalize_analysis_result(
        "curl", {"component_warnings": ["components lack velocity units"]}
    )

    assert result["scientific_status"] == {
        "status": "warning",
        "physically_interpretable": False,
        "warning_codes": ["VECTOR_COMPONENTS_UNVERIFIED"],
    }


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


def test_unscaled_curl_is_not_physically_interpretable():
    result = _finalize_analysis_result(
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

    assert result["scientific_status"] == {
        "status": "warning",
        "physically_interpretable": False,
        "warning_codes": ["PHYSICAL_SCALING_UNVERIFIED"],
    }


def test_nonexistent_optional_session_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path))

    assert _resolve_optional_session("correlation-label", None) is None


def test_dataset_handle_keeps_strict_session_resolution():
    assert (
        _resolve_optional_session("required-session", "dataset_123")
        == "required-session"
    )
