"""Rebuilding a remote rectilinear remap when the variable has a time axis.

``remap_to_rectilinear`` returns the remapped array as nested lists and the
submitter rebuilds a ``DataArray`` from them. That reconstruction used a
hardcoded ``dims=("lat", "lon")``, which is only right for a variable with no
other dimensions.

Ordinary model output is not like that. DYAMOND 30km ``olrtoa`` carries
``time``, so the worker returns ``('time', 'lat', 'lon')`` with shape
``(1, 3, 3)`` and the rebuild died with::

    ValueError: different number of dimensions on data and dims: 3 vs 2

Found against real data on NCAR Casper, not in a fixture. These tests drive
the reconstruction directly with a fake agent, so they cover the shape logic
without needing a cluster.
"""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def remote_rectilinear(monkeypatch):
    """Run ``remap_to_rectilinear`` with the HPC call replaced by a canned reply.

    Returns a callable taking the worker payload, so each test states the
    shape the worker produced and nothing else.
    """
    from uxarray_mcp.tools import advanced

    def run(worker_payload: dict):
        payload = dict(worker_payload)
        payload.setdefault("variable_name", "olrtoa")
        payload.setdefault("backend", "uxarray")
        payload.setdefault("method", "nearest_neighbor")
        payload.setdefault("yac_method", None)
        payload.setdefault("stats", {"min": 1.0, "max": 2.0, "mean": 1.5})
        payload.setdefault("source_coverage", None)
        payload["_provenance"] = {
            "execution_venue": "hpc:test",
            "warnings": [],
            "tool": "remote_remap_to_rectilinear",
        }

        class _Agent:
            config = type("C", (), {"endpoint_name": "test", "endpoint_id": "x"})()

            async def _run_on_hpc(self, *_a, **_k):
                return payload

        # remap_to_rectilinear imports these inside the function, so the
        # patch has to land on the defining modules rather than on `advanced`.
        from uxarray_mcp.remote import agent as agent_module
        from uxarray_mcp.tools import remote_tools

        monkeypatch.setattr(agent_module, "get_agent", lambda **_k: _Agent())
        monkeypatch.setattr(
            remote_tools, "_endpoint_manager_is_up", lambda _a: (True, "")
        )
        monkeypatch.setattr(
            remote_tools, "_path_is_locally_reachable", lambda _p: False
        )

        return advanced.remap_to_rectilinear(
            variable_name="olrtoa",
            target_lon=[-90.0, 0.0, 90.0],
            target_lat=[-45.0, 0.0, 45.0],
            grid_path="/remote/grid.nc",
            data_path="/remote/data.nc",
            use_remote=True,
            endpoint="test",
        )

    return run


def _handle_dataset(result):
    import xarray as xr

    from uxarray_mcp.tools.frontdoor import get_result

    handle = get_result(result["result_handle"])
    return xr.open_dataset(handle["artifact_path"])


class TestAVariableWithATimeAxis:
    """The case that failed on real data."""

    def test_a_three_dimensional_result_is_rebuilt(self, remote_rectilinear, state_dir):
        values = np.arange(9, dtype=float).reshape(1, 3, 3)

        result = remote_rectilinear(
            {
                "values": values.tolist(),
                "target_lon": [-90.0, 0.0, 90.0],
                "target_lat": [-45.0, 0.0, 45.0],
                "result_dims": ["time", "lat", "lon"],
                "result_coords": {"time": [0.0]},
            }
        )

        assert result["result_handle"]
        with _handle_dataset(result) as ds:
            assert ds["olrtoa"].dims == ("time", "lat", "lon")
            assert ds["olrtoa"].shape == (1, 3, 3)

    def test_the_leading_coordinate_is_preserved(self, remote_rectilinear, state_dir):
        """A time value the worker knows should not be thrown away."""
        result = remote_rectilinear(
            {
                "values": np.zeros((2, 3, 3)).tolist(),
                "target_lon": [-90.0, 0.0, 90.0],
                "target_lat": [-45.0, 0.0, 45.0],
                "result_dims": ["time", "lat", "lon"],
                "result_coords": {"time": [10.0, 20.0]},
            }
        )

        with _handle_dataset(result) as ds:
            assert list(ds["olrtoa"].coords["time"].values) == [10.0, 20.0]


class TestTheOrdinaryTwoDimensionalCase:
    def test_a_plain_lat_lon_result_still_works(self, remote_rectilinear, state_dir):
        result = remote_rectilinear(
            {
                "values": np.ones((3, 3)).tolist(),
                "target_lon": [-90.0, 0.0, 90.0],
                "target_lat": [-45.0, 0.0, 45.0],
                "result_dims": ["lat", "lon"],
                "result_coords": {},
            }
        )

        with _handle_dataset(result) as ds:
            assert ds["olrtoa"].dims == ("lat", "lon")


class TestAWorkerThatDoesNotReportDims:
    """Older workers predate ``result_dims`` and must still be usable.

    The cluster is updated separately from the submitter and is routinely
    behind -- that is what the version-drift warning exists to report. A fix
    that only works once every worker is current would not have fixed the
    failure that prompted it.
    """

    def test_a_two_dimensional_payload_is_inferred(self, remote_rectilinear, state_dir):
        result = remote_rectilinear(
            {
                "values": np.ones((3, 3)).tolist(),
                "target_lon": [-90.0, 0.0, 90.0],
                "target_lat": [-45.0, 0.0, 45.0],
            }
        )

        with _handle_dataset(result) as ds:
            assert ds["olrtoa"].dims == ("lat", "lon")

    def test_a_three_dimensional_payload_gets_a_positional_name(
        self, remote_rectilinear, state_dir
    ):
        """Unnamed beats unusable: the array survives, the axis is dim_0."""
        result = remote_rectilinear(
            {
                "values": np.zeros((1, 3, 3)).tolist(),
                "target_lon": [-90.0, 0.0, 90.0],
                "target_lat": [-45.0, 0.0, 45.0],
            }
        )

        with _handle_dataset(result) as ds:
            assert ds["olrtoa"].dims == ("dim_0", "lat", "lon")
            assert ds["olrtoa"].shape == (1, 3, 3)

    def test_a_mismatched_dims_list_is_ignored_rather_than_trusted(
        self, remote_rectilinear, state_dir
    ):
        """Dims that do not match the array are worse than no dims at all."""
        result = remote_rectilinear(
            {
                "values": np.zeros((1, 3, 3)).tolist(),
                "target_lon": [-90.0, 0.0, 90.0],
                "target_lat": [-45.0, 0.0, 45.0],
                "result_dims": ["lat", "lon"],
            }
        )

        with _handle_dataset(result) as ds:
            assert ds["olrtoa"].shape == (1, 3, 3)
