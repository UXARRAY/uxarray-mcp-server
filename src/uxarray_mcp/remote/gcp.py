"""What Globus Connect Personal is doing on this machine, read from its own files.

Globus Connect Personal is what makes a laptop one end of a transfer. It is a
separate program with its own configuration, and three of its states are
invisible from the Globus side of the wire while being the whole reason a
transfer fails:

* it is not running, so the collection exists and answers nothing;
* the directory being transferred is not shared, so the path is not there;
* the directory is shared **read-only**, so a download fails on the write and
  an upload from it succeeds -- one direction works and the other does not,
  which reads like a network problem and is not.

The third is the one that costs an afternoon. The default share on a fresh
install is the user's home directory with the write bit clear, and nothing
warns about it until a transfer has already been submitted, run, and failed
with ``PERMISSION_DENIED`` on the destination.

Everything here reads; nothing here changes Globus Connect Personal's
configuration. Where a value cannot be established -- an unfamiliar platform, a
file that is not there -- the answer is ``None``, meaning "unknown", never
``False``. A confident wrong "no" would send someone to fix the wrong thing.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Injected in tests so none of this needs a real Globus Connect Personal, and
# `None` means "use the real one" rather than "do nothing".
Runner = Callable[..., Any] | None

__all__ = [
    "GcpShare",
    "MACOS_DEFAULTS_DOMAIN",
    "collection_id",
    "config_paths_file",
    "is_running",
    "share_for",
    "shares",
]

MACOS_DEFAULTS_DOMAIN = "org.globusonline.Globus-Connect"
_LTA_DIR = Path.home() / ".globusonline" / "lta"


@dataclass(frozen=True)
class GcpShare:
    """One directory Globus Connect Personal exposes, and on what terms."""

    path: str
    readable: bool
    writable: bool


def collection_id() -> str | None:
    """This machine's collection UUID, as Globus Connect Personal recorded it.

    Reading the file beats asking the user to find it in the web app, where
    their own collections sit in a list with everyone else's.
    """
    try:
        value = (_LTA_DIR / "client-id.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def config_paths_file() -> Path:
    """Where the Linux build keeps its share list."""
    return _LTA_DIR / "config-paths"


def _shares_from_config_paths() -> list[GcpShare] | None:
    """Parse ``~/.globusonline/lta/config-paths`` -- ``<path>,<sharing>,<rw>``."""
    try:
        text = config_paths_file().read_text(encoding="utf-8")
    except OSError:
        return None
    found: list[GcpShare] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(",")]
        path = str(Path(parts[0]).expanduser())
        # A malformed or truncated line is read the permissive way the program
        # itself reads it, rather than being dropped: a share we fail to see is
        # a warning we give about a directory that is actually fine.
        writable = parts[2] == "1" if len(parts) > 2 else True
        found.append(GcpShare(path=path, readable=True, writable=writable))
    return found


def _shares_from_macos_defaults(runner: Runner = None) -> list[GcpShare] | None:
    """Parse ``GC_RESTRICTED_PATHS`` out of the macOS preferences domain.

    ``defaults export`` is used rather than ``defaults read`` because it emits
    an XML property list, which ``plistlib`` parses exactly; ``defaults read``
    prints an ad-hoc format that has to be guessed at.

    Each entry maps a directory to a ``(read, write)`` pair of flags.
    """
    run = runner or subprocess.run
    try:
        proc = run(
            ["defaults", "export", MACOS_DEFAULTS_DOMAIN, "-"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    raw = proc.stdout
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    try:
        parsed = plistlib.loads(raw)
    except Exception:
        return None
    restricted = parsed.get("GC_RESTRICTED_PATHS")
    if not isinstance(restricted, dict):
        return None
    found: list[GcpShare] = []
    for path, flags in restricted.items():
        pair = list(flags) if isinstance(flags, (list, tuple)) else [flags]
        readable = bool(pair[0]) if pair else False
        writable = bool(pair[1]) if len(pair) > 1 else False
        found.append(
            GcpShare(
                path=str(Path(str(path)).expanduser()),
                readable=readable,
                writable=writable,
            )
        )
    return found


def shares(runner: Runner = None) -> list[GcpShare] | None:
    """Every directory this machine exposes, or ``None`` if it cannot be read."""
    if sys.platform == "darwin":
        found = _shares_from_macos_defaults(runner)
        # A macOS install that also has the Linux-style file is unusual but
        # cheap to honour, and beats reporting nothing.
        return found if found is not None else _shares_from_config_paths()
    return _shares_from_config_paths()


def share_for(path: str, runner: Runner = None) -> GcpShare | None:
    """The share covering ``path``, longest match first, or ``None``.

    Longest match, because a nested share is the one whose terms apply: a
    read-only ``$HOME`` with a writable project directory inside it means the
    project directory is writable, and answering with ``$HOME`` would warn
    about a problem that is not there.
    """
    available = shares(runner)
    if not available:
        return None
    target = Path(path).expanduser()
    covering = [
        share
        for share in available
        if target == Path(share.path) or Path(share.path) in target.parents
    ]
    if not covering:
        return None
    return max(covering, key=lambda share: len(share.path))


def is_running(runner: Runner = None) -> bool | None:
    """Whether the background service is up, or ``None`` if it cannot be told.

    Checked by looking for the process, which works the same whether the user
    started the menu-bar app or the headless ``globusconnectpersonal -start``.
    """
    run = runner or subprocess.run
    try:
        proc = run(
            ["pgrep", "-f", "globusconnectpersonal|Globus Connect Personal"],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode == 0
