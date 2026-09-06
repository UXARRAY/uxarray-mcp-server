"""Non-finite floats must not reach the wire (#31).

``NaN`` and ``Infinity`` are Python's, not JSON's. ``json.dumps`` writes
them as bare tokens anyway unless told otherwise, and the MCP adapter does
not even route ``structuredContent`` through ``json.dumps`` -- the live
dict goes to pydantic. So nothing between a tool's ``return`` and the
client's decoder was rejecting them.

The measurement that motivated this: a zonal mean over the masked field in
``masked_mesh_files`` returns 19 latitude bands, every one of them ``NaN``,
and ``json.dumps(result, allow_nan=False)`` on that result raises ``Out of
range float values are not JSON compliant: nan``. A strict client loses the
whole response, provenance and all, over those bands.

(That *every* band is undefined -- not only the masked southern ones -- is
upstream zonal-mean behavior, not something this module decides. It is
recorded here because it is the measured input, not because it is right.)
"""

from __future__ import annotations

import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from uxarray_mcp.json_safe import json_safe, json_text
from uxarray_mcp.preconditions import OVERRIDE_TOKEN
from uxarray_mcp.registry import build_registry


def _strict_loads(text: str) -> object:
    """Parse ``text``, refusing the three tokens JSON does not define.

    ``json.loads`` accepts ``NaN``/``Infinity``/``-Infinity`` by default,
    so a plain round-trip would pass on a payload that a conforming
    decoder in another language rejects.
    """

    def reject(constant: str) -> object:
        raise AssertionError(f"payload carries the non-JSON token {constant!r}")

    return json.loads(text, parse_constant=reject)


def _non_finite(obj: object, path: str = "") -> list[str]:
    """Every path in ``obj`` holding a float JSON cannot represent."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return [f"{path} = {obj}"]
    if isinstance(obj, dict):
        return [hit for k, v in obj.items() for hit in _non_finite(v, f"{path}.{k}")]
    if isinstance(obj, (list, tuple)):
        return [
            hit for i, v in enumerate(obj) for hit in _non_finite(v, f"{path}[{i}]")
        ]
    return []


class TestJsonSafe:
    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_floats_become_null(self, value):
        assert json_safe(value) is None

    def test_finite_floats_are_untouched(self):
        assert json_safe(-0.5) == -0.5
        assert json_safe(0.0) == 0.0

    def test_numpy_scalars_and_arrays_are_unwrapped_and_cleaned(self):
        assert json_safe(np.float64("nan")) is None
        assert json_safe(np.float32(2.5)) == pytest.approx(2.5)
        assert json_safe(np.int64(7)) == 7
        assert json_safe(np.array([1.0, np.nan, np.inf])) == [1.0, None, None]

    def test_nesting_is_reached(self):
        payload = {"a": [{"b": (float("nan"), 1.0)}], "c": {"d": float("inf")}}
        assert json_safe(payload) == {"a": [{"b": [None, 1.0]}], "c": {"d": None}}

    def test_booleans_stay_booleans(self):
        """``isinstance(True, int)`` is True; a bool must not become 1."""
        cleaned = json_safe({"passed": True, "failed": False, "count": 1})
        assert cleaned["passed"] is True
        assert cleaned["failed"] is False
        assert cleaned["count"] == 1

    def test_paths_and_datetimes_become_strings(self):
        stamp = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
        cleaned = json_safe({"file": Path("/tmp/mesh.nc"), "at": stamp})
        assert cleaned["file"] == "/tmp/mesh.nc"
        assert cleaned["at"] == stamp.isoformat()

    def test_keys_are_stringified(self):
        assert json_safe({1: "a", None: "b"}) == {"1": "a", "None": "b"}

    def test_unknown_objects_pass_through_untouched(self):
        """Content blocks and other opaque objects must not be rebuilt."""
        sentinel = object()
        assert json_safe(sentinel) is sentinel

    def test_json_text_is_strictly_parseable(self):
        text = json_text({"values": [float("nan"), 1.0], "n": np.int64(2)})
        assert _strict_loads(text) == {"values": [None, 1.0], "n": 2}


class TestWireBoundary:
    """The registry is where a tool result becomes a response."""

    def test_every_registered_tool_is_wrapped(self):
        registry = build_registry(profile="deferred-full")
        unwrapped = [
            name
            for name in registry.list_tools()
            if not getattr(
                getattr(registry.get_tool(name).callable, "fn", None),
                "_uxarray_mcp_wire_safe",
                False,
            )
        ]
        assert unwrapped == [], (
            f"{len(unwrapped)} tools return unsanitized results: {unwrapped[:5]}"
        )

    def test_wrapping_does_not_cost_a_parameter_schema(self):
        """The wrapper goes on after registration, and this is why (#31).

        Handing the wrapper to ``register()`` instead looked equivalent.
        It is not: parameter schemas come from ``get_type_hints``, which
        resolves annotations in the function's own ``__globals__``, and
        ``functools.wraps`` cannot carry those across. Registering the
        wrapper dropped 28 parameters across this surface to an
        unconstrained schema, silently.
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            registry = build_registry(profile="deferred-full")
        schema_warnings = [
            str(w.message)
            for w in caught
            if "cannot be represented in JSON Schema" in str(w.message)
        ]
        assert schema_warnings == []
        properties = registry.get_tool("run_analysis").parameters["properties"]
        assert "operation" in properties
        assert properties["grid_path"].get("type") is not None

    def test_a_masked_zonal_mean_survives_a_strict_decoder(
        self, state_dir, masked_mesh_files
    ):
        """The measured case: 19 undefined bands used to poison the payload.

        Whether a band *should* be undefined is a separate question from
        how an undefined one is written; this test is only about the
        second. It asserts ``None in``, not all-``None``, so that fixing
        the first does not fail it.

        The override is needed because the bin-coverage gate (#23) refuses
        this call on its own -- which is the right answer for a caller who
        did not ask for it, and the wrong shape for testing what a
        completed result serializes to.
        """
        grid_file, data_file = masked_mesh_files
        tool = build_registry(profile="core").get_tool("run_analysis")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = tool.callable.call_sync(
                operation="calculate_zonal_mean",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="salinity",
                acknowledge=OVERRIDE_TOKEN,
            )

        assert result["outcome"] == "complete"
        # The undefined bands are still reported, as null rather than NaN:
        # dropping them would silently shorten a profile the contract says
        # is the same length as `latitudes`.
        assert None in result["zonal_mean_values"]
        assert len(result["zonal_mean_values"]) == len(result["latitudes"])
        assert _non_finite(result) == []
        _strict_loads(json.dumps(result, allow_nan=False))

    def test_the_front_door_alone_does_not_promise_this(
        self, state_dir, masked_mesh_files
    ):
        """Pins where the boundary is, so it cannot drift without notice.

        ``run_analysis`` called as a Python function still returns NaN --
        that is the honest value of an undefined band, and in-process
        callers can tell it from a missing one. The conversion belongs at
        the point where the result becomes JSON, and nowhere earlier. If
        this test starts failing because the front door sanitizes too,
        that is a decision to make deliberately, not to discover.
        """
        from uxarray_mcp.tools.frontdoor import run_analysis

        grid_file, data_file = masked_mesh_files
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = run_analysis(
                operation="calculate_zonal_mean",
                grid_path=grid_file,
                data_path=data_file,
                variable_name="salinity",
                acknowledge=OVERRIDE_TOKEN,
            )
        assert _non_finite(result) != []
