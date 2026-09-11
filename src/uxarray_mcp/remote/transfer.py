"""Move files between this machine and an HPC collection over Globus Transfer.

Compute has always run there; nothing here could get a file there or back. A
mesh had to be staged by hand before a remote tool could see it, and anything
a remote tool wrote -- a subset, an export, a NetCDF too large to inline --
stayed on the cluster with no way down.

The transfer itself is four lines of Globus SDK. What this module is actually
for is the path arithmetic around it, because a transfer takes two paths and
gets no second chance to be wrong: it moves what it was told to move, at
whatever scale it was told, under credentials that reach the user's whole
allocation. Every check below exists because the obvious way to write it is
wrong in a way that still looks right in a test:

* ``os.path.join("/scratch/me", "/etc/passwd")`` returns ``/etc/passwd``. The
  root is discarded, silently, and the result is a valid path.
* ``"/work/ab".startswith("/work/a")`` is ``True``. Prefix containment on raw
  strings has no notion of a path boundary.
* ``..`` is textual on a remote path -- there is no filesystem here to resolve
  it against -- so it has to be collapsed before containment is checked, not
  after.
* a local symlink resolves to somewhere else entirely, so the local side is
  checked after ``realpath``, not before.

The service builds its own request payloads rather than using
``globus_sdk.TransferData``. That keeps the wire shape visible in one place and
lets the tests drive a fake client with no ``globus-sdk`` installed at all,
which is the only way this is testable without credentials in CI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from uxarray_mcp.remote.config import GlobusTransferProfile

__all__ = [
    "PathOutsideRoot",
    "TransferError",
    "TransferNotConfigured",
    "TransferLoginRequired",
    "TransferService",
    "bounded_preview",
    "collapse",
    "is_within",
    "join_under",
    "resolve_local",
    "to_collection_path",
]


class TransferError(RuntimeError):
    """Something about a transfer request could not be honoured."""


class TransferNotConfigured(TransferError):
    """The endpoint has no ``globus_transfer`` block, so it moves no files."""


class TransferLoginRequired(TransferError):
    """Globus has no usable token for Transfer on this machine."""


class PathOutsideRoot(TransferError):
    """A path resolved outside the root it was required to stay under."""


def collapse(path: str) -> str:
    """Resolve ``.`` and ``..`` textually, without touching a filesystem.

    A remote path cannot be `realpath`-ed from here, and normalizing it after
    the containment check is the same as not checking: ``/root/../etc`` is
    inside ``/root`` right up until the server resolves it.

    A ``..`` that would climb above the top is dropped rather than escaping,
    matching what POSIX does at ``/``.
    """
    pure = PurePosixPath(path)
    parts: list[str] = []
    for part in pure.parts:
        if part == ".":
            continue
        if part == "..":
            if parts and parts[-1] not in ("/", ".."):
                parts.pop()
            elif not pure.is_absolute():
                parts.append(part)
            continue
        parts.append(part)
    if not parts:
        return "/" if pure.is_absolute() else "."
    return str(PurePosixPath(*parts))


def is_within(root: str, candidate: str) -> bool:
    """Whether ``candidate`` is ``root`` or lives under it, boundary-aware.

    Compared component by component, so ``/work/ab`` is not under ``/work/a``.
    Both are collapsed first; neither is resolved against a filesystem.
    """
    root_parts = PurePosixPath(collapse(root)).parts
    candidate_parts = PurePosixPath(collapse(candidate)).parts
    return candidate_parts[: len(root_parts)] == root_parts


def join_under(root: str, path: str) -> str:
    """Place ``path`` under ``root``, refusing anything that leaves it.

    An absolute ``path`` is taken at its word and checked, not re-rooted:
    someone naming ``/scratch/me/out.nc`` under root ``/scratch/me`` means that
    file, and someone naming ``/etc/passwd`` gets an error rather than
    ``/scratch/me/etc/passwd``. A relative one is joined. Either way the result
    is collapsed and then required to be inside the root, so ``../..`` is
    caught in both forms.
    """
    if not PurePosixPath(root).is_absolute():
        raise PathOutsideRoot(f"Transfer root {root!r} must be an absolute path.")
    candidate = PurePosixPath(path)
    joined = candidate if candidate.is_absolute() else PurePosixPath(root) / candidate
    resolved = collapse(str(joined))
    if not is_within(root, resolved):
        raise PathOutsideRoot(
            f"{path!r} resolves to {resolved!r}, which is outside {root!r}."
        )
    return resolved


def resolve_local(path: str | os.PathLike[str], root: str | None = None) -> Path:
    """Resolve a local path through symlinks, then check containment.

    Order matters: a symlink inside the root pointing out of it passes a check
    made before resolution and fails one made after. Resolution is
    non-strict, so a download destination that does not exist yet still
    resolves -- what exists is followed, the rest is appended.
    """
    resolved = Path(path).expanduser().resolve()
    if root is None:
        return resolved
    root_resolved = Path(root).expanduser().resolve()
    if not is_within(str(root_resolved), str(resolved)):
        raise PathOutsideRoot(
            f"{str(path)!r} resolves to {str(resolved)!r}, which is outside "
            f"{str(root_resolved)!r}."
        )
    return resolved


def to_collection_path(path: str, collection_roots: tuple[str, ...] = ()) -> str:
    """Express a filesystem path the way its collection names it.

    A collection that exposes ``/lcrc/group/e3sm`` as its root calls
    ``/lcrc/group/e3sm/run/out.nc`` simply ``/run/out.nc``. The longest
    matching root wins, so nested roots do not depend on config order.

    A path under no configured root is returned unchanged. That is deliberate:
    Globus rejects a path its collection does not recognize, which is a clear
    failure, whereas a path rewritten under the wrong root can name a real file
    nobody asked about.
    """
    collapsed = collapse(path)
    for root in sorted(collection_roots, key=len, reverse=True):
        if not root:
            continue
        if is_within(root, collapsed):
            relative = PurePosixPath(collapsed).relative_to(
                PurePosixPath(collapse(root))
            )
            return "/" + str(relative) if str(relative) != "." else "/"
    return collapsed


def bounded_preview(
    path: str | os.PathLike[str], *, head_bytes: int = 2048, tail_bytes: int = 512
) -> str:
    """Read the ends of a file and say, in bytes, what was left out.

    A transferred file is checked by looking at it, and a NetCDF or a log can
    be any size at all, so the read is bounded at both ends. The omission is
    stated rather than implied by an ellipsis: a reader who cannot see how much
    is missing cannot tell a truncated preview from a short file.
    """
    size = os.path.getsize(path)
    if size <= head_bytes + tail_bytes:
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8", errors="replace")
    with open(path, "rb") as handle:
        head = handle.read(head_bytes)
        handle.seek(size - tail_bytes)
        tail = handle.read(tail_bytes)
    omitted = size - head_bytes - tail_bytes
    return (
        head.decode("utf-8", errors="replace")
        + f"\n... {omitted} of {size} bytes omitted ...\n"
        + tail.decode("utf-8", errors="replace")
    )


class TransferClientLike(Protocol):
    """The four calls this module makes on a Globus ``TransferClient``."""

    def operation_ls(self, collection_id: str, **kwargs: Any) -> Any: ...

    def get_submission_id(self) -> Any: ...

    def submit_transfer(self, data: Any) -> Any: ...

    def get_task(self, task_id: str) -> Any: ...


@dataclass(frozen=True)
class TransferPlan:
    """What a transfer would do, before anything is submitted."""

    source_collection_id: str
    source_path: str
    destination_collection_id: str
    destination_path: str
    recursive: bool
    label: str | None = None

    def as_payload(self, submission_id: str) -> dict[str, Any]:
        return {
            "DATA_TYPE": "transfer",
            "submission_id": submission_id,
            "source_endpoint": self.source_collection_id,
            "destination_endpoint": self.destination_collection_id,
            "label": self.label,
            "notify_on_succeeded": False,
            "notify_on_failed": False,
            "verify_checksum": True,
            "DATA": [
                {
                    "DATA_TYPE": "transfer_item",
                    "source_path": self.source_path,
                    "destination_path": self.destination_path,
                    "recursive": self.recursive,
                }
            ],
        }


class TransferService:
    """Upload, download and list, with the roots enforced on every path.

    The client is injected so the whole path matrix can be tested against a
    fake with no credentials anywhere. ``plan_put`` and ``plan_get`` do all the
    checking and touch no network, which is what makes those tests worth
    having.
    """

    def __init__(
        self,
        profile: GlobusTransferProfile,
        client: TransferClientLike | None = None,
    ) -> None:
        self.profile = profile
        self._client = client

    @property
    def client(self) -> TransferClientLike:
        if self._client is None:
            self._client = default_transfer_client(self.profile)
        return self._client

    # -- path rules ----------------------------------------------------

    def _write_root(self) -> str:
        root = self.profile.remote_write_root
        if not root:
            raise TransferNotConfigured(
                "This endpoint's globus_transfer block sets no remote_write_root, "
                "so there is nowhere a transfer is allowed to write."
            )
        return root

    def _read_roots(self) -> tuple[str, ...]:
        """Where reads may come from, in the order a relative path resolves.

        The write root is always readable: somewhere you may put a file is
        somewhere you may look at one, and a config that could write to
        `/scratch` but not list it would fail on the first download of
        something it had just uploaded. With no read root configured, reads
        fall back to the write root -- never to the whole filesystem.
        """
        write_root = self.profile.remote_write_root
        read_root = self.profile.remote_read_root
        if not read_root:
            return (self._write_root(),)
        if write_root and write_root != read_root:
            return (read_root, write_root)
        return (read_root,)

    def remote_write_path(self, path: str) -> str:
        return to_collection_path(
            join_under(self._write_root(), path), self.profile.collection_roots
        )

    def remote_read_path(self, path: str) -> str:
        roots = self._read_roots()
        last: PathOutsideRoot | None = None
        for root in roots:
            try:
                resolved = join_under(root, path)
            except PathOutsideRoot as exc:
                last = exc
                continue
            return to_collection_path(resolved, self.profile.collection_roots)
        raise PathOutsideRoot(
            f"{path!r} is outside every readable root ({', '.join(roots)})."
        ) from last

    def _local_collection_id(self) -> str:
        if not self.profile.local_collection_id:
            raise TransferNotConfigured(
                "This endpoint's globus_transfer block sets no "
                "local_collection_id, so this machine is not one end of a "
                "transfer. Install Globus Connect Personal and record its "
                "collection UUID."
            )
        return self.profile.local_collection_id

    # -- planning ------------------------------------------------------

    def plan_put(
        self, local_path: str | os.PathLike[str], remote_path: str, *, label=None
    ) -> TransferPlan:
        source = resolve_local(local_path, self.profile.local_root)
        if not source.exists():
            raise TransferError(f"{str(source)!r} does not exist; nothing to send.")
        return TransferPlan(
            source_collection_id=self._local_collection_id(),
            source_path=str(source),
            destination_collection_id=self.profile.remote_collection_id,
            destination_path=self.remote_write_path(remote_path),
            recursive=source.is_dir(),
            label=label,
        )

    def plan_get(
        self,
        remote_path: str,
        local_path: str | os.PathLike[str],
        *,
        recursive: bool = False,
        label: str | None = None,
    ) -> TransferPlan:
        destination = resolve_local(local_path, self.profile.local_root)
        return TransferPlan(
            source_collection_id=self.profile.remote_collection_id,
            source_path=self.remote_read_path(remote_path),
            destination_collection_id=self._local_collection_id(),
            destination_path=str(destination),
            recursive=recursive,
            label=label,
        )

    # -- submission ----------------------------------------------------

    def submit(self, plan: TransferPlan) -> dict[str, Any]:
        submission_id = _value_of(self.client.get_submission_id(), "value")
        response = self.client.submit_transfer(plan.as_payload(str(submission_id)))
        return {
            "task_id": _value_of(response, "task_id"),
            "status": _value_of(response, "code") or "submitted",
            "source_path": plan.source_path,
            "destination_path": plan.destination_path,
            "recursive": plan.recursive,
        }

    def put(
        self, local_path: str | os.PathLike[str], remote_path: str, *, label=None
    ) -> dict[str, Any]:
        return self.submit(self.plan_put(local_path, remote_path, label=label))

    def get(
        self,
        remote_path: str,
        local_path: str | os.PathLike[str],
        *,
        recursive: bool = False,
        label: str | None = None,
    ) -> dict[str, Any]:
        return self.submit(
            self.plan_get(remote_path, local_path, recursive=recursive, label=label)
        )

    def ls(self, remote_path: str) -> list[dict[str, Any]]:
        """List a remote directory, under the read root like everything else."""
        path = self.remote_read_path(remote_path)
        response = self.client.operation_ls(
            self.profile.remote_collection_id, path=path
        )
        entries = _value_of(response, "DATA") or []
        return [
            {
                "name": entry.get("name"),
                "type": entry.get("type"),
                "size": entry.get("size"),
                "last_modified": entry.get("last_modified"),
            }
            for entry in entries
        ]

    def status(self, task_id: str) -> dict[str, Any]:
        response = self.client.get_task(task_id)
        return {
            "task_id": task_id,
            "status": _value_of(response, "status"),
            "bytes_transferred": _value_of(response, "bytes_transferred"),
            "files_transferred": _value_of(response, "files_transferred"),
            "fatal_error": _value_of(response, "fatal_error"),
        }


def _value_of(response: Any, key: str) -> Any:
    """Read a key off a Globus response, a dict, or an object with attributes.

    The SDK's response objects are mapping-like; a fake in a test is a plain
    dict; neither should have to know about the other.
    """
    if response is None:
        return None
    if isinstance(response, dict):
        return response.get(key)
    try:
        return response[key]
    except (TypeError, KeyError):
        return getattr(response, key, None)


def default_transfer_client(
    profile: GlobusTransferProfile,
) -> TransferClientLike:
    """Build a real client from the login Globus Compute already made.

    Same native client as `globus-compute-sdk`, same token storage, so a user
    who has run a remote tool has already logged in and only needs to consent
    to the Transfer scope. That consent is an interactive browser flow, and an
    MCP server has no terminal to run it in, so a missing token raises with the
    command to run rather than blocking on a prompt nobody will see.

    Mapped collections need a per-collection ``data_access`` scope on top of
    the base Transfer scope; both configured collections are declared before
    the login state is checked, so a user who consented to one and not the
    other is told to log in again rather than failing later on a path.
    """
    try:
        import globus_sdk
        from globus_compute_sdk.sdk.auth.globus_app import get_globus_app
    except ImportError as exc:  # pragma: no cover - exercised by install shape
        raise TransferError(
            "Globus Transfer needs the transfer extra: "
            "pip install 'uxarray-mcp[transfer]'."
        ) from exc

    app = get_globus_app()
    client = globus_sdk.TransferClient(app=app)
    for collection_id in (
        profile.remote_collection_id,
        profile.local_collection_id,
    ):
        if collection_id:
            client.add_app_data_access_scope(collection_id)
    if app.login_required():
        raise TransferLoginRequired(
            "Globus has no Transfer consent for these collections on this "
            "machine. Run `uxarray-mcp transfer-login` in a terminal, which "
            "opens the browser flow an MCP server cannot."
        )
    return client


def transfer_service_for(profile: Any) -> TransferService:
    """Build a service from an endpoint profile, or say why there is none."""
    transfer_profile = getattr(profile, "globus_transfer", None)
    if transfer_profile is None:
        name = getattr(profile, "name", "this endpoint")
        raise TransferNotConfigured(
            f"{name} has no globus_transfer block in config.yaml, so it moves "
            f"no files. Add remote_collection_id and remote_write_root to "
            f"enable transfers for it."
        )
    return TransferService(transfer_profile)
