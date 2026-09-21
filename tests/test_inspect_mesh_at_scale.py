"""A topology summary must not compute the expensive parts of the topology.

``inspect_mesh`` on the 63 GB CONUS-RRM np4 grid killed the Globus worker.
The caller saw ``WorkerLost``, which names neither memory nor a line of code,
and the obvious reading -- that the large-SCRIP lazy-open fix had not been
deployed -- was wrong: the worker had it.

What actually happened is that the summary asked for more than the caller
did. Reading ``n_face`` and ``n_node`` costs about 118 GiB on that mesh, which
fits. But the reply also carried ``n_edge``, which builds the entire
``edge_node_connectivity`` when the file does not store one, and
``mesh_coverage.sphere_fraction``, which sums an area computed per face from
all 3.6 billion corners. Neither was guarded, and together they exceed the
node's 235 GiB.

The closure check in the same function was already capped at 250,000 faces
and reported as skipped. These tests hold the other two to that same rule:
skip the work, and *say* the field was skipped rather than return a partial
answer that looks complete.

The mesh here is a real HEALPix grid wearing a proxy that reports 300M faces
and raises if the expensive properties are touched -- so the test asserts the
work was not merely tolerable but genuinely not done, without needing a
multi-GB file or a big machine.
"""

from __future__ import annotations

import pytest

from uxarray_mcp.remote import compute_functions as cf

#: The cap the closure check and ``n_edge`` use.
MAX_FACES = 250_000

#: Summing face areas is vectorized, so it survives two orders of magnitude
#: longer than the closure loop. Mirrors AREA_MAX_FACES in
#: domain/mesh_coverage.py. The 300M-face mesh here is above both.
MAX_AREA_FACES = 50_000_000


class _RefusesExpensiveWork:
    """Reports a huge ``n_face``; explodes on the properties that would OOM."""

    n_face = 299_999_162

    def __init__(self, real):
        object.__setattr__(self, "_real", real)

    @property
    def n_node(self):
        return self._real.n_node

    @property
    def n_edge(self):
        raise AssertionError(
            "n_edge was computed on a 300M-face mesh; on the real grid this "
            "builds edge_node_connectivity and kills the worker"
        )

    @property
    def face_areas(self):
        raise AssertionError(
            "face_areas was computed on a 300M-face mesh; on the real grid "
            "this is 3.6 billion corners of work and kills the worker"
        )

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_real"), name)


@pytest.fixture
def huge_mesh(monkeypatch):
    ux = pytest.importorskip("uxarray")
    real = ux.Grid.from_healpix(2)
    monkeypatch.setattr(
        ux.Grid,
        "from_healpix",
        staticmethod(lambda *a, **k: _RefusesExpensiveWork(real)),
    )
    return "healpix:2"


class TestTheSummaryStaysAffordable:
    def test_inspect_mesh_returns_at_all(self, huge_mesh):
        """The whole point: a summary of a huge mesh has to come back."""
        result = cf.remote_inspect_mesh(huge_mesh)
        assert result["n_face"] == 299_999_162
        assert result["n_node"] > 0

    def test_the_skipped_fields_say_they_were_skipped(self, huge_mesh):
        """A partial answer must not be shaped like a complete one.

        Silently dropping ``n_edge`` would leave a caller unable to tell "this
        mesh has no edges" from "we declined to count them", which is the
        under-reporting failure this server has been bitten by before.
        """
        result = cf.remote_inspect_mesh(huge_mesh)

        assert result["n_edge"] is None
        assert str(MAX_FACES) in result["n_edge_skipped"]
        assert "299999162" in result["n_edge_skipped"]

        coverage = result["mesh_coverage"]
        assert coverage["sphere_fraction"] is None
        assert str(MAX_AREA_FACES) in coverage["sphere_fraction_skipped"]
        assert coverage["topology_skipped"]

    def test_cheap_fields_are_still_answered(self, huge_mesh):
        """Skipping the expensive parts must not skip the rest.

        ``lon_extent``/``lat_extent`` read node coordinates that are already
        resident, so they cost nothing extra and remain part of the answer.
        """
        coverage = cf.remote_inspect_mesh(huge_mesh)["mesh_coverage"]
        assert coverage["lon_extent"] is not None
        assert coverage["lat_extent"] is not None


class TestSmallMeshesAreUnaffected:
    """The guards must not cost a real answer on a mesh that can afford one."""

    def test_a_small_mesh_still_reports_everything(self):
        result = cf.remote_inspect_mesh("healpix:2")

        assert result["n_edge"] == 384
        assert "n_edge_skipped" not in result

        coverage = result["mesh_coverage"]
        assert coverage["sphere_fraction"] == pytest.approx(1.0)
        assert coverage["closed"] is True
        assert coverage["euler_characteristic"] == 2
        assert "sphere_fraction_skipped" not in coverage
        assert coverage.get("topology_skipped") is None


class TestSubsetCostsTheCropNotTheMesh:
    """A regional crop must not price itself against the whole globe.

    ``subset_bbox`` computed the mean face area of the *entire* mesh before
    subsetting, purely to express the crop's resolution as a ratio. On the
    300M-face np4 grid that killed the worker at ~400 s -- the caller asked
    for Texas and paid for the planet, then got nothing.

    The subset now happens first, and the whole-mesh statistic is skipped and
    reported above the same 50M-face cap the area sum uses elsewhere.

    The huge-mesh case is not asserted here: the proxy that fakes an enormous
    ``n_face`` cannot also satisfy uxarray's subsetting internals, which
    divide by the real face count. Faking that convincingly would mean
    reimplementing the grid, and a test whose fixture is a reimplementation
    tests the fixture. What *is* pinned below is the order of operations,
    which is the thing that was wrong.
    """

    def test_the_full_mesh_area_is_computed_after_the_subset(self):
        """Order of operations, read off the source.

        Cheap and exact: if the whole-mesh ``face_areas`` scan ever moves back
        above ``subset.bounding_box``, a crop of a mesh too large to measure
        dies again before it starts.
        """
        import inspect

        src = inspect.getsource(cf.remote_subset_bbox_plot)
        subset_at = src.index("grid.subset.bounding_box")
        full_area_at = src.index("full_areas = grid.face_areas")
        assert subset_at < full_area_at, (
            "the whole-mesh face_areas scan runs before the subset; on a "
            "300M-face mesh that kills the worker before the crop is attempted"
        )

    def test_the_whole_mesh_scan_is_capped(self):
        """And the cap is the same one used elsewhere, not a new number."""
        import inspect

        src = inspect.getsource(cf.remote_subset_bbox_plot)
        assert "_MAX_AREA_FACES = 50_000_000" in src
        assert "mean_area_full_skipped" in src

    def test_a_small_mesh_still_reports_the_ratio(self):
        """The statistic is worth keeping where it is affordable."""
        result = cf.remote_subset_bbox_plot(
            "healpix:3", [-30, 30], [-20, 20], width=200, height=150
        )
        assert result["mean_area_full_sr"] is not None
        assert result["mean_area_full_skipped"] is None
        assert result["resolution_ratio"] is not None
