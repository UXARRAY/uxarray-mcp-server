"""Opt-in live HPC integration tests for remote remapping.

These tests submit real work to a configured Globus Compute endpoint and are
**skipped by default**. They exist to validate the end-to-end remote remap path
(compute on the worker, compact summary back) against a live cluster — the gap
noted when the remap tools were first added while the endpoint was offline.

Run them explicitly with::

    UXMCP_LIVE_ENDPOINT=chrysalis \\
    UXMCP_LIVE_GRID=/home/jain/uxarray/test/meshfiles/mpas/QU/480/grid.nc \\
    UXMCP_LIVE_DATA=/home/jain/uxarray/test/meshfiles/mpas/QU/480/data.nc \\
    UXMCP_LIVE_TARGET_GRID=/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc \\
    UXMCP_LIVE_VARIABLE=bottomDepth \\
    uv run pytest tests/test_remote_remap_live.py -v

All five environment variables must be set or the module is skipped.
"""

from __future__ import annotations

import os

import pytest

_ENDPOINT = os.environ.get("UXMCP_LIVE_ENDPOINT")
_GRID = os.environ.get("UXMCP_LIVE_GRID")
_DATA = os.environ.get("UXMCP_LIVE_DATA")
_TARGET_GRID = os.environ.get("UXMCP_LIVE_TARGET_GRID")
_VARIABLE = os.environ.get("UXMCP_LIVE_VARIABLE")

pytestmark = pytest.mark.skipif(
    not all([_ENDPOINT, _GRID, _DATA, _TARGET_GRID, _VARIABLE]),
    reason=(
        "live HPC remap test skipped; set UXMCP_LIVE_ENDPOINT, UXMCP_LIVE_GRID, "
        "UXMCP_LIVE_DATA, UXMCP_LIVE_TARGET_GRID, UXMCP_LIVE_VARIABLE to run."
    ),
)


def _assert_remote(result: dict) -> None:
    prov = result["_provenance"]
    assert prov["execution_venue"] == f"hpc:{_ENDPOINT}", prov["execution_venue"]
    # Worker version is recorded for remote runs.
    assert "remote_uxarray_version" in prov


def test_remote_remap_variable_live():
    from uxarray_mcp.tools.advanced import remap_variable

    result = remap_variable(
        target_grid_path=_TARGET_GRID,
        variable_name=_VARIABLE,
        grid_path=_GRID,
        data_path=_DATA,
        method="nearest_neighbor",
        use_remote=True,
        endpoint=_ENDPOINT,
    )
    _assert_remote(result)
    assert result["stats"]["min"] is not None
    assert result["result_shape"]


def test_remote_regrid_dataset_live():
    from uxarray_mcp.tools.advanced import regrid_dataset

    result = regrid_dataset(
        target_grid_path=_TARGET_GRID,
        grid_path=_GRID,
        data_path=_DATA,
        method="nearest_neighbor",
        use_remote=True,
        endpoint=_ENDPOINT,
    )
    _assert_remote(result)
    assert _VARIABLE in result["per_variable_stats"]


def test_remote_remap_to_rectilinear_live():
    from uxarray_mcp.tools.advanced import remap_to_rectilinear

    result = remap_to_rectilinear(
        variable_name=_VARIABLE,
        target_lon=[-90.0, 0.0, 90.0],
        target_lat=[-45.0, 0.0, 45.0],
        grid_path=_GRID,
        data_path=_DATA,
        use_remote=True,
        endpoint=_ENDPOINT,
    )
    _assert_remote(result)
    assert result["target_shape"] == [3, 3]
    # The small rectilinear array is returned and persisted locally.
    assert result["result_handle"]


def test_remote_and_local_agree_on_stats():
    """Remote and local remap_variable produce identical summary statistics
    when both paths are reachable (guards against silent divergence)."""
    from uxarray_mcp.tools.advanced import remap_variable

    remote = remap_variable(
        target_grid_path=_TARGET_GRID,
        variable_name=_VARIABLE,
        grid_path=_GRID,
        data_path=_DATA,
        method="nearest_neighbor",
        use_remote=True,
        endpoint=_ENDPOINT,
    )
    # Local run only if the same paths are readable locally (else skip).
    if not (os.path.exists(_GRID) and os.path.exists(_DATA)):
        pytest.skip("grid/data not readable locally; cannot cross-check stats")
    local = remap_variable(
        target_grid_path=_TARGET_GRID,
        variable_name=_VARIABLE,
        grid_path=_GRID,
        data_path=_DATA,
        method="nearest_neighbor",
    )
    assert remote["stats"]["min"] == pytest.approx(local["stats"]["min"])
    assert remote["stats"]["max"] == pytest.approx(local["stats"]["max"])
