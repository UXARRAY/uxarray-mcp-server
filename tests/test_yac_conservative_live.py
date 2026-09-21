"""A real conservative remap, end to end through ``run_analysis``.

Everything else about YAC in this suite is checked without YAC installed: the
routing rules, the refusal message, the argument plumbing. Those tests pass on
a machine where the conservative remap cannot run at all, which is most of
them, and they would keep passing if the backend were broken.

This is the one that needs the real thing. It builds two overlapping HEALPix
meshes, puts a field on the finer one, and asks the server's own front door to
remap it conservatively onto the coarser one -- the operation the ERA5 case
study measured as the most accurate of six (12.5% lower RMSE than nearest
neighbour, and roughly half the drift in the field's own mean).

Conservative remapping is the only method here that is supposed to preserve
the *areal integral* of the field rather than sample point values, so that is
what is asserted. A nearest-neighbour or bilinear implementation quietly
substituted for the conservative one would fail this, which is the point:
"conservative" naming something non-conservative is exactly the kind of wrong
answer that returns successfully.

Marked ``yac`` rather than guarded with ``importorskip`` so that a machine
without YAC reports a deselection instead of a green skip.

A note on MPI, learned the hard way on a cluster. Importing YAC calls
``MPI_Init``. Open MPI initialises fine as a singleton, which is why this runs
unlaunched on a laptop and in CI. MPICH does not: it aborts with
``PMI_Get_appnum returned -1``, and inside a Globus Compute worker that abort
takes the whole worker down, surfacing as ``WorkerLost`` rather than as
anything mentioning MPI. On an MPICH site, run these under a launcher::

    srun --ntasks 1 python -m pytest tests/ -m yac

``scripts/chrysalis_endpoint.sh check-yac`` already does exactly that, and is
the better entry point there.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.yac


@pytest.fixture
def healpix_pair(tmp_path):
    """A coarse and a fine global mesh, plus a field on the fine one.

    HEALPix cells are equal-area by construction, which makes the integral
    being conserved a plain mean rather than an area-weighted sum -- one less
    thing for the test itself to get wrong.
    """
    ux = pytest.importorskip("uxarray")

    fine = ux.Grid.from_healpix(3)  # 768 cells
    coarse = ux.Grid.from_healpix(2)  # 192 cells

    # A HEALPix grid builds its node coordinates and connectivity lazily, and
    # to_xarray() only emits what has been built -- so a freshly constructed
    # one serialises to face centres alone, which is not a readable mesh.
    # Touching them first is what makes the written file round-trip.
    for g in (fine, coarse):
        _ = g.node_lon, g.node_lat, g.face_node_connectivity

    fine_path = tmp_path / "fine.nc"
    coarse_path = tmp_path / "coarse.nc"
    data_path = tmp_path / "field.nc"

    fine.to_xarray().to_netcdf(fine_path)
    coarse.to_xarray().to_netcdf(coarse_path)

    # A smooth field, so the answer is not dominated by what any one method
    # does at a discontinuity. Latitude-dependent, strictly positive.
    lat = np.asarray(fine.face_lat.values)
    values = 10.0 + 5.0 * np.cos(np.deg2rad(lat))

    ds = fine.to_xarray()
    ds["flux"] = (("n_face",), values, {"units": "W m-2"})
    ds.to_netcdf(data_path)
    del ds

    return {
        "fine_grid": str(fine_path),
        "coarse_grid": str(coarse_path),
        "data": str(data_path),
        "source_mean": float(values.mean()),
        "n_coarse": int(coarse.n_face),
    }


def _remapped_mean(result):
    """The mean of the remapped field, read back off the result handle.

    ``run_analysis`` returns a handle rather than the array, so checking what
    the remap actually produced means resolving it. The stored summary carries
    the mean already; the artifact is opened as well so this is not trusting a
    number the same code path computed.
    """
    import xarray as xr

    from uxarray_mcp.tools.frontdoor import get_result

    handle = get_result(result["result_handle"])
    summarised = handle["summary"]["mean"]
    on_disk = float(xr.open_dataset(handle["artifact_path"])["flux"].values.mean())
    assert summarised == pytest.approx(on_disk, rel=1e-9), (
        "the summary's mean disagrees with the file it summarises: "
        f"{summarised} vs {on_disk}"
    )
    return on_disk


def test_yac_is_actually_importable():
    """Fail loudly if the lane ran without the thing it exists to test."""
    import yac  # noqa: F401


def test_conservative_remap_runs_and_conserves_the_mean(healpix_pair, state_dir):
    """The headline path: conservative remap through the public front door.

    Asserted on the integral rather than on point values, because that is the
    property the method is chosen for. HEALPix cells are equal-area, so the
    integral is the unweighted mean, and a genuinely conservative remap has to
    land close to the source mean. Nearest-neighbour on this field drifts
    several times further.
    """
    from uxarray_mcp.tools.frontdoor import run_analysis

    result = run_analysis(
        "remap_variable",
        grid_path=healpix_pair["fine_grid"],
        data_path=healpix_pair["data"],
        variable_name="flux",
        target_grid_path=healpix_pair["coarse_grid"],
        method="conservative",
    )

    assert result["outcome"] == "complete"

    # It must say it used YAC. A silent fall back to the uxarray engine would
    # otherwise look like a passing conservative remap.
    assert result["backend"] == "yac", (
        f"expected the YAC backend, got {result['backend']!r}; a fallback to "
        "the uxarray engine would otherwise be indistinguishable here"
    )
    assert result["yac_method"] == "conservative"
    assert result["method"] == "yac:conservative"

    remapped_mean = _remapped_mean(result)
    source_mean = healpix_pair["source_mean"]
    drift = abs(remapped_mean - source_mean) / source_mean
    assert drift < 0.02, (
        f"conservative remap moved the field mean by {drift:.2%} "
        f"({source_mean:.4f} -> {remapped_mean:.4f}); that is not conservation"
    )


def test_conservative_beats_nearest_neighbour_on_conservation(
    healpix_pair, state_dir
):
    """The claim that justifies building YAC at all, as a test.

    The ERA5 case study measured conservative as roughly halving the drift in
    the field's mean against nearest neighbour. If that ordering ever inverts,
    either the backend regressed or the case study's recommendation is wrong,
    and both are worth a red build.
    """
    from uxarray_mcp.tools.frontdoor import run_analysis

    def mean_after(method):
        res = run_analysis(
            "remap_variable",
            grid_path=healpix_pair["fine_grid"],
            data_path=healpix_pair["data"],
            variable_name="flux",
            target_grid_path=healpix_pair["coarse_grid"],
            method=method,
        )
        return _remapped_mean(res)

    conservative = mean_after("conservative")
    nearest = mean_after("nearest_neighbor")

    source = healpix_pair["source_mean"]
    drift_conservative = abs(conservative - source)
    drift_nearest = abs(nearest - source)

    assert drift_conservative <= drift_nearest, (
        "conservative remap drifted further from the source mean than nearest "
        f"neighbour did ({drift_conservative:.6f} vs {drift_nearest:.6f}); "
        "the method chosen for flux work is losing to the one that samples "
        "point values"
    )
