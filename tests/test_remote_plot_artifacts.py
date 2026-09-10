"""A figure rendered on HPC has to survive the conversation that showed it.

`tests/test_plot_artifacts.py` holds the local render/write/describe/list
chain together. The remote path never entered it: a worker returns
``png_b64`` and nothing else, so `_provenance["artifacts"]` came back empty
and no file was written anywhere. Plotting the 128k-face CONUS mesh on
Chrysalis produced 1,096,863 bytes of PNG that existed only inline --
minutes of cluster time on a mesh too large to copy down, with no path,
no URI, and nothing for `resources/list` to serve.

The venue that most needs a durable artifact was the one that had none.
These tests drive `_ensure_plot_artifact` with worker-shaped results, so
they need no endpoint and no real render.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from uxarray_mcp.tools.remote_tools import _ensure_plot_artifact

PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the artifact store at a directory this test owns."""
    monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path))
    return tmp_path / "artifacts"


def _worker_result(**extra):
    """A plot reply shaped the way a Globus Compute worker returns one."""
    return {
        "png_b64": base64.b64encode(PNG).decode("utf-8"),
        "image_size_bytes": len(PNG),
        "grid_info": {"n_face": 128001},
        "execution_venue": "hpc:chrysalis",
        "_provenance": {"tool": "remote_plot_mesh", "artifacts": []},
        **extra,
    }


def _artifact(result):
    artifacts = result["_provenance"]["artifacts"]
    assert len(artifacts) == 1, f"expected one plot artifact, got {artifacts}"
    return artifacts[0]


def test_a_figure_rendered_on_hpc_is_written_down(store):
    """The bug: base64 in the reply, empty artifacts, no file anywhere."""
    result = _ensure_plot_artifact(_worker_result(), plot_type="mesh_wireframe")
    artifact = _artifact(result)

    assert artifact["stored"] is True
    assert artifact["plot_type"] == "mesh_wireframe"
    assert artifact["size_bytes"] == len(PNG)

    written = Path(artifact["path"])
    assert written.exists(), "artifact names a path that was never written"
    assert written.read_bytes() == PNG
    assert artifact["uri"] == written.as_uri()


def test_the_reply_points_at_the_file_it_just_wrote(store):
    """A caller handing the figure to something else needs the URI."""
    result = _ensure_plot_artifact(_worker_result(), plot_type="mesh_wireframe")
    assert result["image_uri"] == _artifact(result)["uri"]

    # The bytes stay inline as well: the caller sees the picture in the same
    # round trip and can still reach the file afterwards.
    assert result["png_b64"]


def test_the_stored_remote_plot_is_what_resources_list_serves(store):
    """One store, whichever venue drew the figure."""
    from uxarray_mcp.resources import list_artifacts, read_artifact

    result = _ensure_plot_artifact(_worker_result(), plot_type="mesh_wireframe")
    artifact = _artifact(result)

    listed, _cursor = list_artifacts()
    uris = {item["uri"] for item in listed}
    assert artifact["uri"] in uris, (
        f"written where resources/list does not look; listed {sorted(uris)}"
    )

    served = read_artifact(artifact["uri"])
    assert served["mimeType"] == "image/png"
    assert base64.b64decode(served["blob"]) == PNG


def test_a_remote_variable_plot_names_the_variable_it_drew(store):
    """The worker resolves a null name to the first face-centered field."""
    result = _ensure_plot_artifact(
        _worker_result(variable_name="LW_flux_up_at_model_top"),
        plot_type="variable_polygons",
        variable="LW_flux_up_at_model_top",
    )
    assert _artifact(result)["variable"] == "LW_flux_up_at_model_top"


def test_a_locally_stored_plot_is_not_stored_twice(store):
    """The local path already writes its figure on the way out."""
    already = _worker_result()
    already["_provenance"]["artifacts"] = [{"type": "plot", "stored": True}]

    result = _ensure_plot_artifact(already, plot_type="mesh_wireframe")

    assert result["_provenance"]["artifacts"] == [{"type": "plot", "stored": True}]
    assert "image_uri" not in result


def test_a_reply_carrying_no_bytes_is_left_alone(store):
    """A large figure already handed back as a link has nothing to write."""
    linked = _worker_result()
    linked["png_b64"] = None
    linked["image_uri"] = "file:///somewhere/plot.png"

    result = _ensure_plot_artifact(linked, plot_type="mesh_wireframe")

    assert result["_provenance"]["artifacts"] == []
    assert result["image_uri"] == "file:///somewhere/plot.png"


def test_an_unwritable_store_says_so_instead_of_going_quiet(tmp_path, monkeypatch):
    """Losing the picture over a read-only directory is the worse failure."""
    monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path / "state"))

    def _boom(*_args, **_kwargs):
        raise PermissionError("read-only file system")

    monkeypatch.setattr(Path, "write_bytes", _boom)

    result = _ensure_plot_artifact(_worker_result(), plot_type="mesh_wireframe")
    artifact = _artifact(result)

    assert artifact["stored"] is False
    assert "PermissionError" in artifact["not_stored_because"]
    assert "path" not in artifact
    assert result["png_b64"], "the figure must still come back inline"
