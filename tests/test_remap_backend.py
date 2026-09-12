"""Selecting the remap engine: UXarray's own or YAC, from one set of arguments.

Before this, ``run_analysis`` had no way to reach YAC at all -- the
``backend`` argument stopped at the front door -- so conservative remapping,
the one that matters for fluxes, was documented but unreachable. These tests
pin the resolution rules and the places that must agree with them.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from uxarray_mcp.domain.remap_backend import (
    UXARRAY_METHODS,
    YAC_METHODS,
    RemapPlan,
    resolve_remap_plan,
    yac_unavailable_message,
)
from uxarray_mcp.remote import compute_functions as cf
from uxarray_mcp.tools.advanced import _coverage_warnings


class TestResolveRemapPlan:
    def test_default_is_uxarray_nearest_neighbour(self):
        plan = resolve_remap_plan()
        assert plan == RemapPlan("uxarray", "nearest_neighbor", None)
        assert plan.label == "nearest_neighbor"
        assert plan.coverage_method == "nearest_neighbor"

    @pytest.mark.parametrize("method", UXARRAY_METHODS)
    def test_uxarray_methods_stay_on_uxarray(self, method):
        plan = resolve_remap_plan(method=method)
        assert plan.backend == "uxarray"
        assert plan.method == method
        assert plan.yac_method is None

    @pytest.mark.parametrize("method", YAC_METHODS)
    def test_a_yac_method_name_selects_the_yac_backend(self, method):
        """``method="conservative"`` is the natural request; it must route."""
        plan = resolve_remap_plan(method=method)
        assert plan.backend == "yac"
        assert plan.yac_method == method
        assert plan.label == f"yac:{method}"
        assert plan.coverage_method == method

    def test_explicit_backend_defaults_to_nnn(self):
        plan = resolve_remap_plan(backend="yac")
        assert plan.yac_method == "nnn"

    def test_explicit_backend_and_yac_method(self):
        plan = resolve_remap_plan(backend="yac", yac_method="dnn")
        assert plan == RemapPlan("yac", "nearest_neighbor", "dnn")

    def test_case_and_whitespace_are_forgiven(self):
        plan = resolve_remap_plan(method=" Conservative ", backend=" YAC ")
        assert plan.yac_method == "conservative"

    def test_conflicting_method_and_yac_method_refuse(self):
        with pytest.raises(ValueError, match="disagree"):
            resolve_remap_plan(method="conservative", yac_method="nnn")

    def test_yac_method_on_uxarray_backend_refuses_rather_than_ignores(self):
        with pytest.raises(ValueError, match="requires backend='yac'"):
            resolve_remap_plan(method="nearest_neighbor", yac_method="conservative")

    def test_unknown_method_lists_both_engines(self):
        with pytest.raises(ValueError) as excinfo:
            resolve_remap_plan(method="bogus")
        message = str(excinfo.value)
        assert "nearest_neighbor" in message
        assert "conservative" in message

    def test_unknown_backend_refuses(self):
        with pytest.raises(ValueError, match="Unsupported remap backend"):
            resolve_remap_plan(backend="esmf")

    def test_unknown_yac_method_refuses(self):
        with pytest.raises(ValueError, match="Unsupported yac_method"):
            resolve_remap_plan(backend="yac", yac_method="bilinear")

    def test_only_conservative_is_conservative(self):
        from uxarray_mcp.domain.remap_coverage import method_is_conservative

        for method in YAC_METHODS + UXARRAY_METHODS:
            plan = resolve_remap_plan(method=method)
            assert method_is_conservative(plan.coverage_method) is (
                method == "conservative"
            )


class TestCoverageWarningNamesTheMethod:
    """The not-conservative warning once said 'nearest-neighbor' for IDW too."""

    def _coverage(self, method):
        return {
            "n_target_points": 10,
            "points_in_source": 10,
            "method": method,
            "warning_codes": ["REMAP_METHOD_NOT_CONSERVATIVE"],
        }

    @pytest.mark.parametrize(
        "method", ["nearest_neighbor", "inverse_distance_weighted", "nnn", "dnn"]
    )
    def test_message_carries_the_method_used(self, method):
        (message,) = _coverage_warnings(self._coverage(method))
        assert message.startswith(f"REMAP_METHOD_NOT_CONSERVATIVE: {method} ")
        assert "conservative" in message  # points at the fix

    def test_message_without_a_method_still_reads(self):
        coverage = self._coverage(None)
        coverage.pop("method")
        (message,) = _coverage_warnings(coverage)
        assert "nearest-neighbor" not in message


class TestYacUnavailableMessage:
    def test_names_venue_and_both_repairs(self):
        message = yac_unavailable_message("HPC worker")
        assert "HPC worker" in message
        assert "backend='uxarray'" in message
        assert "PYTHONPATH" in message


class TestRemoteInlineMirrorsDomain:
    """The worker copies the resolution rules; they must not drift apart."""

    @pytest.mark.parametrize(
        "function",
        [cf.remote_remap_variable, cf.remote_regrid_dataset],
    )
    def test_method_lists_match(self, function):
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id in (
                    "_YAC_METHODS",
                    "_UX_METHODS",
                ):
                    found[target.id] = tuple(ast.literal_eval(node.value))
        assert found["_YAC_METHODS"] == YAC_METHODS
        assert found["_UX_METHODS"] == UXARRAY_METHODS

    def test_rectilinear_payload_carries_the_yac_methods(self):
        tree = ast.parse(
            textwrap.dedent(inspect.getsource(cf.remote_remap_to_rectilinear))
        )
        yac_lists = [
            tuple(ast.literal_eval(node.value))
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_YAC_METHODS"
        ]
        assert yac_lists == [YAC_METHODS]

    @pytest.mark.parametrize(
        "function",
        [
            cf.remote_remap_variable,
            cf.remote_regrid_dataset,
            cf.remote_remap_to_rectilinear,
        ],
    )
    def test_remote_signatures_accept_backend_and_yac_method(self, function):
        params = inspect.signature(function).parameters
        assert params["backend"].default == "uxarray"
        assert params["yac_method"].default is None


class TestFrontDoorForwardsBackend:
    def test_run_analysis_declares_backend_and_yac_method(self):
        from uxarray_mcp.tools.frontdoor import run_analysis

        params = inspect.signature(run_analysis).parameters
        assert params["backend"].default == "uxarray"
        assert params["yac_method"].default is None

    def test_conservative_without_yac_fails_with_the_repair(
        self, state_dir, comparison_mesh_with_data, remap_target_grid
    ):
        """On a machine without YAC the failure must say what to do."""
        pytest.importorskip("uxarray")
        try:
            import yac.core  # noqa: F401

            pytest.skip("YAC is importable here; the refusal cannot be observed")
        except ImportError:
            pass
        from uxarray_mcp.tools.frontdoor import run_analysis

        grid_file, data_a, _ = comparison_mesh_with_data
        with pytest.raises(RuntimeError, match="backend='uxarray'"):
            run_analysis(
                "remap_variable",
                grid_path=grid_file,
                data_path=data_a,
                variable_name="temperature",
                target_grid_path=remap_target_grid,
                method="conservative",
            )
