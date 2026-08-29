"""Refusable preconditions and the MRTR-shaped refusal payload (issue #86)."""

from __future__ import annotations

import json

import pytest

from uxarray_mcp.preconditions import (
    OVERRIDE_TOKEN,
    RESULT_TYPE_INPUT_REQUIRED,
    PreconditionRefusal,
    enforce,
    evaluate_comparison_preconditions,
    evaluate_validation_preconditions,
    evaluate_vector_preconditions,
    normalize_units,
)

VELOCITY_EVIDENCE = {
    "u": {"units": "m s-1", "velocity_units": True, "eastward": True},
    "v": {"units": "m s-1", "velocity_units": True, "northward": True},
    "units_supported": True,
    "component_identity_supported": True,
}

BARE_EVIDENCE = {
    "u": {"units": None, "velocity_units": False, "eastward": False},
    "v": {"units": None, "velocity_units": False, "northward": False},
    "units_supported": False,
    "component_identity_supported": False,
}


class TestVectorPreconditions:
    def test_labeled_velocity_components_satisfy_every_check(self):
        checks = evaluate_vector_preconditions(
            "curl", "uo", "vo", VELOCITY_EVIDENCE, True
        )

        assert [c["id"] for c in checks] == [
            "components_distinct",
            "velocity_units",
            "component_identity",
            "radius_scaling",
        ]
        assert all(c["passed"] for c in checks)

    def test_divergence_requires_radius_scaling_like_curl(self):
        """UXarray's ``divergence`` takes ``scale_by_radius`` just as ``curl``
        does, so an unscaled divergence is unit-sphere output for the same
        reason and must be refused the same way."""
        checks = evaluate_vector_preconditions(
            "divergence", "uo", "vo", VELOCITY_EVIDENCE, False
        )

        radius = next(c for c in checks if c["id"] == "radius_scaling")
        assert not radius["passed"]
        assert all(c["passed"] for c in checks if c["id"] != "radius_scaling")

    def test_same_field_as_both_components_fails(self):
        checks = evaluate_vector_preconditions(
            "divergence", "temp", "temp", VELOCITY_EVIDENCE, None
        )

        assert not next(c for c in checks if c["id"] == "components_distinct")["passed"]

    def test_missing_names_abstain_rather_than_fail_distinctness(self):
        """An absent name is a gap in what we were told, not evidence that
        the same field was passed twice."""
        checks = evaluate_vector_preconditions("curl", "", "", VELOCITY_EVIDENCE, True)

        assert next(c for c in checks if c["id"] == "components_distinct")["passed"]

    def test_byte_identical_arrays_are_separated_by_metadata_alone(self):
        """The study's core case: two pairs a model cannot tell apart from
        the numbers. Only the labeled pair should pass."""
        labeled = evaluate_vector_preconditions(
            "curl", "uo", "vo", VELOCITY_EVIDENCE, True
        )
        unlabeled = evaluate_vector_preconditions(
            "curl", "uo", "vo", BARE_EVIDENCE, True
        )

        assert all(c["passed"] for c in labeled)
        assert not all(c["passed"] for c in unlabeled)

    def test_every_check_carries_a_repair(self):
        for evidence in (VELOCITY_EVIDENCE, BARE_EVIDENCE):
            for check in evaluate_vector_preconditions(
                "curl", "a", "b", evidence, False
            ):
                assert check["repair"].strip()


class TestValidationPreconditions:
    @pytest.mark.parametrize("key", ["passed", "is_valid"])
    def test_reads_either_result_spelling(self, key):
        assert evaluate_validation_preconditions({key: False})[0]["passed"] is False
        assert evaluate_validation_preconditions({key: True})[0]["passed"] is True

    def test_absent_verdict_is_not_treated_as_failure(self):
        assert evaluate_validation_preconditions({})[0]["passed"] is True


class TestEnforce:
    def test_satisfied_preconditions_return_a_block(self):
        checks = evaluate_vector_preconditions(
            "curl", "uo", "vo", VELOCITY_EVIDENCE, True
        )
        block = enforce("curl", checks, None)

        assert block["status"] == "satisfied"
        assert block["failed_checks"] == []
        assert block["override_used"] is False

    def test_failure_refuses_by_default(self):
        checks = evaluate_vector_preconditions("curl", "a", "b", BARE_EVIDENCE, True)

        with pytest.raises(PreconditionRefusal):
            enforce("curl", checks, None)

    def test_override_token_permits_the_call(self):
        checks = evaluate_vector_preconditions("curl", "a", "b", BARE_EVIDENCE, True)
        block = enforce("curl", checks, OVERRIDE_TOKEN)

        assert block["status"] == "overridden"
        assert block["override_used"] is True
        assert set(block["failed_checks"]) == {"velocity_units", "component_identity"}

    @pytest.mark.parametrize(
        "guess", ["yes", "true", "ok", "acknowledge", OVERRIDE_TOKEN.upper(), ""]
    )
    def test_near_miss_tokens_do_not_unlock_the_result(self, guess):
        checks = evaluate_vector_preconditions("curl", "a", "b", BARE_EVIDENCE, True)

        with pytest.raises(PreconditionRefusal):
            enforce("curl", checks, guess)

    def test_override_on_a_passing_call_is_not_marked_overridden(self):
        checks = evaluate_vector_preconditions(
            "curl", "uo", "vo", VELOCITY_EVIDENCE, True
        )
        block = enforce("curl", checks, OVERRIDE_TOKEN)

        assert block["status"] == "satisfied"
        assert block["override_used"] is False


class TestRefusalPayloadShape:
    """The payload mirrors MCP 2026-07-28 `InputRequiredResult` so that it
    becomes a passthrough once the adapter supports MRTR natively."""

    @pytest.fixture
    def payload(self):
        checks = evaluate_vector_preconditions("curl", "a", "b", BARE_EVIDENCE, False)
        with pytest.raises(PreconditionRefusal) as excinfo:
            enforce("curl", checks, None)
        return excinfo.value.payload

    def test_tagged_as_input_required(self, payload):
        assert payload["result_type"] == RESULT_TYPE_INPUT_REQUIRED

    def test_carries_an_elicitation_input_request(self, payload):
        request = payload["input_requests"]["acknowledge_unverified"]

        assert request["method"] == "elicitation/create"
        assert request["params"]["mode"] == "form"
        assert request["params"]["message"].strip()

    def test_requested_schema_is_flat_per_spec(self, payload):
        schema = payload["input_requests"]["acknowledge_unverified"]["params"][
            "requestedSchema"
        ]

        assert schema["required"] == ["acknowledge"]
        assert schema["properties"]["acknowledge"]["const"] == OVERRIDE_TOKEN
        for prop in schema["properties"].values():
            assert prop["type"] != "object"

    def test_request_state_is_opaque_and_specific_to_the_refusal(self, payload):
        other_checks = evaluate_vector_preconditions(
            "curl", "uo", "vo", VELOCITY_EVIDENCE, False
        )
        with pytest.raises(PreconditionRefusal) as excinfo:
            enforce("curl", other_checks, None)

        assert payload["request_state"] != excinfo.value.payload["request_state"]

    def test_request_state_is_stable_for_the_same_refusal(self, payload):
        checks = evaluate_vector_preconditions("curl", "a", "b", BARE_EVIDENCE, False)
        with pytest.raises(PreconditionRefusal) as excinfo:
            enforce("curl", checks, None)

        assert payload["request_state"] == excinfo.value.payload["request_state"]

    def test_no_computed_number_leaks_into_a_refusal(self, payload):
        assert "stats" not in payload
        assert "value" not in payload

    def test_payload_is_json_serializable(self, payload):
        assert json.loads(json.dumps(payload))["operation"] == "curl"


class TestComparisonPreconditions:
    """``bias``/``rmse`` are built from ``a - b``, which is only a physical
    quantity when both sides are on the same scale."""

    def test_matching_units_pass(self):
        checks = evaluate_comparison_preconditions("tas", "K", "K")

        assert [c["id"] for c in checks] == ["units_comparable"]
        assert checks[0]["passed"]

    def test_kelvin_against_celsius_is_refusable(self):
        """The 273.15 offset reads as model error, which is the whole hazard."""
        checks = evaluate_comparison_preconditions("tas", "K", "degC")

        assert not checks[0]["passed"]
        with pytest.raises(PreconditionRefusal):
            enforce("compare_fields", checks, None)

    @pytest.mark.parametrize(
        ("left", "right"),
        [("K", "kelvin"), ("m/s", "m s-1"), ("degC", "degrees_Celsius"), ("1", "")],
    )
    def test_known_synonyms_are_not_treated_as_a_mismatch(self, left, right):
        assert evaluate_comparison_preconditions("v", left, right)[0]["passed"]

    @pytest.mark.parametrize(
        ("left", "right"), [(None, "K"), ("K", None), (None, None)]
    )
    def test_undeclared_units_abstain_rather_than_refuse(self, left, right):
        """An absent attribute is a gap in the metadata, not evidence that the
        two fields disagree. Comparing unlabeled anomaly fields is ordinary."""
        assert evaluate_comparison_preconditions("v", left, right)[0]["passed"]

    def test_unparsed_equivalents_refuse_and_say_so_in_the_repair(self):
        """We do not do unit algebra, so equivalent-but-unaliased spellings
        refuse. The repair has to name that, or the caller cannot act on it."""
        checks = evaluate_comparison_preconditions("pr", "mm day-1", "kg m-2 s-1")

        assert not checks[0]["passed"]
        assert "unit algebra" in checks[0]["repair"]


class TestNormalizeUnits:
    def test_blank_and_missing_fold_to_none(self):
        for value in (None, "", "   "):
            assert normalize_units(value) is None

    def test_case_and_whitespace_do_not_make_units_differ(self):
        assert normalize_units("  M/S ") == normalize_units("m/s")
