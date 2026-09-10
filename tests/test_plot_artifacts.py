"""A plot result must name a figure that exists.

`plot_dataset` used to answer with `artifacts: [{"type": "plot", "format":
"png", "size_bytes": 41830}]` and no file anywhere: storing the PNG and
inlining it were the same decision, so anything under 256 KB -- which is
nearly every figure -- came back as base64 in the conversation and was
never written. The artifact list said a PNG had been produced, named no
path, and `resources/list` had nothing to serve. Nothing in the suite
touched `_provenance["artifacts"]` for a plot, so the gap was invisible.

These tests run the real tools against a temporary store and hold the
chain together end to end: render, write, describe, list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import UXARRAY_IS_MOCKED

pytestmark = pytest.mark.skipif(
    UXARRAY_IS_MOCKED, reason="rendering a real figure needs a real uxarray"
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the artifact store at a directory this test owns."""
    monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path))
    return tmp_path / "artifacts"


def _provenance_of(blocks):
    """Read the provenance dict out of a plot tool's block list."""
    from uxarray_mcp.content_blocks import block_text

    return json.loads(block_text(blocks[-1]))["_provenance"]


def _plot_artifact(blocks):
    artifacts = _provenance_of(blocks)["artifacts"]
    assert len(artifacts) == 1, f"expected one plot artifact, got {artifacts}"
    return artifacts[0]


def test_a_small_plot_is_still_written_to_the_store(store, synthetic_mesh_with_data):
    """Inline delivery is a payload choice, not a decision to keep nothing."""
    from uxarray_mcp.tools.plotting import _plot_mesh_local

    grid_file, _data_file = synthetic_mesh_with_data
    blocks = _plot_mesh_local(grid_path=grid_file)
    artifact = _plot_artifact(blocks)

    assert artifact["stored"] is True
    written = Path(artifact["path"])
    assert written.exists(), "artifact names a path that was never written"
    assert written.read_bytes().startswith(b"\x89PNG"), "stored file is not a PNG"
    assert written.stat().st_size == artifact["size_bytes"]
    assert artifact["uri"] == written.as_uri()

    # Small enough to inline: the bytes are in the conversation *and* on
    # disk, which is the point -- the caller sees the figure immediately and
    # can still hand the file to something else.
    meta = json.loads(_text_of(blocks))
    assert meta["image_delivery"] == "inline"
    assert meta["image_uri"] == artifact["uri"]


def _text_of(blocks):
    from uxarray_mcp.content_blocks import block_text

    return block_text(blocks[-1])


def test_the_stored_plot_is_what_resources_list_serves(store, synthetic_mesh_with_data):
    """The store the plot writes to is the one the MCP resources read."""
    from uxarray_mcp.resources import list_artifacts, read_artifact
    from uxarray_mcp.tools.plotting import _plot_mesh_local

    grid_file, _data_file = synthetic_mesh_with_data
    blocks = _plot_mesh_local(grid_path=grid_file)
    artifact = _plot_artifact(blocks)

    listed, _cursor = list_artifacts()
    uris = {item["uri"] for item in listed}
    assert artifact["uri"] in uris, (
        "the figure was written where resources/list does not look; "
        f"listed {sorted(uris)}"
    )

    served = read_artifact(artifact["uri"])
    assert served["mimeType"] == "image/png"
    assert Path(artifact["path"]).read_bytes() == __import__("base64").b64decode(
        served["blob"]
    )


def test_a_variable_plot_names_the_variable_it_drew(store, synthetic_mesh_with_data):
    """An artifact for one of several fields has to say which one."""
    from uxarray_mcp.tools.plotting import _plot_variable_local

    grid_file, data_file = synthetic_mesh_with_data
    blocks = _plot_variable_local(
        grid_path=grid_file,
        data_path=data_file,
        variable_name="temperature",
    )
    artifact = _plot_artifact(blocks)
    assert artifact["plot_type"] == "variable_polygons"
    assert artifact["variable"] == "temperature"
    assert Path(artifact["path"]).exists()


def test_an_unwritable_store_says_so_instead_of_going_quiet(
    tmp_path, monkeypatch, synthetic_mesh_with_data
):
    """A figure that could not be kept is reported, not silently dropped.

    The old code returned ``None`` from a bare ``except Exception``, which
    the caller could not tell apart from a figure it had chosen not to
    store. The plot still comes back inline -- losing the picture over a
    read-only directory would be the worse failure -- but the artifact now
    carries the reason.
    """
    from uxarray_mcp.tools.plotting import _plot_mesh_local

    monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path / "state"))

    import uxarray_mcp.typed_results as typed_results

    def _boom(*_args, **_kwargs):
        raise PermissionError("read-only file system")

    grid_file, _data_file = synthetic_mesh_with_data
    monkeypatch.setattr(Path, "write_bytes", _boom)

    blocks = _plot_mesh_local(grid_path=grid_file)
    artifact = _plot_artifact(blocks)

    assert artifact["stored"] is False
    assert "PermissionError" in artifact["not_stored_because"]
    assert "path" not in artifact
    assert json.loads(_text_of(blocks))["image_delivery"] == "inline"
    assert typed_results.store_png  # the helper under test, imported for clarity


def test_analyze_dataset_carries_the_plots_its_stages_drew(
    store, synthetic_mesh_with_data
):
    """A pipeline's provenance lists what its stages produced."""
    from uxarray_mcp.tools.orchestration import analyze_dataset

    grid_file, data_file = synthetic_mesh_with_data
    result = analyze_dataset(
        grid_path=grid_file,
        data_path=data_file,
        include_plots=True,
    )
    artifacts = result["_provenance"]["artifacts"]
    plots = [a for a in artifacts if a.get("type") == "plot"]
    assert plots, "analyze_dataset drew plots and reported none of them"
    for artifact in plots:
        assert artifact["stored"] is True
        assert Path(artifact["path"]).exists()
