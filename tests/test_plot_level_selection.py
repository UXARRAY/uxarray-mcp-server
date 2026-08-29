"""``plot_variable`` must be able to reach a level, and must say which one.

Two defects motivate this file. First, ``level_index`` existed in the domain
renderer but was reachable from no tool, so every plot of a multi-level field
was pinned to level 0 with no way to ask for another. Second, the reduction
metadata computed by ``_plot_variable_local`` was dropped on the way out of
``remote_tools.plot_variable``, so even the pinned choice was invisible: a
caller looking at a PNG of level 0 of a 4-level field had nothing telling
them the other three existed.
"""

from __future__ import annotations

import json

import pytest

from uxarray_mcp.content_blocks import block_text
from uxarray_mcp.tools.frontdoor import plot_dataset


def _meta(items) -> dict:
    """Return the JSON metadata block that accompanies the rendered image."""
    return json.loads(block_text(items[-1]) or "{}")


def _png(items) -> bytes:
    import base64

    block = items[0]
    data = getattr(block, "data", None)
    if data is None and isinstance(block, dict):
        data = block.get("source", {}).get("data") or block.get("data")
    assert data, f"no image payload in {block!r}"
    return base64.b64decode(data)


class TestPlotVariableLevelSelection:
    def test_level_index_changes_the_image(self, multi_level_mesh_files):
        """Levels are 100/200/300/400, so a different level is a different PNG.

        Comparing bytes is coarse but it is the property that actually
        matters: if ``level_index`` were still ignored, both renders would be
        byte-identical no matter what was asked for.
        """
        grid_file, data_file = multi_level_mesh_files
        first = plot_dataset(
            plot_type="variable",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
            level_index=0,
        )
        third = plot_dataset(
            plot_type="variable",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
            level_index=2,
        )
        assert _png(first) != _png(third)

    def test_the_drawn_slice_is_disclosed(self, multi_level_mesh_files):
        """``reduced_dims`` is the only record of which level the PNG shows."""
        grid_file, data_file = multi_level_mesh_files
        items = plot_dataset(
            plot_type="variable",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
            level_index=2,
        )
        reduced = _meta(items)["reduced_dims"]
        assert reduced["n_level"] == {"kind": "level", "index": 2, "size": 4}

    def test_time_index_does_not_move_the_level(self, time_level_mesh_files):
        """The original bug: one selector was applied to every extra axis."""
        grid_file, data_file = time_level_mesh_files
        items = plot_dataset(
            plot_type="variable",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
            time_index=2,
        )
        reduced = _meta(items)["reduced_dims"]
        assert reduced["time"] == {"kind": "time", "index": 2, "size": 3}
        assert reduced["n_level"] == {"kind": "level", "index": 0, "size": 4}

    def test_worker_selects_the_same_slice_as_local(self, time_level_mesh_files):
        """The worker copy is inlined by hand and can drift from the local one.

        Globus Compute serializes each function body standalone, so
        ``remote_plot_variable`` cannot import the shared helper. Divergence
        here means the same request answers differently depending on where it
        ran, which is the worst kind to debug.
        """
        from uxarray_mcp.remote.compute_functions import remote_plot_variable

        grid_file, data_file = time_level_mesh_files
        local = plot_dataset(
            plot_type="variable",
            grid_path=grid_file,
            data_path=data_file,
            variable_name="temperature",
            time_index=2,
            level_index=1,
        )
        remote = remote_plot_variable(
            grid_file,
            data_file,
            "temperature",
            800,
            400,
            "viridis",
            None,
            None,
            None,
            2,
            1,
        )
        assert remote["reduced_dims"] == _meta(local)["reduced_dims"]


class TestVerticalDimensionSpellings:
    """``n_level`` is this project's own fixture spelling, and it was missed.

    An exact-name list cannot keep up with how models name a vertical axis,
    and every name it misses is one ``level_index`` silently cannot reach.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "n_level",
            "nlev",
            "num_levels",
            "nVertLevels",
            "depth",
            "height_above_ground",
        ],
    )
    def test_spelling_is_classified_as_level(self, name):
        from uxarray_mcp.domain.dims import classify_dim

        assert classify_dim(name) == "level"
