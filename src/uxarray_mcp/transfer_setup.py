"""``uxarray-mcp transfer setup`` -- get Globus data movement working, once.

Seven things have to be true before a file can move between this machine and a
cluster, and Globus reports the failure of each one differently and none of
them plainly. Getting from nothing to a working transfer by hand means finding
out about them in the worst order: the collection UUID that is in a file nobody
mentions, the consent scope that exists for one kind of collection and not
another, the share on this machine whose write bit is clear by default, and the
identity policy that only speaks up after a transfer has been submitted.

So this asks all seven up front, says which are already true, and offers to fix
the rest. It is deliberately close to a shell script: prompts, one line of
output per step, and no state of its own. Anything it changes it names first.

What it does *not* do is authenticate. Every credential step is handed to the
``globus`` command-line client, running attached to this terminal so its
browser flow works. Nothing here stores a token.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from uxarray_mcp.remote import gcp

__all__ = [
    "KNOWN_COLLECTIONS",
    "KnownCollection",
    "TransferSetup",
    "cmd_transfer_setup",
]


@dataclass(frozen=True)
class KnownCollection:
    """A facility collection whose UUID is a fact, not a per-user setting."""

    label: str
    collection_id: str
    collection_roots: tuple[str, ...] = ()
    default_read_root: str | None = None


# Searching for these is a poor substitute for stating them. Facilities publish
# a guest collection per project, and users publish their own, so a name search
# for "Chrysalis" or "GLADE" returns a page of look-alikes with no way to tell
# which one serves the filesystem the compute endpoint runs on. Each entry below
# was confirmed against a live listing.
KNOWN_COLLECTIONS: dict[str, KnownCollection] = {
    "ncar": KnownCollection(
        label="NCAR GLADE",
        collection_id="d33b3614-6d04-11e5-ba46-22000b92c6ec",
        # GLADE names files by their real filesystem path, so nothing to translate.
        collection_roots=(),
        default_read_root="/glade",
    ),
    "polaris": KnownCollection(
        label="ALCF Polaris (alcf#dtn_eagle)",
        collection_id="05d2c76a-e867-4f67-aa57-76edeb0beda0",
        collection_roots=("/eagle", "/lus/eagle/projects"),
    ),
    "aurora": KnownCollection(
        label="ALCF Aurora (ALCF Flare)",
        collection_id="f39a7a0f-5bfc-46ce-9615-ba9f8592814f",
        collection_roots=("/flare", "/lus/flare/projects"),
    ),
    "perlmutter": KnownCollection(
        label="NERSC DTN",
        collection_id="9d6d994a-6d04-11e5-ba46-22000b92c6ec",
    ),
}

# Endpoint names people actually use, mapped to the table above. An endpoint
# whose name matches nothing here just gets asked about.
_NAME_HINTS: tuple[tuple[str, str], ...] = (
    ("ucar", "ncar"),
    ("ncar", "ncar"),
    ("glade", "ncar"),
    ("derecho", "ncar"),
    ("casper", "ncar"),
    ("polaris", "polaris"),
    ("eagle", "polaris"),
    ("aurora", "aurora"),
    ("flare", "aurora"),
    ("perlmutter", "perlmutter"),
    ("nersc", "perlmutter"),
)

_CONSENT_SCOPE = (
    "urn:globus:auth:scope:transfer.api.globus.org:all"
    "[*https://auth.globus.org/scopes/{collection_id}/data_access]"
)


def known_collection_for(endpoint_name: str | None) -> KnownCollection | None:
    """Guess the facility collection from an endpoint's name."""
    if not endpoint_name:
        return None
    lowered = endpoint_name.lower()
    for hint, key in _NAME_HINTS:
        if hint in lowered:
            return KNOWN_COLLECTIONS[key]
    return None


@dataclass
class StepResult:
    """One line of the report: what was checked and how it came out."""

    title: str
    ok: bool
    detail: str = ""
    fix: str = ""

    def render(self) -> str:
        mark = "ok  " if self.ok else "TODO"
        line = f"  [{mark}] {self.title}"
        if self.detail:
            line += f" -- {self.detail}"
        if not self.ok and self.fix:
            line += f"\n         fix: {self.fix}"
        return line


@dataclass
class TransferSetup:
    """The seven checks, and the offers to fix them.

    ``runner``, ``prompt`` and ``emit`` are injected so every path through this
    can be tested with no binary, no network and no terminal.
    """

    endpoint: str | None = None
    check_only: bool = False
    assume_yes: bool = False
    runner: Callable[..., Any] = subprocess.run
    prompt: Callable[[str], str] = input
    emit: Callable[[str], None] = print
    results: list[StepResult] = field(default_factory=list)

    # -- primitives ----------------------------------------------------

    def _record(self, title: str, ok: bool, detail: str = "", fix: str = "") -> bool:
        result = StepResult(title=title, ok=ok, detail=detail, fix=fix)
        self.results.append(result)
        self.emit(result.render())
        return ok

    def _confirm(self, question: str) -> bool:
        """Ask before changing anything. ``--check`` never changes anything."""
        if self.check_only:
            return False
        if self.assume_yes:
            return True
        try:
            answer = self.prompt(f"         {question} [Y/n] ").strip().lower()
        except EOFError:
            return False
        return answer in ("", "y", "yes")

    def _ask(self, question: str, default: str = "") -> str:
        if self.check_only or self.assume_yes:
            return default
        try:
            answer = self.prompt(f"         {question}").strip()
        except EOFError:
            return default
        return answer or default

    def _capture(self, argv: list[str], timeout: int = 120) -> tuple[int, str, str]:
        try:
            proc = self.runner(
                argv, capture_output=True, text=True, timeout=timeout, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, "", str(exc)
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()

    def _interactive(self, argv: list[str]) -> int:
        """Run a command attached to this terminal.

        Login and consent print a URL and wait for a pasted code. Capturing
        their output would hide the URL and hang on the prompt, so these are the
        one kind of command that must not be captured.
        """
        self.emit(f"         running: {' '.join(argv)}")
        try:
            proc = self.runner(argv, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            self.emit(f"         failed: {exc}")
            return 1
        return int(getattr(proc, "returncode", 1))

    # -- 1. the CLI ----------------------------------------------------

    def find_cli(self) -> str | None:
        from uxarray_mcp.remote.transfer import TransferError, find_globus_cli

        try:
            return find_globus_cli()
        except TransferError:
            return None

    def step_cli(self) -> str | None:
        found = self.find_cli()
        if found:
            self._record("globus CLI", True, found)
            return found
        self._record(
            "globus CLI",
            False,
            "not installed",
            "pip install globus-cli",
        )
        if not self._confirm("install globus-cli now?"):
            return None
        if self._interactive([sys.executable, "-m", "pip", "install", "globus-cli"]):
            self.emit("         install failed; install it by hand and re-run.")
            return None
        found = self.find_cli()
        self.emit(
            f"         installed: {found}" if found else "         still not found"
        )
        return found

    # -- 2. login ------------------------------------------------------

    def step_login(self, cli: str) -> bool:
        code, out, _ = self._capture([cli, "whoami"], timeout=60)
        if code == 0 and out:
            return self._record("globus login", True, out)
        self._record("globus login", False, "not logged in", "globus login")
        if not self._confirm("log in now? A browser opens; paste the code back."):
            return False
        if self._interactive([cli, "login"]):
            return False
        code, out, _ = self._capture([cli, "whoami"], timeout=60)
        if code == 0 and out:
            self.emit(f"         logged in as {out}")
            return True
        return False

    # -- 3. this machine's Globus Connect Personal ----------------------

    def step_gcp(self, local_root: str | None) -> None:
        running = gcp.is_running()
        if running is None:
            self._record(
                "Globus Connect Personal", False, "cannot tell if it is running"
            )
        elif running:
            self._record("Globus Connect Personal", True, "running")
        else:
            self._record(
                "Globus Connect Personal",
                False,
                "not running -- transfers to and from this machine will fail",
                "start it from the menu bar, or `globusconnectpersonal -start`",
            )
        self._step_gcp_share(local_root)

    def _step_gcp_share(self, local_root: str | None) -> None:
        """The write bit. The default share is read-only and nothing says so."""
        target = local_root or str(Path.home())
        share = gcp.share_for(target)
        if share is None:
            self._record(
                f"{target} shared",
                False,
                "not in Globus Connect Personal's shared paths",
                "Preferences -> Access -> + , add it and tick Writable",
            )
            return
        if share.writable:
            self._record(f"{target} writable", True, f"covered by {share.path}")
            return
        self._record(
            f"{target} writable",
            False,
            f"{share.path} is shared READ-ONLY, so downloads here will be refused",
            self._share_fix(share.path),
        )

    @staticmethod
    def _share_fix(share_path: str) -> str:
        if sys.platform == "darwin":
            # Flipping this in the preferences plist by hand does not take
            # effect until the app rewrites it, and the app is what owns the
            # file -- so this is the supported route, and the only honest one.
            return (
                "Globus Connect Personal -> Preferences -> Access, "
                f"select {share_path}, tick Writable, then restart it"
            )
        return (
            f"add a writable entry to {gcp.config_paths_file()} "
            f"(e.g. `{share_path}/,0,1`), then restart globusconnectpersonal"
        )

    # -- 4. which collection is this machine ----------------------------

    def step_local_collection(self, cli: str) -> str | None:
        found = gcp.collection_id()
        if found:
            self._record("this machine's collection", True, found)
            return found
        code, out, _ = self._capture(
            [
                cli,
                "endpoint",
                "search",
                "--filter-scope",
                "my-endpoints",
                "--format",
                "unix",
                "--jmespath",
                "DATA[].[id,display_name]",
            ]
        )
        if code == 0 and out:
            self.emit("         collections you own:")
            for line in out.splitlines():
                self.emit(f"           {line}")
        entered = self._ask("this machine's collection UUID (blank to skip): ")
        if entered:
            self._record("this machine's collection", True, entered)
            return entered
        self._record(
            "this machine's collection",
            False,
            "unknown",
            "install Globus Connect Personal, or paste its UUID",
        )
        return None

    # -- 5. the facility's collection -----------------------------------

    def step_remote_collection(self) -> KnownCollection | None:
        known = known_collection_for(self.endpoint)
        if known:
            self._record(
                "facility collection", True, f"{known.label}  {known.collection_id}"
            )
            return known
        entered = self._ask(
            f"collection UUID for {self.endpoint or 'this endpoint'} "
            f"(find it under Collections in the Globus web app): "
        )
        if entered:
            self._record("facility collection", True, entered)
            return KnownCollection(
                label=self.endpoint or "endpoint", collection_id=entered
            )
        self._record(
            "facility collection",
            False,
            "unknown",
            "look it up under Collections at app.globus.org and re-run",
        )
        return None

    # -- 6. consent ------------------------------------------------------

    def step_consent(self, cli: str, collection_id: str, probe_path: str) -> bool:
        """Prove the consent by using it, then ask for it if that failed.

        A listing is the probe because it is the cheapest thing that exercises
        the whole chain -- token, consent, the collection's own identity policy,
        and the path -- and moves nothing.
        """
        code, _, err = self._capture([cli, "ls", f"{collection_id}:{probe_path}"])
        if code == 0:
            return self._record("consent", True, f"listed {probe_path}")
        scope = _CONSENT_SCOPE.format(collection_id=collection_id)
        self._record(
            "consent", False, _first_line(err), f"globus session consent '{scope}'"
        )
        if not self._confirm("request consent now? A browser opens."):
            return False
        # The local collection is deliberately absent from this. Only Globus
        # Connect Server v5 collections have a data_access scope; asking for one
        # on a Globus Connect Personal collection fails with UNKNOWN_SCOPE_ERROR
        # and leaves the login looking permanently incomplete.
        if self._interactive([cli, "session", "consent", scope]):
            return False
        code, _, err = self._capture([cli, "ls", f"{collection_id}:{probe_path}"])
        if code == 0:
            self.emit(f"         consent granted; {probe_path} lists")
            return True
        self.emit(f"         still refused: {_first_line(err)}")
        return False

    # -- report ----------------------------------------------------------

    def summary(self) -> tuple[int, int]:
        done = sum(1 for r in self.results if r.ok)
        return done, len(self.results)

    # -- 7. write it down -------------------------------------------------

    def step_config(
        self,
        remote: KnownCollection,
        local_collection: str | None,
        write_root: str | None,
        local_root: str | None,
    ) -> bool:
        """Put the answers in the user config so nobody has to find them twice."""
        from uxarray_mcp.cli import (
            _ensure_hpc_block,
            _read_user_config,
            _user_write_target,
            _write_user_config,
        )

        if not self.endpoint:
            self._record(
                "config", False, "no endpoint named", "re-run with --endpoint NAME"
            )
            return False
        block: dict[str, Any] = {"remote_collection_id": remote.collection_id}
        if local_collection:
            block["local_collection_id"] = local_collection
        if write_root:
            block["remote_write_root"] = write_root
        if remote.default_read_root:
            block["remote_read_root"] = remote.default_read_root
        if remote.collection_roots:
            block["collection_roots"] = list(remote.collection_roots)
        if local_root:
            block["local_root"] = local_root

        target = _user_write_target()
        data = _read_user_config(target)
        hpc = _ensure_hpc_block(data)
        endpoints = hpc["endpoints"]
        existing = endpoints.get(self.endpoint)
        if not isinstance(existing, dict):
            self._record(
                "config",
                False,
                f"{self.endpoint} is not in {target}",
                f"uxarray-mcp endpoints add {self.endpoint} <compute-endpoint-uuid>",
            )
            return False
        current = existing.get("globus_transfer")
        if current == block:
            return self._record("config", True, f"already set in {target}")
        # A --check run never asked for the write root, so it cannot have built
        # a block equal to a good one. Judging what is there on its own terms is
        # the only thing that is not a false alarm.
        if self.check_only:
            configured = isinstance(current, dict) and current.get(
                "remote_collection_id"
            )
            return self._record(
                "config",
                bool(configured),
                f"{self.endpoint} in {target}"
                if configured
                else f"{self.endpoint} has no globus_transfer block",
                "" if configured else "run this again without --check",
            )
        for key, value in block.items():
            self.emit(f"           {key}: {value}")
        if not self._confirm(f"write this to {target}?"):
            self._record(
                "config", False, "not written", f"add the block above to {target}"
            )
            return False
        existing["globus_transfer"] = block
        _write_user_config(target, data)
        return self._record("config", True, f"written to {target}")

    # -- the whole thing --------------------------------------------------

    def run(self) -> int:
        """Every step in order. Returns a process exit code."""
        self.emit(
            "Globus Transfer moves files. It is a separate service from Globus\n"
            "Compute, with separate logins and separate consents -- being able to\n"
            "run a job on a machine does not let you copy a file to it.\n"
        )
        cli = self.step_cli()
        if not cli:
            return self._finish()
        logged_in = self.step_login(cli)
        # Not logged in stops the fixing but not the reporting: the Globus
        # Connect Personal checks below read local files and are the ones most
        # likely to be quietly wrong, so a `--check` run should still show them.
        if not logged_in and not self.check_only:
            return self._finish()

        remote = self.step_remote_collection()
        write_root = None
        if remote and logged_in:
            default_root = remote.default_read_root or ""
            write_root = self._ask(
                f"writable directory on {remote.label} "
                f"(e.g. /glade/derecho/scratch/$USER){f' [{default_root}]' if default_root else ''}: ",
                default_root,
            )
            probe = write_root or "/"
            self.step_consent(cli, remote.collection_id, probe)

        local_root = self._ask(
            f"directory on this machine transfers may touch [{Path.home()}]: ",
            str(Path.home()),
        )
        self.step_gcp(local_root)
        local_collection = self.step_local_collection(cli)

        if remote:
            self.step_config(remote, local_collection, write_root or None, local_root)
        return self._finish()

    def _finish(self) -> int:
        done, total = self.summary()
        self.emit(f"\n{done}/{total} checks pass.")
        if done == total:
            self.emit("Transfers should work. Try `transfer_ls` from the MCP client.")
            return 0
        self.emit("Fix the TODO lines above, then run this again.")
        return 1


def cmd_transfer_setup(args: argparse.Namespace) -> int:
    """``uxarray-mcp transfer setup`` -- see :class:`TransferSetup`."""
    setup = TransferSetup(
        endpoint=getattr(args, "endpoint", None),
        check_only=bool(getattr(args, "check", False)),
        assume_yes=bool(getattr(args, "yes", False)),
    )
    return setup.run()


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:200]
    return "failed"
