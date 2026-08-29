"""Tests for non-spatial dimension classification.

The bug these exist to prevent: ``time_index`` being applied to *every* extra
dimension, so a caller asking for time step 3 of a multi-level field silently
gets level 3 as well, with nothing in the output saying so.
"""

from uxarray_mcp.domain.dims import classify_dim, face_slice_selection


class TestClassifyDim:
    def test_time_names(self):
        for name in ("time", "Time", "time_counter", "valid_time"):
            assert classify_dim(name) == "time", name

    def test_level_names(self):
        for name in ("lev", "level", "levels", "plev", "z", "nVertLevels"):
            assert classify_dim(name) == "level", name

    def test_unrecognized_is_other(self):
        for name in ("ensemble", "member", "nbnd"):
            assert classify_dim(name) == "other", name


class TestFaceSliceSelection:
    def test_time_index_does_not_leak_onto_level(self):
        """The regression. ``lev`` must take ``level_index``, not ``time_index``."""
        selection, reduced = face_slice_selection(
            {"time": 6, "lev": 8, "n_face": 5400}, time_index=3
        )
        assert selection == {"time": 3, "lev": 0}
        assert reduced["lev"] == {"kind": "level", "index": 0, "size": 8}
        assert reduced["time"] == {"kind": "time", "index": 3, "size": 6}

    def test_level_index_is_honored(self):
        selection, _ = face_slice_selection(
            {"time": 6, "lev": 8, "n_face": 5400}, time_index=3, level_index=5
        )
        assert selection == {"time": 3, "lev": 5}

    def test_face_dims_are_never_collapsed(self):
        for face_dim in ("n_face", "nCells"):
            selection, reduced = face_slice_selection({face_dim: 5400}, time_index=3)
            assert selection == {}
            assert reduced == {}

    def test_size_one_dims_collapse_without_being_reported(self):
        """A length-1 axis loses no information, so it is not a caveat."""
        selection, reduced = face_slice_selection(
            {"time": 1, "n_face": 10}, time_index=3
        )
        assert selection == {"time": 0}
        assert reduced == {}

    def test_unrecognized_dim_takes_index_zero(self):
        selection, reduced = face_slice_selection(
            {"ensemble": 4, "nCells": 99}, time_index=2, level_index=2
        )
        assert selection == {"ensemble": 0}
        assert reduced["ensemble"] == {"kind": "other", "index": 0, "size": 4}

    def test_every_real_collapse_is_reported(self):
        """Whatever gets collapsed must show up in ``reduced`` for provenance."""
        sizes = {"time": 6, "lev": 8, "ensemble": 4, "n_face": 100}
        selection, reduced = face_slice_selection(sizes, time_index=1, level_index=2)
        assert set(reduced) == {"time", "lev", "ensemble"}
        assert {d: r["index"] for d, r in reduced.items()} == selection
