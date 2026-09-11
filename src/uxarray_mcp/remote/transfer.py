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

The service builds its own request payloads rather than assembling calls inline.
That keeps the wire shape visible in one place and lets the tests drive a fake
client with nothing Globus installed at all, which is the only way this is
testable without credentials in CI.

Nothing here authenticates. The four calls this module makes are handed to the
``globus`` command-line client, which already owns the user's tokens, consents
and sessions; see ``CliTransferClient``. Holding no auth code is the point, not
an omission -- Globus auth has scopes that exist on one kind of collection and
not another, and session policies a local consent check cannot see, and every
one of those rules is a rule the CLI already implements and we would otherwise
have to track.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from uxarray_mcp.remote.config import GlobusTransferProfile

__all__ = [
    "CliTransferClient",
    "PathOutsideRoot",
    "TransferError",
    "TransferNotConfigured",
    "TransferLoginRequired",
    "TransferService",
    "bounded_preview",
    "collapse",
    "find_globus_cli",
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
    """Globus will not act for this user until they log in again.

    Covers the three failures that look unrelated and are not: no tokens, no
    consent for a collection's ``data_access`` scope, and a session identity a
    collection's policy refuses. Each needs a browser, so each needs a
    terminal, which is the one thing an MCP server does not have.
    """


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

    A relative path resolves against ``root`` when there is one, matching what
    the remote side already does with ``remote_write_root``. The alternative is
    the process working directory, which for a server started by an MCP client
    is wherever that client happened to be launched from -- a different
    directory per client, invisible to the caller, and never the one they meant.
    """
    given = Path(path).expanduser()
    if root is not None and not given.is_absolute():
        given = Path(root).expanduser() / given
    resolved = given.resolve()
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


CLI_TIMEOUT_SECONDS = 120

# Text the CLI prints when the problem is who you are rather than what you
# asked for. Globus has several such failures and they read nothing alike: no
# tokens at all, tokens without consent for a collection's ``data_access``
# scope, and a session whose identity the collection's own policy rejects. All
# three are fixed by logging in again, in a terminal, so all three are one
# exception here -- and the CLI's own words go along with it, because those are
# the words in the Globus documentation and in any support ticket that follows.
_LOGIN_MARKERS = (
    "MissingLoginError",
    "globus login",
    "globus session",
    "ConsentRequired",
    "consent_required",
    "session_required",
    "AuthenticationFailed",
    "PermissionDenied",
)


def find_globus_cli() -> str:
    """Locate the ``globus`` executable, or say how to get one.

    ``shutil.which`` alone is not enough. A server started by a desktop MCP
    client inherits the launcher's environment rather than a login shell's, so
    a CLI that works when the user types it can be missing here; the two
    directories pip actually drops console scripts into are checked by hand
    before giving up.
    """
    found = shutil.which("globus")
    if found:
        return found
    for candidate in (
        Path(sys.prefix) / "bin" / "globus",
        Path.home() / ".local" / "bin" / "globus",
    ):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise TransferError(
        "The globus command-line client is not installed, or is not on this "
        "process's PATH. Install it with `pip install globus-cli`, then run "
        "`uxarray-mcp transfer setup`."
    )


class CliTransferClient:
    """The four Transfer calls, made by running the ``globus`` CLI.

    The CLI holds the user's tokens, consents and session, so this class holds
    none: there is no login flow here, no token store, no scope arithmetic, and
    nothing that expires. A failure comes back as the CLI's own stderr, which
    is what the user will paste into a search box or a support ticket anyway.

    ``runner`` is injected so the whole thing can be tested against a fake
    without a binary, a network, or credentials.
    """

    def __init__(
        self,
        executable: str | None = None,
        *,
        timeout_seconds: int = CLI_TIMEOUT_SECONDS,
        runner: Any = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self._executable = executable or find_globus_cli()
        self._timeout = timeout_seconds

    # -- running it ----------------------------------------------------

    def _run(self, *argv: str) -> str:
        printable = "globus " + " ".join(argv)
        try:
            proc = self._runner(
                [self._executable, *argv],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TransferError(
                f"`{printable}` did not finish within {self._timeout} seconds."
            ) from exc
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip()[-4000:]
            detail = f"`{printable}` failed:\n{message}" if message else printable
            if any(marker in message for marker in _LOGIN_MARKERS):
                raise TransferLoginRequired(
                    f"{detail}\n\nThis is a Globus login, consent or identity "
                    f"problem, which only a terminal can fix. Run "
                    f"`uxarray-mcp transfer setup` and follow what it asks."
                )
            raise TransferError(detail)
        return proc.stdout

    def _run_json(self, *argv: str) -> Any:
        raw = self._run(*argv)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TransferError(
                f"`globus {' '.join(argv)}` did not return JSON:\n{raw.strip()[:4000]}"
            ) from exc

    def whoami(self) -> str:
        """The logged-in identity, or ``TransferLoginRequired``."""
        return self._run("whoami").strip()

    # -- the protocol --------------------------------------------------

    def operation_ls(self, collection_id: str, **kwargs: Any) -> Any:
        path = kwargs.get("path") or "/"
        return self._run_json(
            "ls", "--long", "--format", "json", f"{collection_id}:{path}"
        )

    def get_submission_id(self) -> Any:
        """A sentinel: ``globus transfer`` mints and consumes its own.

        The id exists so a retried submission cannot run twice, and the CLI
        already handles that end to end. Returning a placeholder keeps
        ``TransferService.submit`` written against one shape.
        """
        return {"value": "globus-cli"}

    def submit_transfer(self, data: Any) -> Any:
        items = data.get("DATA") or []
        if len(items) != 1:
            raise TransferError(
                f"The CLI backend submits one path pair at a time; this "
                f"payload has {len(items)}. Use `globus transfer --batch` for "
                f"more."
            )
        item = items[0]
        argv = ["transfer"]
        if item.get("recursive"):
            argv.append("--recursive")
        argv += [
            f"{data['source_endpoint']}:{item['source_path']}",
            f"{data['destination_endpoint']}:{item['destination_path']}",
            "--notify",
            "off",
            "--format",
            "json",
        ]
        # Checksum verification is the CLI's default, so only its absence is
        # worth saying out loud.
        if data.get("verify_checksum") is False:
            argv.append("--no-verify-checksum")
        if data.get("label"):
            argv += ["--label", str(data["label"])]
        return self._run_json(*argv)

    def get_task(self, task_id: str) -> Any:
        return self._run_json("task", "show", "--format", "json", task_id)


def default_transfer_client(
    profile: GlobusTransferProfile,
) -> TransferClientLike:
    """Hand the work to the ``globus`` CLI, after checking it can do it.

    ``profile`` is unused, and that is the change: the previous client read the
    collection UUIDs off it to request a ``data_access`` scope for each. Only
    Globus Connect Server v5 collections have that scope -- a Globus Connect
    Personal collection does not, so asking for one on the local end left the
    login permanently incomplete and every transfer refused. Which collections
    need which scopes is the CLI's problem now.
    """
    del profile  # the CLI resolves collections and scopes for itself
    client = CliTransferClient()
    client.whoami()
    return client
