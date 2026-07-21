"""Regression coverage: `use_remote=True` must never be silently ignored.

`run_analysis` and `plot_dataset` accept `use_remote`/`endpoint` on every
call regardless of `operation`/`plot_type`, but roughly half of the
`run_analysis` operations (and `plot_dataset(plot_type="mesh_geo")`) have no
remote implementation to forward to. Before this test existed, requesting
`use_remote=True` for one of those operations silently ran locally instead --
on a facility-only path (one that does not exist on the caller's machine)
this surfaced as a confusing local `FileNotFoundError` with no indication
that `use_remote` was ever honored. That is exactly the "silent failure"
class of bug this server's provenance/guardrail design otherwise exists to
prevent.

`run_analysis`/`plot_dataset` now raise `ValueError` immediately for these
operations when `use_remote=True` is passed, rather than dispatching locally
without saying so. This file pins that behavior for every affected
operation, and confirms the operations that DO support remote execution are
unaffected (no regression in the other direction).
"""

from __future__ import annotations

import pytest

from uxarray_mcp.tools import plot_dataset, run_analysis

# Operations with no remote implementation -- use_remote=True must raise.
# Kwargs are the minimum needed to reach the use_remote check inside each
# branch (i.e. get past _require() for that operation's own required args).
NO_REMOTE_OPERATIONS = [
    ("validate_dataset", {"grid_path": "g.nc", "data_path": "d.nc"}),
    (
        "subset_bbox",
        {"grid_path": "g.nc", "lon_bounds": [0, 10], "lat_bounds": [0, 10]},
    ),
    (
        "subset_polygon",
        {"grid_path": "g.nc", "polygon_lon_lat": [[0, 0], [1, 0], [1, 1]]},
    ),
    ("cross_section", {"grid_path": "g.nc", "latitude": 0.0}),
    (
        "compare_fields",
        {
            "variable_name": "v",
            "data_path_a": "a.nc",
            "data_path_b": "b.nc",
        },
    ),
    ("bias", {"variable_name": "v", "data_path_a": "a.nc", "data_path_b": "b.nc"}),
    ("rmse", {"variable_name": "v", "data_path_a": "a.nc", "data_path_b": "b.nc"}),
    (
        "pattern_correlation",
        {"variable_name": "v", "data_path_a": "a.nc", "data_path_b": "b.nc"},
    ),
    ("temporal_mean", {"data_path": "d.nc", "variable_name": "v"}),
    ("anomaly", {"data_path": "d.nc", "variable_name": "v"}),
    ("ensemble_mean", {"variable_name": "v", "data_paths": ["a.nc", "b.nc"]}),
    ("ensemble_spread", {"variable_name": "v", "data_paths": ["a.nc", "b.nc"]}),
    ("export", {"output_path": "out.nc"}),
]

# Operations that DO support use_remote -- must NOT raise ValueError for
# use_remote itself (they should fail later, e.g. on the missing/fake file,
# never on "unsupported operation").
REMOTE_CAPABLE_OPERATIONS = [
    ("inspect_mesh", {"grid_path": "healpix:2"}),
    ("calculate_area", {"grid_path": "healpix:2"}),
]


class TestRunAnalysisRejectsUnsupportedRemote:
    @pytest.mark.parametrize("operation,kwargs", NO_REMOTE_OPERATIONS)
    def test_raises_immediately_on_use_remote(self, operation, kwargs):
        with pytest.raises(ValueError, match="does not support use_remote=True"):
            run_analysis(
                operation=operation, use_remote=True, endpoint="whatever", **kwargs
            )

    @pytest.mark.parametrize("operation,kwargs", NO_REMOTE_OPERATIONS)
    def test_local_call_unaffected(self, operation, kwargs):
        """use_remote defaults to False -- these operations still run (and
        fail on missing test fixtures, not on rejecting use_remote)."""
        with pytest.raises(Exception) as exc_info:
            run_analysis(operation=operation, **kwargs)
        assert "does not support use_remote=True" not in str(exc_info.value)


class TestRunAnalysisRemoteCapableOperationsUnaffected:
    @pytest.mark.parametrize("operation,kwargs", REMOTE_CAPABLE_OPERATIONS)
    def test_use_remote_does_not_raise_unsupported_error(
        self, operation, kwargs, tmp_path, monkeypatch
    ):
        """These operations forward use_remote; with no endpoint configured
        they fall back to local execution rather than raising our new
        "unsupported" error (the whole point is they DO support it). Point
        config discovery at an empty scratch file so this is deterministic
        regardless of what endpoints happen to be configured on the machine
        running the test.
        """
        empty_config = tmp_path / "config.yaml"
        empty_config.write_text("hpc:\n  execution_mode: auto\n", encoding="utf-8")
        monkeypatch.setenv("UXARRAY_MCP_CONFIG", str(empty_config))

        result = run_analysis(operation=operation, use_remote=True, **kwargs)
        assert result["_provenance"]["execution_venue"] == "local"


def test_plot_dataset_mesh_geo_rejects_use_remote():
    with pytest.raises(ValueError, match="does not support use_remote=True"):
        plot_dataset(
            plot_type="mesh_geo", grid_path="g.nc", use_remote=True, endpoint="whatever"
        )


def test_plot_dataset_mesh_accepts_use_remote_without_unsupported_error():
    """`mesh` supports remote; with no endpoint it falls back locally."""
    items = plot_dataset(plot_type="mesh", grid_path="healpix:2", use_remote=True)
    assert items  # returns MCP content blocks, not our ValueError
