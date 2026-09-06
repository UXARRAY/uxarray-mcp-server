"""The declared contract must describe the response we actually send.

``response_contract`` exists so a caller can be told the shape of the
answer before it asks for one (#91). That only helps if the declaration
matches the payload. It did not: the contract advertised a top-level
``physically_interpretable`` boolean, and nothing in the server has ever
emitted one -- every producer nests that verdict inside
``scientific_status``. Measured on four operations, 0 of 4 results carried
the declared field and 4 of 4 carried the block it actually lives in, and
because that block was undeclared, ``validate_response`` reported the
server's own envelope back as *extra* on every call.

These tests compare the declaration against real results rather than
against another declaration, which is the only comparison that would have
caught it.
"""

from __future__ import annotations

import warnings

import pytest

from uxarray_mcp.response_contract import (
    _COMMON_FIELDS,
    available_contracts,
    describe_response_contract,
    validate_response,
)
from uxarray_mcp.tools.frontdoor import run_analysis
from uxarray_mcp.typed_results import _ANALYSIS_ENVELOPE, output_schema_for

#: Envelope blocks every completed result carries.
ENVELOPE_FIELDS = (
    "outcome",
    "scientific_status",
    "preconditions",
    "postconditions",
)


@pytest.fixture
def completed_results(state_dir, earth_radius_mesh_files):
    """One completed result per operation that declares a contract.

    ``earth_radius_mesh_files`` rather than a unit-sphere mesh because
    ``calculate_area`` refuses a grid with no radius to scale by, and a
    refusal is a different shape from the one under test here.
    """
    grid_file, data_file = earth_radius_mesh_files
    calls = {
        "inspect_mesh": {},
        "calculate_area": {},
        "calculate_zonal_mean": {"variable_name": "u", "data_path": data_file},
        "validate_dataset": {"data_path": data_file},
    }
    results = {}
    for operation, kwargs in calls.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results[operation] = run_analysis(
                operation=operation, grid_path=grid_file, **kwargs
            )
    return results


class TestDeclarationMatchesPayload:
    def test_no_common_field_is_declared_that_nothing_emits(self, completed_results):
        """Every declared common field appears in at least one real result.

        A field the contract promises and no code path produces is worse
        than an undocumented one: a caller reads it, looks for it, and
        concludes the server failed to judge.
        """
        seen = set()
        for result in completed_results.values():
            seen.update(result)
        never_emitted = [f["name"] for f in _COMMON_FIELDS if f["name"] not in seen]
        assert never_emitted == [], (
            f"declared but never emitted: {never_emitted}; results carry {sorted(seen)}"
        )

    def test_the_interpretability_verdict_is_declared_where_it_lives(
        self, completed_results
    ):
        """It is inside ``scientific_status``, and only there."""
        for operation, result in completed_results.items():
            assert "physically_interpretable" not in result, operation
            assert "physically_interpretable" in result["scientific_status"], operation

        declared = {f["name"] for f in _COMMON_FIELDS}
        assert "physically_interpretable" not in declared
        assert "scientific_status" in declared

    def test_the_envelope_is_not_reported_back_as_extra(self, completed_results):
        """``extra_fields`` should mean "you added something", not "we did".

        An envelope the server attaches to every reply, listed as an
        unexpected addition by the server's own validator, teaches a
        caller to ignore the field entirely.
        """
        for operation, result in completed_results.items():
            verdict = validate_response(operation, result)
            leaked = [n for n in verdict["extra_fields"] if n in ENVELOPE_FIELDS]
            assert leaked == [], (operation, leaked)
            assert verdict["missing_fields"] == [], operation
            assert verdict["wrong_type"] == [], operation
            assert verdict["valid"] is True, operation


class TestSchemaAgreesWithTheFrontDoor:
    def test_envelope_blocks_reuse_the_front_door_definition(self):
        """One description per field, whichever schema a client reads.

        ``run_analysis`` publishes ``scientific_status`` with a documented
        null ("do not read null as true"). A per-operation schema that
        flattened the same field to a bare object would make the weaker
        promise to any client that happened to read that one instead.
        """
        declared = _ANALYSIS_ENVELOPE["properties"]
        for operation in available_contracts():
            schema = output_schema_for(operation)
            for name in ENVELOPE_FIELDS:
                if name in schema["properties"]:
                    assert schema["properties"][name] == declared[name], (
                        operation,
                        name,
                    )

    def test_the_envelope_stays_optional(self):
        """A refusal carries no ``scientific_status``, so nothing may require it.

        The blocks are promised per branch on the front door's schema --
        required when ``outcome`` is ``complete`` -- and requiring them
        flatly here would declare a shape refusals do not have.
        """
        for operation in available_contracts():
            required = set(describe_response_contract(operation)["required"])
            assert required.isdisjoint(ENVELOPE_FIELDS), operation
