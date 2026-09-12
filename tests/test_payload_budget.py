"""Result-size and tool-schema budgets (issue #88).

Everything the server returns is carried forward in the conversation and
re-sent on every later turn, so payload size is paid for repeatedly. These
tests treat result shape as an interface contract: they fail loudly with the
measured number, because knowing what it grew to is the useful part.

The budgets are ratchets, not aspirations -- they sit just above today's
measurements. They were tightened when #83 landed; tighten them again when
#89 lands, and do not loosen them without saying why.
"""

from __future__ import annotations

import json
import pathlib
import warnings

import numpy as np
import pytest

from uxarray_mcp.tools.frontdoor import run_analysis

#: Earth's mean radius, so calculate_area measures its completed payload
#: rather than its refusal.
EARTH_RADIUS_M = 6371000.0

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
#: values sit roughly 15% below each budget; the slack absorbs the varying
#: length of the temporary file paths echoed back in ``_provenance.inputs``.
#: Lowered across the board when #83 removed the caller paths that
#: ``recommended_next_steps`` used to interpolate into every suggestion.
#: Raised from 1150 and 1800 for the ``mesh_coverage`` block (#33): 151
#: bytes on each. Before it, a 5-degree mesh spanning 0-40E/0-40N returned
#: `total_area: 22936016715559.137 m^2` -- 4.4967% of `4*pi*R^2` -- with
#: `physically_interpretable: True`, no warning code, and a bare
#: `postconditions: not_evaluated`, and the identical call on a global mesh
#: returned 1.0000 of the sphere. Nothing in either payload said which was
#: which. The block was trimmed to earn those bytes: the raw steradian sum
#: was dropped (it is `4*pi * sphere_fraction`) and the floats rounded to
#: 1e-6, which is 510 km^2 of sphere and 0.1 m of arc.
RESULT_BYTE_BUDGETS = {
    "inspect_mesh": 1300,
    # Kept above inspect_mesh for the postcondition block (#84/#90): ~440
    # bytes that took correct verification answers from 11/20 to 20/20 in
    # the study, which is the one payload increase we have evidence for.
    # Raised from 1550 for `area_basis` and its precondition (#30): ~200
    # bytes. Before it, a global mesh returned `total_area: 12.566371` --
    # 4*pi steradians -- with `area_units: null` and no warning code, and did
    # so even on a grid whose file declared `sphere_radius: 6371000.0`.
    "calculate_area": 1950,
    "inspect_variable": 1700,
    # Raised from 2050 for the bin-coverage block and its precondition (#23),
    # most of it the repair text. Before it, a regional mesh asked for bands
    # it does not span returned a profile of the requested length and entirely
    # NaN as `outcome: complete` with no warning codes -- shaped exactly like
    # an answer. ~140 bytes to make that state refuse instead.
    "calculate_zonal_mean": 2250,
    "validate_dataset": 2050,
}

#: Floor on the fraction of a result that is the computed answer plus status.
#: Measured at 0.37-0.59 after #83, up from 0.25-0.48 before it. #83 argues
#: for something closer to 0.5 everywhere; the remaining gap is
#: ``_provenance``, which is now the largest key in every result.
SIGNAL_FRACTION_FLOOR = 0.30

#: Upper bound on the serialized core tool specification, sent every request.
#: Measured on the served surface (``RouteTable``), which is 4,263 bytes
#: larger than the ``get_schemas()`` output this used to read. Ratcheted from
#: 42000 after #146 trimmed ``toolcall_reason`` and the Pydantic ``title``
#: annotations: 40748 served bytes before the trim, 35475 after.
TOOL_SPEC_BYTE_BUDGET = 36000

#: Upper bound for the two largest individual tool schemas (#89). Ratcheted
#: from 6000/4200 on the same measurement; ``run_analysis`` alone was 5994
#: served bytes before the trim, six under a budget it was never tested on.
RUN_ANALYSIS_SCHEMA_BUDGET = 5000
GET_CAPABILITIES_SCHEMA_BUDGET = 3500


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
        "calculate_area": {"sphere_radius": EARTH_RADIUS_M},
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
    """Budgets on the specification clients receive, not the one upstream cleans.

    This fixture read ``registry.get_schemas()`` until #146. That is
    ``Tool.get_schema()``'s output -- flattened, gated, and served to
    nobody: every surface we run reaches tools through ``RouteTable``,
    which reads ``tool.parameters`` raw. The budget was therefore measuring
    a schema 4,263 bytes smaller than the wire, and passing.
    """

    @pytest.fixture(scope="class")
    def schemas(self):
        from toolregistry_server.route_table import RouteTable

        from uxarray_mcp.app import make_registry

        return {
            route.tool_name: {
                "name": route.tool_name,
                "description": route.description,
                "parameters": route.parameters_schema,
            }
            for route in RouteTable(make_registry()).list_routes()
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


class TestServedSchemaIsTrimmed:
    """Guard the surface clients actually receive.

    Everything above measures ``registry.get_schemas()``, which runs
    upstream's cleaning and so has always looked tidy. Nothing we serve
    goes through it: ``RouteTable._tool_to_route`` reads ``tool.parameters``
    directly, so the MCP and REST surfaces get the raw dict, uncleaned.
    The gap hid ~2,400 tokens per request -- ``toolcall_reason`` on all 33
    tools for a disabled feature, plus a Pydantic ``title`` on every
    property. ``_trim_wire_schema`` closes it; these tests keep it closed.
    """

    @pytest.fixture(scope="class")
    def routes(self):
        from toolregistry_server.route_table import RouteTable

        from uxarray_mcp.app import make_registry

        return RouteTable(make_registry()).list_routes()

    def test_no_served_tool_advertises_toolcall_reason(self, routes):
        offenders = sorted(
            r.tool_name
            for r in routes
            if "toolcall_reason" in (r.parameters_schema.get("properties") or {})
        )
        assert not offenders, (
            f"{len(offenders)} served tools advertise toolcall_reason: "
            f"{offenders}. Thought-augmented tool calling is off, so this is "
            "schema nobody asked for, re-sent on every request."
        )

    def test_no_served_property_carries_a_title_annotation(self, routes):
        offenders = sorted(
            f"{r.tool_name}.{name}"
            for r in routes
            for name, spec in (r.parameters_schema.get("properties") or {}).items()
            if isinstance(spec, dict) and "title" in spec
        )
        assert not offenders, (
            f"{len(offenders)} served properties carry a Pydantic title "
            f"annotation: {offenders[:5]}. It restates the property name in "
            "title case and no client reads it."
        )

    def test_a_parameter_named_title_survives_the_trim(self, routes):
        """The bug the blanket strip causes, pinned so we never repeat it.

        Upstream's ``get_schema()`` filters the key ``title`` at every
        depth, which deletes ``plot_dataset``'s real ``title`` argument
        along with the annotations -- confirm with
        ``make_registry().get_schemas()``, where it is missing. Our trim
        recurses into property *values* only, so the argument stays.
        """
        plot = next(r for r in routes if r.tool_name == "plot_dataset")
        props = plot.parameters_schema.get("properties") or {}
        assert "title" in props, (
            "plot_dataset lost its `title` argument to the trim. A caller "
            "cannot label a figure it cannot see."
        )
        assert props["title"].get("type") == "string"


def test_measurement_script_reports_the_served_surface():
    """``scripts/measure_payload.py`` must not measure a surface we do not send."""
    source = (
        pathlib.Path(__file__).resolve().parents[1] / "scripts" / "measure_payload.py"
    ).read_text()
    assert "RouteTable" in source, (
        "measure_payload.py still reads get_schemas(); that is upstream's "
        "cleaned schema, not the one RouteTable puts on the wire."
    )


def test_measurement_helper_counts_signal_only():
    """Guard the measurement itself, so a budget cannot pass by miscounting."""
    total, signal, fraction = _measure(
        {"total_area": 12.566, "_provenance": {"tool": "x"}}
    )
    assert signal < total
    assert 0.0 < fraction < 1.0
    assert not np.isnan(fraction)
