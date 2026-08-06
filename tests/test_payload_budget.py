"""Result-size and tool-schema budgets (issue #88).

Everything the server returns is carried forward in the conversation and
re-sent on every later turn, so payload size is paid for repeatedly. These
tests treat result shape as an interface contract: they fail loudly with the
measured number, because knowing what it grew to is the useful part.

The budgets are ratchets, not aspirations -- they sit just above today's
measurements. Tighten them when #83 and #89 land; do not loosen them without
saying why.
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import pytest

from uxarray_mcp.tools.frontdoor import run_analysis

#: Keys that belong to discovery (``get_capabilities``), not to a result.
DISCOVERY_ONLY_KEYS = {
    "mcp_server_tools",
    "uxarray_capabilities",
    "endpoint_profiles",
}

#: Keys that are envelope rather than answer. Everything else counts as signal.
NON_SIGNAL_KEYS = DISCOVERY_ONLY_KEYS | {
    "_provenance",
    "recommended_next_steps",
    "grid_info",
}

#: Upper bound on serialized result bytes, per operation family. Measured
#: values sit roughly 20% below each budget; the slack absorbs the varying
#: length of the temporary file paths echoed back in ``_provenance.inputs``.
RESULT_BYTE_BUDGETS = {
    "inspect_mesh": 1600,
    "calculate_area": 1600,
    "inspect_variable": 2600,
    "calculate_zonal_mean": 2800,
    "validate_dataset": 2600,
}

#: Floor on the fraction of a result that is the computed answer plus status.
#: Measured at 0.20-0.36 today. #83 argues for something closer to 0.5; raise
#: this as the catalog and provenance payload shrink.
SIGNAL_FRACTION_FLOOR = 0.15

#: Upper bound on the serialized core tool specification, sent every request.
TOOL_SPEC_BYTE_BUDGET = 42000

#: Upper bound for the two largest individual tool schemas (#89).
RUN_ANALYSIS_SCHEMA_BUDGET = 6000
GET_CAPABILITIES_SCHEMA_BUDGET = 4200


def _measure(result: dict) -> tuple[int, int, float]:
    total = len(json.dumps(result, default=str))
    signal = sum(
        len(json.dumps({key: value}, default=str))
        for key, value in result.items()
        if key not in NON_SIGNAL_KEYS
    )
    return total, signal, signal / total


@pytest.fixture
def analysis_results(state_dir, structured_mesh_files):
    grid_file, data_file = structured_mesh_files
    calls = {
        "inspect_mesh": {},
        "calculate_area": {},
        "inspect_variable": {"variable_name": "temperature", "data_path": data_file},
        "calculate_zonal_mean": {
            "variable_name": "temperature",
            "data_path": data_file,
        },
        "validate_dataset": {"data_path": data_file},
    }
    results = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for operation, kwargs in calls.items():
            results[operation] = run_analysis(
                operation=operation, grid_path=grid_file, **kwargs
            )
    return results


class TestResultPayloadBudget:
    @pytest.mark.parametrize("operation", sorted(RESULT_BYTE_BUDGETS))
    def test_result_stays_within_byte_budget(self, analysis_results, operation):
        total, _signal, _fraction = _measure(analysis_results[operation])
        budget = RESULT_BYTE_BUDGETS[operation]
        assert total <= budget, (
            f"{operation} result is {total} serialized bytes, over its "
            f"{budget}-byte budget. Shrink the result or justify raising it."
        )

    @pytest.mark.parametrize("operation", sorted(RESULT_BYTE_BUDGETS))
    def test_signal_fraction_stays_above_floor(self, analysis_results, operation):
        total, signal, fraction = _measure(analysis_results[operation])
        assert fraction >= SIGNAL_FRACTION_FLOOR, (
            f"{operation} is only {fraction:.1%} answer "
            f"({signal} of {total} bytes), under the "
            f"{SIGNAL_FRACTION_FLOOR:.0%} floor."
        )

    @pytest.mark.parametrize("operation", sorted(RESULT_BYTE_BUDGETS))
    def test_discovery_keys_never_appear_in_results(self, analysis_results, operation):
        leaked = DISCOVERY_ONLY_KEYS & set(analysis_results[operation])
        assert not leaked, (
            f"{operation} result carries discovery-only keys {sorted(leaked)}; "
            "those belong in get_capabilities, which is called once."
        )


class TestToolSpecBudget:
    @pytest.fixture(scope="class")
    def schemas(self):
        from uxarray_mcp.app import make_registry

        return {
            schema.get("function", schema)["name"]: schema
            for schema in make_registry().get_schemas()
        }

    def test_core_tool_specification_stays_within_budget(self, schemas):
        total = sum(len(json.dumps(schema)) for schema in schemas.values())
        assert total <= TOOL_SPEC_BYTE_BUDGET, (
            f"The core tool specification is {total} serialized bytes, over "
            f"the {TOOL_SPEC_BYTE_BUDGET}-byte budget. This is sent on every "
            "request."
        )

    @pytest.mark.parametrize(
        "name,budget",
        [
            ("run_analysis", RUN_ANALYSIS_SCHEMA_BUDGET),
            ("get_capabilities", GET_CAPABILITIES_SCHEMA_BUDGET),
        ],
    )
    def test_largest_schemas_stay_within_budget(self, schemas, name, budget):
        size = len(json.dumps(schemas[name]))
        assert size <= budget, (
            f"The {name} schema is {size} serialized bytes, over its "
            f"{budget}-byte budget."
        )


def test_measurement_helper_counts_signal_only():
    """Guard the measurement itself, so a budget cannot pass by miscounting."""
    total, signal, fraction = _measure(
        {"total_area": 12.566, "_provenance": {"tool": "x"}}
    )
    assert signal < total
    assert 0.0 < fraction < 1.0
    assert not np.isnan(fraction)
