"""Follow-up hints must not echo the caller's own file paths (#83).

``recommended_next_steps`` was 38-46% of some results, and most of those
bytes were the grid and data paths interpolated back into every suggested
call -- paths the caller had just sent in the request. Results are carried
forward in the conversation and re-sent on every later turn, so that waste
is paid repeatedly.

These tests pin the rule rather than the wording: a step may name a tool
and may spell out a value the *server* discovered, but it must never quote
back a filesystem path the caller supplied.
"""

from __future__ import annotations

import warnings

import pytest

from uxarray_mcp.next_steps import call, literal, needed
from uxarray_mcp.tools.frontdoor import run_analysis

#: Operations whose results carry follow-up hints, with the extra arguments
#: each one needs beyond ``grid_path``.
_OPERATIONS = {
    "inspect_mesh": {},
    "calculate_area": {},
    "inspect_variable": {"variable_name": "temperature"},
    "calculate_zonal_mean": {"variable_name": "temperature"},
    "validate_dataset": {},
}


@pytest.fixture
def results(state_dir, structured_mesh_files):
    grid_file, data_file = structured_mesh_files
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for operation, extra in _OPERATIONS.items():
            kwargs = dict(extra)
            if operation != "inspect_mesh" and operation != "calculate_area":
                kwargs["data_path"] = data_file
            out[operation] = (
                run_analysis(operation=operation, grid_path=grid_file, **kwargs),
                grid_file,
                data_file,
            )
    return out


class TestNoPathEcho:
    @pytest.mark.parametrize("operation", sorted(_OPERATIONS))
    def test_steps_never_echo_caller_paths(self, results, operation):
        result, grid_file, data_file = results[operation]
        steps = " ".join(result.get("recommended_next_steps", []))
        for path in (grid_file, data_file):
            assert path not in steps, (
                f"{operation} echoes the caller-supplied path {path!r} back "
                "inside recommended_next_steps. Reference it by parameter "
                "name instead; the caller already knows what it passed."
            )

    @pytest.mark.parametrize("operation", sorted(_OPERATIONS))
    def test_steps_still_name_tools(self, results, operation):
        """Shrinking the field must not empty it: #30's purpose survives."""
        steps = results[operation][0].get("recommended_next_steps", [])
        assert steps, f"{operation} returned no follow-up hints at all"
        assert all(isinstance(step, str) and "(" in step for step in steps), (
            f"{operation} hints should still read as callable suggestions"
        )

    @pytest.mark.parametrize("operation", sorted(_OPERATIONS))
    def test_steps_are_a_small_share_of_the_result(self, results, operation):
        import json

        result = results[operation][0]
        total = len(json.dumps(result, default=str))
        steps = len(json.dumps(result.get("recommended_next_steps", []), default=str))
        assert steps / total <= 0.25, (
            f"{operation} spends {steps / total:.0%} of its payload on "
            f"follow-up hints ({steps} of {total} bytes)."
        )


class TestRenderers:
    def test_caller_supplied_argument_is_a_bare_parameter_name(self):
        assert call("plot_mesh", "grid_path") == "plot_mesh(grid_path)"

    def test_discovered_value_is_quoted(self):
        assert literal("temperature") == '"temperature"'

    def test_missing_argument_is_bracketed(self):
        assert needed("data_path") == "<data_path>"

    def test_keyword_and_note_render(self):
        step = call("subset_bbox", lon_bounds="[-180, 180]", note="focus on a region")
        assert step == "subset_bbox(lon_bounds=[-180, 180]) - focus on a region"

    def test_numeric_literal_is_not_quoted(self):
        assert literal(0.5) == "0.5"
