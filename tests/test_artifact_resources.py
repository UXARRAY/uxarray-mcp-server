"""The artifact links we hand out have to be fetchable (#14).

A large figure goes back as an MCP ``resource_link`` instead of an inlined
base64 blob. That link is only a link if something answers ``resources/read``
for it, and before this the server advertised no ``resources`` capability and
registered no resource handler at all. These tests hold three things: the
capability is advertised on both server construction paths, an artifact
round-trips through ``resources/read`` byte-for-byte, and a URI pointing
anywhere but the artifact store is refused rather than served.
"""

from __future__ import annotations

import base64
import json

import pytest

import uxarray_mcp.app as app_module
from uxarray_mcp.app import make_mcp_server
from uxarray_mcp.resources import (
    ARTIFACT_PAGE_SIZE,
    ArtifactNotServable,
    list_artifacts,
    read_artifact,
    uri_to_artifact_path,
)
from uxarray_mcp.state import _artifacts_dir

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4


def _handlers(server):
    """Return the methods the SDK's handler table answers.

    Reading the table is deliberate: ``get_capabilities`` derives the
    capability from ``resources/list`` alone, so a server that advertises the
    capability and cannot answer a read would pass a capability-only check.
    The table is keyed by request type, so each key is mapped back to the
    method string it declares.
    """
    return {key.model_fields["method"].default for key in server.request_handlers}


async def _dispatch(server, request):
    """Invoke a registered handler the way the SDK would.

    The handler is called with the request itself and answers a
    ``ServerResult``; unwrap it so the assertions can talk about the result.
    """
    result = await server.request_handlers[type(request)](request)
    return result.root


@pytest.fixture
def artifact_store(tmp_path, monkeypatch):
    """Point the state root at a temp dir so tests never read the real store."""
    monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path / "state"))
    return _artifacts_dir()


def _write(store, name: str, data: bytes) -> str:
    path = store / name
    path.write_bytes(data)
    return path.as_uri()


# ---------------------------------------------------------------------------
# The capability reaches the handshake
# ---------------------------------------------------------------------------


def test_make_mcp_server_advertises_resources():
    """Without this the link is a URI over a protocol that cannot fetch it."""
    server = make_mcp_server(profile="core")
    capabilities = server.get_capabilities(
        notification_options=_no_notifications(), experimental_capabilities={}
    )
    assert capabilities.resources is not None


def test_make_mcp_server_registers_both_resource_methods():
    server = make_mcp_server(profile="core")
    handlers = _handlers(server)
    assert "resources/list" in handlers
    assert "resources/read" in handlers


def test_serve_mcp_registers_the_same_handlers(monkeypatch):
    """The CLI path builds its own adapter, so it needs its own wiring.

    ``make_mcp_server`` is what the rest of the suite exercises; ``serve_mcp``
    is what users run. Attaching in only one of them would leave the tested
    surface and the served surface different, which is the failure this test
    exists to catch, so ``run`` is stubbed out and the adapter inspected.
    """
    captured = {}

    from toolregistry_server.adapters.mcp import MCPAdapter

    def fake_run(self, **kwargs):
        captured["handlers"] = _handlers(self.server)

    monkeypatch.setattr(MCPAdapter, "run", fake_run)
    app_module.UXarrayApp().serve_mcp(profile="core")

    assert "resources/list" in captured["handlers"]
    assert "resources/read" in captured["handlers"]


@pytest.mark.asyncio
async def test_registered_handlers_answer_over_the_protocol_types(artifact_store):
    """Exercise the handlers themselves, not just the functions behind them.

    The two layers can disagree: ``list_artifacts`` returns ``mimeType`` and a
    plain cursor string, while the SDK models want ``mime_type`` and
    ``nextCursor``. Only calling the registered handler proves the field names
    line up.
    """
    import mcp.types as types

    _write(artifact_store, "plot_abc.png", PNG_BYTES)
    server = make_mcp_server(profile="core")

    listed = await _dispatch(
        server,
        types.ListResourcesRequest(
            method="resources/list", params=types.PaginatedRequestParams(cursor=None)
        ),
    )
    assert [str(item.uri) for item in listed.resources] == [
        (artifact_store / "plot_abc.png").as_uri()
    ]
    assert listed.resources[0].mimeType == "image/png"
    assert listed.nextCursor is None

    read = await _dispatch(
        server,
        types.ReadResourceRequest(
            method="resources/read",
            params=types.ReadResourceRequestParams(uri=str(listed.resources[0].uri)),
        ),
    )
    assert base64.b64decode(read.contents[0].blob) == PNG_BYTES


def _no_notifications():
    class _Options:
        prompts_changed = False
        resources_changed = False
        tools_changed = False

    return _Options()


# ---------------------------------------------------------------------------
# Reading an artifact back
# ---------------------------------------------------------------------------


def test_png_round_trips_as_a_blob(artifact_store):
    uri = _write(artifact_store, "plot_abc.png", PNG_BYTES)
    contents = read_artifact(uri)
    assert contents["mimeType"] == "image/png"
    assert base64.b64decode(contents["blob"]) == PNG_BYTES
    assert "text" not in contents


def test_json_round_trips_as_text(artifact_store):
    payload = {"faces": 648, "units": "K"}
    uri = _write(artifact_store, "result_abc.json", json.dumps(payload).encode())
    contents = read_artifact(uri)
    assert contents["mimeType"] == "application/json"
    assert json.loads(contents["text"]) == payload


def test_unknown_suffix_is_a_blob_not_a_guess(artifact_store):
    """Guessing text on a binary hands the client a decoding error."""
    uri = _write(artifact_store, "mesh_abc.nc", b"CDF\x01\x00\x00")
    contents = read_artifact(uri)
    assert "blob" in contents
    assert contents["mimeType"] in {"application/octet-stream", "application/x-netcdf"}


# ---------------------------------------------------------------------------
# Refusals. Serving files by URI is the shape of a traversal bug.
# ---------------------------------------------------------------------------


def test_absolute_path_outside_the_store_is_refused(artifact_store):
    with pytest.raises(ArtifactNotServable, match="outside the artifact directory"):
        uri_to_artifact_path("file:///etc/passwd")


def test_dot_dot_escape_is_refused(artifact_store):
    """Confinement is checked after ``resolve()``, which collapses ``..``."""
    escaped = f"file://{artifact_store}/../../../../etc/passwd"
    with pytest.raises(ArtifactNotServable, match="outside the artifact directory"):
        uri_to_artifact_path(escaped)


def test_symlink_out_of_the_store_is_refused(artifact_store, tmp_path):
    """``resolve()`` follows the link, so the target is what gets checked."""
    outside = tmp_path / "secret.txt"
    outside.write_text("not an artifact")
    link = artifact_store / "escape.txt"
    link.symlink_to(outside)
    with pytest.raises(ArtifactNotServable, match="outside the artifact directory"):
        uri_to_artifact_path(link.as_uri())


def test_non_file_scheme_is_refused(artifact_store):
    with pytest.raises(ArtifactNotServable, match="not a file:// URI"):
        uri_to_artifact_path("https://example.com/x.png")


def test_remote_host_is_refused(artifact_store):
    with pytest.raises(ArtifactNotServable, match="remote host"):
        uri_to_artifact_path("file://otherhost/x.png")


def test_missing_artifact_says_so(artifact_store):
    uri = (artifact_store / "gone.png").as_uri()
    with pytest.raises(ArtifactNotServable, match="does not name an artifact"):
        uri_to_artifact_path(uri)


def test_a_directory_is_not_an_artifact(artifact_store):
    (artifact_store / "subdir").mkdir()
    with pytest.raises(ArtifactNotServable, match="does not name an artifact"):
        uri_to_artifact_path((artifact_store / "subdir").as_uri())


# ---------------------------------------------------------------------------
# Listing is paged, because the store is unbounded
# ---------------------------------------------------------------------------


def test_empty_store_lists_nothing(artifact_store):
    assert list_artifacts() == ([], None)


def test_one_page_stops_at_the_page_size(artifact_store):
    for index in range(ARTIFACT_PAGE_SIZE + 25):
        _write(artifact_store, f"plot_{index:04d}.png", b"x")
    page, cursor = list_artifacts()
    assert len(page) == ARTIFACT_PAGE_SIZE
    assert cursor is not None


def test_paging_walks_every_artifact_exactly_once(artifact_store):
    """The measured store held 1258 files; an unpaged listing was 212 KB."""
    expected = {f"plot_{index:04d}.png" for index in range(ARTIFACT_PAGE_SIZE * 2 + 7)}
    for name in expected:
        _write(artifact_store, name, b"x")

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page, cursor = list_artifacts(cursor)
        seen.extend(item["name"] for item in page)
        pages += 1
        if cursor is None:
            break
        assert pages < 20, "cursor never terminated"

    assert pages == 3
    assert len(seen) == len(expected)
    assert set(seen) == expected
    assert seen == sorted(seen)


def test_the_last_page_reports_no_cursor(artifact_store):
    for index in range(ARTIFACT_PAGE_SIZE):
        _write(artifact_store, f"plot_{index:04d}.png", b"x")
    _, cursor = list_artifacts()
    assert cursor is None


def test_deleting_ahead_of_the_cursor_does_not_skip_entries(artifact_store):
    """Resuming by name rather than by offset is what makes this hold.

    Tools write into this store and cleanup deletes from it while a client is
    paging. An offset into a list that shrank silently steps over entries; a
    name does not.
    """
    for index in range(6):
        _write(artifact_store, f"plot_{index:04d}.png", b"x")

    page, cursor = list_artifacts(page_size=2)
    assert [item["name"] for item in page] == ["plot_0000.png", "plot_0001.png"]

    (artifact_store / "plot_0002.png").unlink()
    page, cursor = list_artifacts(cursor, page_size=2)
    assert [item["name"] for item in page] == ["plot_0003.png", "plot_0004.png"]


def test_a_cursor_we_did_not_issue_is_refused(artifact_store):
    """Restarting silently would look to the client like forward progress."""
    with pytest.raises(ArtifactNotServable, match="not a cursor this server issued"):
        list_artifacts("not-a-cursor!!")


def test_a_symlink_out_of_the_store_is_not_listed(artifact_store, tmp_path):
    """Listing a URI that ``resources/read`` will refuse is the same bug again."""
    outside = tmp_path / "secret.txt"
    outside.write_text("not an artifact")
    (artifact_store / "escape.txt").symlink_to(outside)
    _write(artifact_store, "plot_0000.png", b"x")
    page, _ = list_artifacts()
    assert [item["name"] for item in page] == ["plot_0000.png"]


def test_hidden_files_are_not_listed(artifact_store):
    _write(artifact_store, ".hidden", b"x")
    _write(artifact_store, "plot_0000.png", b"x")
    page, _ = list_artifacts()
    assert [item["name"] for item in page] == ["plot_0000.png"]


def test_listing_reports_size_and_type(artifact_store):
    _write(artifact_store, "plot_abc.png", PNG_BYTES)
    page, _ = list_artifacts()
    assert page[0]["mimeType"] == "image/png"
    assert page[0]["size"] == len(PNG_BYTES)
    assert page[0]["uri"].startswith("file://")
