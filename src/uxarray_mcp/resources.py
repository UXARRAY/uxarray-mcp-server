"""Serve the artifacts this server hands back by reference (#14).

A figure at or above :data:`~uxarray_mcp.typed_results.INLINE_PAYLOAD_LIMIT_BYTES`
is written to the artifact store and returned as an MCP ``resource_link``
rather than inlined, because base64 inflates the bytes by a third and a
multi-hundred-kilobyte PNG costs far more of the caller's context than the
picture is worth. That trade is right. What was wrong is that the link went
out over a server advertising no ``resources`` capability and serving neither
``resources/list`` nor ``resources/read``: measured on the core profile, the
capability was ``None`` and the handler table held no resource method at all.
So a client that followed the link the way the spec says to got
``METHOD_NOT_FOUND``, and a client that did not follow up lost the figure
entirely. Either way the URI was a promise nothing could keep.

The fix is to keep the promise rather than withdraw it. Registering the two
read methods makes the same ``file://`` URI fetchable over the protocol,
which also makes the link correct over HTTP, where the client does not share
a filesystem with the server and never could have opened the path itself.

Serving files by URI is exactly the shape of a path-traversal bug, so reading
is confined to the artifact directory and the confinement is enforced after
``resolve()``, which collapses ``..`` and follows symlinks. A request for a
path outside that directory is refused rather than clamped: a caller asking
for ``/etc/passwd`` is not making a repairable mistake.
"""

from __future__ import annotations

import base64
import bisect
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .state import _artifacts_dir

#: Extensions served as text rather than as a base64 blob. Anything else is
#: returned as ``BlobResourceContents``; guessing wrong on a PNG would hand
#: the client a decoding error instead of an image.
_TEXT_SUFFIXES = frozenset({".json", ".txt", ".md", ".csv"})

#: Fallback when :mod:`mimetypes` cannot name the type. ``application/octet-stream``
#: is honest about a blob whose type we could not determine.
_DEFAULT_MIME = "application/octet-stream"

#: Artifacts described per ``resources/list`` page. The store is append-only in
#: practice and unbounded in principle -- measured at 1258 files and 212 KB of
#: JSON on one developer machine -- so an unpaged listing is the same
#: swallow-the-context mistake that :mod:`~uxarray_mcp.typed_results` exists to
#: prevent, only arriving through the protocol instead of through a tool result.
#: At the measured 168 bytes per entry a page costs about 17 KB, which is the
#: size of a large tool result rather than of a whole session.
ARTIFACT_PAGE_SIZE = 100


class ArtifactNotServable(ValueError):
    """A URI does not name a readable file inside the artifact store."""


def _mime_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or _DEFAULT_MIME


def _encode_cursor(name: str) -> str:
    """Wrap a filename as the opaque cursor the protocol asks for.

    The spec calls the cursor opaque, so it is encoded rather than handed over
    as a bare filename: a client that reads one and starts constructing its own
    would be depending on an implementation detail we would then be unable to
    change.
    """
    return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None) -> str | None:
    """Recover the filename a cursor names, refusing anything we did not issue."""
    if cursor is None:
        return None
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        # An invalid cursor is refused rather than treated as "start over".
        # Silently restarting would hand a paging client the first page again
        # under the impression it was making progress.
        raise ArtifactNotServable(
            f"{cursor!r} is not a cursor this server issued. Omit the cursor to "
            "list from the beginning."
        ) from exc


def uri_to_artifact_path(uri: str) -> Path:
    """Resolve a ``file://`` URI to a path inside the artifact store.

    Raises
    ------
    ArtifactNotServable
        If the URI is not a ``file://`` URI, if it escapes the artifact
        directory once symlinks and ``..`` are collapsed, or if it does not
        name an existing regular file.
    """
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ArtifactNotServable(
            f"{uri!r} is not a file:// URI. This server serves only the "
            "artifacts it wrote itself."
        )
    if parsed.netloc not in ("", "localhost"):
        # A host component would name a file on another machine, which this
        # server has no business fetching on the caller's behalf.
        raise ArtifactNotServable(f"{uri!r} names a remote host.")

    candidate = Path(unquote(parsed.path)).resolve()
    root = _artifacts_dir().resolve()
    if not candidate.is_relative_to(root):
        raise ArtifactNotServable(
            f"{uri!r} is outside the artifact directory. Only artifacts this "
            "server produced can be read back."
        )
    if not candidate.is_file():
        raise ArtifactNotServable(
            f"{uri!r} does not name an artifact that still exists. Artifacts "
            "are files on the server, not permanent storage; re-run the "
            "operation to produce a fresh one."
        )
    return candidate


def read_artifact(uri: str) -> dict[str, Any]:
    """Read one artifact as an MCP resource-contents dictionary.

    Returns a mapping with ``uri``, ``mimeType`` and either ``text`` or
    ``blob``, matching the two ``ResourceContents`` shapes the protocol
    defines.
    """
    path = uri_to_artifact_path(uri)
    mime_type = _mime_for(path)
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return {
            "uri": uri,
            "mimeType": mime_type,
            "text": path.read_text(encoding="utf-8"),
        }
    return {
        "uri": uri,
        "mimeType": mime_type,
        "blob": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def list_artifacts(
    cursor: str | None = None, page_size: int = ARTIFACT_PAGE_SIZE
) -> tuple[list[dict[str, Any]], str | None]:
    """Describe one page of the artifacts currently on disk.

    Listing is a directory scan rather than a registry the tools write to:
    the store is shared by every session on this machine and artifacts are
    deleted out from under us by ordinary cleanup, so a scan is the only
    account of it that cannot go stale.

    Returns the page and the cursor for the next one, or ``None`` when the
    page reaches the end.

    Raises
    ------
    ArtifactNotServable
        If ``cursor`` is not one this function issued.
    """
    root = _artifacts_dir()
    if not root.is_dir():
        return [], None

    after = _decode_cursor(cursor)
    resolved_root = root.resolve()
    names = sorted(
        path.name
        for path in root.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        # A symlink out of the store is listable but not readable, and this
        # module exists because advertising a URI nothing will serve is worse
        # than not advertising it.
        and path.resolve().is_relative_to(resolved_root)
    )
    if after is not None:
        # Resume by name rather than by offset. The store changes underneath a
        # paging client -- tools write into it and cleanup deletes from it --
        # and an offset into a list that shrank silently skips entries. A name
        # is stable: whatever is still there and sorts after it comes next.
        start = bisect.bisect_right(names, after)
    else:
        start = 0

    page = names[start : start + page_size]
    resources: list[dict[str, Any]] = []
    for name in page:
        path = root / name
        try:
            size = path.stat().st_size
        except OSError:
            # Deleted between the scan and the stat. Omitting it is the
            # truthful answer; it is no longer an artifact anyone can read.
            continue
        resources.append(
            {
                "uri": path.as_uri(),
                "name": name,
                "mimeType": _mime_for(path),
                "size": size,
            }
        )

    exhausted = start + page_size >= len(names)
    next_cursor = None if exhausted or not page else _encode_cursor(page[-1])
    return resources, next_cursor


def attach_artifact_resources(server: Any) -> Any:
    """Register ``resources/list`` and ``resources/read`` on an MCP server.

    Called from both server construction sites so the surface tests exercise
    is the surface the CLI serves. The capability itself is derived by the
    SDK from the presence of these handlers, so registering them is what
    makes ``resources`` appear in the handshake.

    Returns the server, so callers can wrap a constructor call in place.
    """
    try:
        import mcp.types as types
    except ImportError:  # pragma: no cover - MCP SDK is a hard dep of serving
        return server

    async def on_list_resources(ctx: Any, params: Any) -> Any:
        page, next_cursor = list_artifacts(getattr(params, "cursor", None))
        return types.ListResourcesResult(
            resources=[types.Resource(**item) for item in page],
            nextCursor=next_cursor,
        )

    async def on_read_resource(ctx: Any, params: Any) -> Any:
        contents = read_artifact(str(params.uri))
        if "text" in contents:
            block: Any = types.TextResourceContents(**contents)
        else:
            block = types.BlobResourceContents(**contents)
        return types.ReadResourceResult(contents=[block])

    # Both SDK generations are inside the range this package declares, and they
    # register handlers through different APIs: mcp 1.x has per-method
    # decorators and no ``add_request_handler``, mcp 2.x has
    # ``add_request_handler`` and no decorators. Registering through only one
    # of them leaves the other advertising no resources and 404-ing every
    # artifact link -- silently, because a failed registration looks exactly
    # like an empty artifact store. Verified against mcp 1.27.2 and 2.1.1.
    if hasattr(server, "add_request_handler"):
        server.add_request_handler(
            "resources/list", types.PaginatedRequestParams, on_list_resources
        )
        server.add_request_handler(
            "resources/read", types.ReadResourceRequestParams, on_read_resource
        )
        return server

    if not (hasattr(server, "list_resources") and hasattr(server, "read_resource")):
        return server

    async def _list_resources(req: Any) -> Any:
        cursor = getattr(getattr(req, "params", None), "cursor", None)
        page, next_cursor = list_artifacts(cursor)
        return types.ListResourcesResult(
            resources=[types.Resource(**item) for item in page],
            nextCursor=next_cursor,
        )

    # The SDK decides whether to hand the handler its request by resolving the
    # annotations with ``get_type_hints``, and ``from __future__ import
    # annotations`` makes ours strings it evaluates against this module's
    # globals -- where ``types`` is a local of this function and does not
    # resolve. Binding the class object is what makes the parameter recognized:
    # left as ``Any`` the SDK calls the handler with no arguments at all, and
    # the paging cursor never arrives. Set before registering, because the
    # decorator inspects the function as it is passed.
    _list_resources.__annotations__ = {"req": types.ListResourcesRequest}
    server.list_resources()(_list_resources)

    @server.read_resource()
    async def _read_resource(uri: Any) -> Any:
        from mcp.server.lowlevel.helper_types import ReadResourceContents

        contents = read_artifact(str(uri))
        if "text" in contents:
            payload: Any = contents["text"]
        else:
            payload = base64.b64decode(contents["blob"])
        return [
            ReadResourceContents(content=payload, mime_type=contents.get("mimeType"))
        ]

    return server
