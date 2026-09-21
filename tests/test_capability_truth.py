"""What the server says it can do has to match what it can do.

Two separate failures motivated these, and both were silent.

``get_capabilities`` is how an agent decides what to attempt. Its remapping
list advertised UXarray's three native methods and omitted YAC's four, so an
agent asking "how should I remap this flux?" was told, in effect, that
conservative remapping does not exist -- while ``run_analysis`` supported it
the whole time. Under-reporting a capability steers work onto the wrong
method without ever raising anything.

The second is version drift. The worker reported its UXarray version but not
its *own*, so a cluster running months-old ``uxarray_mcp`` against a current
``uxarray`` looked healthy while a merged fix was simply not deployed there.
The failure mode is an operation that keeps failing after it was fixed.
"""

from __future__ import annotations

import pytest

from uxarray_mcp.domain.remap_backend import UXARRAY_METHODS, YAC_METHODS
from uxarray_mcp.tools.capabilities import get_capabilities


class TestRemappingIsAdvertisedInFull:
    def test_every_supported_method_appears(self):
        """The list must cover both engines, not just the built-in one."""
        remapping = get_capabilities("healpix:2")["uxarray_capabilities"]["remapping"]
        blob = " ".join(remapping)

        missing = [m for m in UXARRAY_METHODS + YAC_METHODS if m not in blob]
        assert not missing, (
            f"get_capabilities does not mention {missing}; an agent reading "
            "this list would not know those methods exist"
        )

    def test_conservative_is_reachable_as_written(self):
        """The call example has to be the call that works.

        ``conservative`` is not a method on the accessor -- it is reached by
        calling the accessor with ``backend="yac"``. An example showing
        ``var.remap.conservative(...)`` would be advertising an AttributeError,
        and that is exactly the mistake this text exists to prevent.
        """
        remapping = get_capabilities("healpix:2")["uxarray_capabilities"]["remapping"]
        conservative = [line for line in remapping if "conservative" in line]

        assert conservative, "conservative remapping is not advertised at all"
        for line in conservative:
            assert 'backend="yac"' in line, (
                f"{line!r} does not show the backend argument, without which "
                "the call raises AttributeError"
            )
            assert ".remap.conservative(" not in line, (
                f"{line!r} advertises a method that does not exist on the "
                "remap accessor"
            )

    def test_the_yac_methods_say_when_they_are_unreachable(self, monkeypatch):
        """A method that exists but cannot run here must say so.

        Hiding the YAC entries on a machine without the bindings would be
        worse: the caller could not tell "this mesh cannot be remapped
        conservatively" from "this *machine* cannot". So they stay listed and
        carry the reason.
        """
        import uxarray_mcp.tools.capabilities as cap

        monkeypatch.setattr(cap, "_yac_importable", lambda: False)
        absent = get_capabilities("healpix:2")["uxarray_capabilities"]["remapping"]
        assert [line for line in absent if "conservative" in line], (
            "the YAC methods vanished when yac was unimportable; they should "
            "be annotated, not hidden"
        )
        assert all(
            "yac not importable" in line for line in absent if "backend=" in line
        )

        monkeypatch.setattr(cap, "_yac_importable", lambda: True)
        present = get_capabilities("healpix:2")["uxarray_capabilities"]["remapping"]
        assert not any("yac not importable" in line for line in present)

    def test_native_methods_are_not_labelled_as_needing_yac(self):
        """The annotation must not bleed onto UXarray's own methods."""
        remapping = get_capabilities("healpix:2")["uxarray_capabilities"]["remapping"]
        for line in remapping:
            if any(f".remap.{m}(" in line for m in UXARRAY_METHODS):
                assert "yac" not in line.lower(), (
                    f"{line!r} is a native UXarray method but mentions yac"
                )


class TestWorkerReportsItsOwnVersion:
    def test_runtime_probe_carries_the_server_version(self):
        """Not just uxarray's -- the two drift independently."""
        from uxarray_mcp.remote.compute_functions import remote_runtime_probe

        runtime = remote_runtime_probe()["_worker_runtime"]
        assert "mcp_server_version" in runtime, (
            "the worker reports uxarray's version but not the server's, which "
            "is what goes stale when an endpoint is not redeployed"
        )
        assert runtime["mcp_server_version"] not in (None, ""), (
            "an empty version is indistinguishable from a matching one"
        )

    @staticmethod
    async def _warnings_for_worker_version(worker_version):
        """Run the real remote path with a worker reporting ``worker_version``.

        Driving ``_run_on_hpc`` rather than re-deriving the comparison here:
        a test that rebuilds the warning string it is checking would pass even
        if the shipped code never emitted one.
        """
        from unittest.mock import MagicMock, patch

        from uxarray_mcp.remote.agent import UXarrayComputeAgent
        from uxarray_mcp.remote.config import HPCConfig

        future = MagicMock()
        future.result.return_value = {
            "total_area": 1.0,
            "mean_area": 0.5,
            "min_area": 0.1,
            "max_area": 0.9,
            "area_units": "m^2",
            "n_face": 100,
            "_worker_runtime": {
                "hostname": "worker-1",
                "mcp_server_version": worker_version,
            },
        }
        executor = MagicMock()
        executor.submit.return_value = future

        agent = UXarrayComputeAgent(
            HPCConfig(endpoint_id="test-uuid", execution_mode="hpc")
        )
        with patch("globus_compute_sdk.Executor", return_value=executor):
            result = await agent.calculate_area_remote("test.nc", use_remote=True)
        return result["_provenance"].get("warnings") or [], result

    @pytest.mark.asyncio
    async def test_a_stale_worker_produces_a_warning_naming_both_versions(self):
        """The drift has to be reported, not merely recorded.

        A field nobody compares is the same as no field: the real endpoint ran
        server 0.1.0 against 2026.9.0 locally for weeks, with the version
        visible in every response and noticed by nobody.
        """
        from uxarray_mcp.provenance import _get_server_version

        local = _get_server_version()
        assert local != "unknown", "cannot test drift without a local version"

        warnings, result = await self._warnings_for_worker_version("0.1.0")
        drift = [w for w in warnings if "uxarray-mcp version drift" in w]

        assert drift, (
            f"a worker on 0.1.0 against local {local} produced no drift "
            f"warning; got {warnings}"
        )
        assert "0.1.0" in drift[0] and local in drift[0], (
            "the warning must name both versions; 'versions differ' does not "
            f"tell anyone which one to redeploy. Got: {drift[0]}"
        )
        # And the raw fact is inspectable even by a caller that ignores warnings.
        assert result["_provenance"]["remote_mcp_server_version"] == "0.1.0"

    @pytest.mark.asyncio
    async def test_matching_versions_are_silent(self):
        """No warning when the worker is current -- noise trains people to ignore it."""
        from uxarray_mcp.provenance import _get_server_version

        warnings, _ = await self._warnings_for_worker_version(_get_server_version())
        assert not [w for w in warnings if "uxarray-mcp version drift" in w]


class TestCapabilityListsTrackTheData:
    """Empty categories are correct when there is nothing to report.

    Checked because the obvious "fix" -- always populating every category --
    would be a regression: it would advertise vector calculus on a mesh with
    no vector data.
    """

    @pytest.fixture
    def grid_and_field(self, tmp_path):
        np = pytest.importorskip("numpy")
        ux = pytest.importorskip("uxarray")

        grid = ux.Grid.from_healpix(2)
        _ = grid.node_lon, grid.node_lat, grid.face_node_connectivity
        grid_path = tmp_path / "grid.nc"
        grid.to_xarray().to_netcdf(grid_path)

        ds = grid.to_xarray()
        ds["u"] = (("n_face",), np.ones(grid.n_face))
        ds["v"] = (("n_face",), np.ones(grid.n_face))
        data_path = tmp_path / "data.nc"
        ds.to_netcdf(data_path)
        return str(grid_path), str(data_path)

    def test_vector_calculus_is_empty_without_data_and_populated_with_it(
        self, grid_and_field
    ):
        grid_path, data_path = grid_and_field

        bare = get_capabilities(grid_path)["uxarray_capabilities"]
        assert bare["vector_calculus"] == [], (
            "vector calculus was advertised for a mesh with no variables"
        )

        withdata = get_capabilities(grid_path, data_path=data_path)[
            "uxarray_capabilities"
        ]
        assert withdata["vector_calculus"], (
            "two face-centered variables are present but no vector calculus "
            "was advertised"
        )
