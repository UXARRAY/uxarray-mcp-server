"""Path safety for Globus transfers, checked with no credentials anywhere.

Every test here drives a fake client. That is not a shortcut around an
integration test -- a transfer moves real files under the user's real
allocation, so the only version of "did the path arithmetic hold" worth
running on every commit is one that cannot touch a network. The real
`ls`/`put`/`get` against Chrysalis and UCAR are a hand check, once, by a human
who can look at what landed.

Each case below is a way the obvious implementation is wrong while still
looking right.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from uxarray_mcp.remote.config import GlobusTransferProfile
from uxarray_mcp.remote.transfer import (
    CliTransferClient,
    PathOutsideRoot,
    TransferError,
    TransferLoginRequired,
    TransferNotConfigured,
    TransferService,
    bounded_preview,
    collapse,
    find_globus_cli,
    is_within,
    join_under,
    resolve_local,
    to_collection_path,
)


class FakeTransferClient:
    """Records what it was asked to do; invents nothing it was not given."""

    def __init__(self, ls_entries=None, task=None):
        self.ls_entries = ls_entries or []
        self.task = task or {}
        self.submitted: list[dict] = []
        self.ls_calls: list[tuple[str, str]] = []
        self.submission_ids = 0

    def operation_ls(self, collection_id, **kwargs):
        self.ls_calls.append((collection_id, kwargs.get("path")))
        return {"DATA": self.ls_entries}

    def get_submission_id(self):
        self.submission_ids += 1
        return {"value": f"submission-{self.submission_ids}"}

    def submit_transfer(self, data):
        self.submitted.append(data)
        return {"task_id": "task-1", "code": "Accepted"}

    def get_task(self, task_id):
        return {"status": "SUCCEEDED", "bytes_transferred": 12, **self.task}


def _profile(**overrides) -> GlobusTransferProfile:
    base = {
        "remote_collection_id": "remote-uuid",
        "local_collection_id": "local-uuid",
        "remote_write_root": "/scratch/rjain",
        "remote_read_root": "/lcrc/group/e3sm",
        "collection_roots": (),
    }
    base.update(overrides)
    return GlobusTransferProfile(**base)


class TestAPrefixIsNotAPathBoundary:
    """`"/work/ab".startswith("/work/a")` is True and that is the whole bug."""

    def test_a_sibling_sharing_a_prefix_is_not_inside(self):
        assert not is_within("/work/a", "/work/ab")

    def test_a_real_child_is_inside(self):
        assert is_within("/work/a", "/work/a/b")

    def test_a_root_contains_itself(self):
        assert is_within("/work/a", "/work/a")

    def test_a_parent_is_not_inside_its_child(self):
        assert not is_within("/work/a/b", "/work/a")

    def test_the_sibling_is_refused_by_join_too(self):
        with pytest.raises(PathOutsideRoot):
            join_under("/work/a", "/work/ab/out.nc")


class TestAnAbsoluteSecondArgumentDoesNotEscape:
    """`os.path.join("/scratch/me", "/etc/passwd")` returns `/etc/passwd`."""

    def test_an_absolute_path_outside_the_root_is_refused(self):
        with pytest.raises(PathOutsideRoot) as excinfo:
            join_under("/scratch/me", "/etc/passwd")
        assert "/etc/passwd" in str(excinfo.value)

    def test_an_absolute_path_inside_the_root_is_kept_not_re_rooted(self):
        assert join_under("/scratch/me", "/scratch/me/out.nc") == "/scratch/me/out.nc"

    def test_a_relative_path_is_joined(self):
        assert join_under("/scratch/me", "runs/out.nc") == "/scratch/me/runs/out.nc"

    def test_a_relative_root_is_refused_outright(self):
        with pytest.raises(PathOutsideRoot):
            join_under("scratch/me", "out.nc")


class TestDotDotIsResolvedBeforeContainmentNotAfter:
    """A remote path cannot be realpath'd, so `..` is collapsed textually."""

    def test_climbing_out_of_the_root_is_refused(self):
        with pytest.raises(PathOutsideRoot):
            join_under("/scratch/me", "../../etc/passwd")

    def test_climbing_and_returning_stays_inside(self):
        assert join_under("/scratch/me", "runs/../out.nc") == "/scratch/me/out.nc"

    def test_an_absolute_path_that_only_looks_inside_is_refused(self):
        with pytest.raises(PathOutsideRoot):
            join_under("/scratch/me", "/scratch/me/../../etc/passwd")

    def test_dot_segments_vanish(self):
        assert collapse("/a/./b/./c") == "/a/b/c"

    def test_dotdot_at_the_top_cannot_climb_past_root(self):
        assert collapse("/../../etc") == "/etc"


class TestALocalSymlinkIsFollowedBeforeTheCheck:
    """Checked after resolution: a link inside the root can point out of it."""

    def test_a_link_pointing_outside_the_root_is_refused(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.nc").write_text("x")
        root = tmp_path / "root"
        root.mkdir()
        link = root / "escape"
        os.symlink(outside, link)
        with pytest.raises(PathOutsideRoot):
            resolve_local(link / "secret.nc", str(root))

    def test_a_real_file_inside_the_root_resolves(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        target = root / "mesh.nc"
        target.write_text("x")
        assert resolve_local(target, str(root)) == target.resolve()

    def test_a_destination_that_does_not_exist_yet_still_resolves(self, tmp_path):
        assert (
            resolve_local(tmp_path / "not-yet.nc", str(tmp_path)).name == "not-yet.nc"
        )

    def test_without_a_root_nothing_is_refused(self, tmp_path):
        assert resolve_local(tmp_path / "anything.nc").is_absolute()


class TestACollectionNamesPathsItsOwnWay:
    """A collection exposing a subtree calls that subtree `/`."""

    def test_a_path_under_a_root_is_expressed_relative_to_it(self):
        assert (
            to_collection_path("/lcrc/group/e3sm/run/out.nc", ("/lcrc/group/e3sm",))
            == "/run/out.nc"
        )

    def test_the_root_itself_becomes_slash(self):
        assert to_collection_path("/lcrc/group/e3sm", ("/lcrc/group/e3sm",)) == "/"

    def test_the_longest_root_wins_regardless_of_order(self):
        roots = ("/lcrc", "/lcrc/group/e3sm")
        assert to_collection_path("/lcrc/group/e3sm/out.nc", roots) == "/out.nc"
        assert to_collection_path("/lcrc/group/e3sm/out.nc", roots[::-1]) == "/out.nc"

    def test_an_unmatched_path_passes_through_unchanged(self):
        # Globus rejecting a path it does not recognize is a clear failure; a
        # path rewritten under the wrong root names a real file nobody asked
        # about.
        assert (
            to_collection_path("/home/rjain/out.nc", ("/lcrc",)) == "/home/rjain/out.nc"
        )

    def test_a_prefix_sibling_does_not_match_a_root(self):
        assert to_collection_path("/lcrcx/out.nc", ("/lcrc",)) == "/lcrcx/out.nc"

    def test_no_roots_means_no_translation(self):
        assert to_collection_path("/scratch/me/out.nc") == "/scratch/me/out.nc"


class TestAPreviewSaysHowMuchItLeftOut:
    def test_a_short_file_is_returned_whole(self, tmp_path):
        path = tmp_path / "small.txt"
        path.write_text("hello")
        assert bounded_preview(path) == "hello"

    def test_a_long_file_reports_the_omitted_byte_count(self, tmp_path):
        path = tmp_path / "big.txt"
        path.write_bytes(b"a" * 5000)
        preview = bounded_preview(path, head_bytes=100, tail_bytes=50)
        assert "4850 of 5000 bytes omitted" in preview
        assert len(preview) < 5000

    def test_both_ends_survive(self, tmp_path):
        path = tmp_path / "ends.txt"
        path.write_bytes(b"HEAD" + b"." * 5000 + b"TAIL")
        preview = bounded_preview(path, head_bytes=10, tail_bytes=10)
        assert preview.startswith("HEAD")
        assert preview.endswith("TAIL")

    def test_undecodable_bytes_do_not_raise(self, tmp_path):
        path = tmp_path / "binary.nc"
        path.write_bytes(b"\x89HDF\r\n\x1a\n\xff\xfe")
        assert "HDF" in bounded_preview(path)


class TestTheRootsAreEnforcedOnEveryTransfer:
    def test_an_upload_lands_under_the_write_root(self, tmp_path):
        source = tmp_path / "mesh.nc"
        source.write_text("x")
        service = TransferService(_profile(), FakeTransferClient())
        plan = service.plan_put(source, "runs/mesh.nc")
        assert plan.destination_path == "/scratch/rjain/runs/mesh.nc"
        assert plan.source_path == str(source.resolve())
        assert plan.recursive is False

    def test_an_upload_outside_the_write_root_is_refused(self, tmp_path):
        source = tmp_path / "mesh.nc"
        source.write_text("x")
        service = TransferService(_profile(), FakeTransferClient())
        with pytest.raises(PathOutsideRoot):
            service.plan_put(source, "/etc/passwd")

    def test_an_upload_of_a_missing_file_is_refused_before_the_network(self, tmp_path):
        client = FakeTransferClient()
        service = TransferService(_profile(), client)
        with pytest.raises(TransferError):
            service.plan_put(tmp_path / "gone.nc", "runs/mesh.nc")
        assert client.submitted == []

    def test_a_directory_upload_is_marked_recursive(self, tmp_path):
        source = tmp_path / "run"
        source.mkdir()
        service = TransferService(_profile(), FakeTransferClient())
        assert service.plan_put(source, "runs/").recursive is True

    def test_a_download_reads_under_the_read_root(self, tmp_path):
        service = TransferService(_profile(), FakeTransferClient())
        plan = service.plan_get("cases/out.nc", tmp_path / "out.nc")
        assert plan.source_path == "/lcrc/group/e3sm/cases/out.nc"

    def test_the_write_root_is_readable_too(self, tmp_path):
        # Somewhere you may put a file is somewhere you may look at one: a
        # download of what was just uploaded must not fail on the read root.
        service = TransferService(_profile(), FakeTransferClient())
        plan = service.plan_get("/scratch/rjain/out.nc", tmp_path / "out.nc")
        assert plan.source_path == "/scratch/rjain/out.nc"

    def test_a_path_under_no_readable_root_names_them_all(self, tmp_path):
        service = TransferService(_profile(), FakeTransferClient())
        with pytest.raises(PathOutsideRoot) as excinfo:
            service.plan_get("/home/rjain/out.nc", tmp_path / "out.nc")
        assert "/scratch/rjain" in str(excinfo.value)
        assert "/lcrc/group/e3sm" in str(excinfo.value)

    def test_a_read_root_does_not_widen_writes(self, tmp_path):
        source = tmp_path / "mesh.nc"
        source.write_text("x")
        service = TransferService(_profile(), FakeTransferClient())
        with pytest.raises(PathOutsideRoot):
            service.plan_put(source, "/lcrc/group/e3sm/mesh.nc")

    def test_without_a_read_root_reads_fall_back_to_the_write_root(self, tmp_path):
        service = TransferService(_profile(remote_read_root=None), FakeTransferClient())
        assert (
            service.plan_get("out.nc", tmp_path).source_path == "/scratch/rjain/out.nc"
        )
        with pytest.raises(PathOutsideRoot):
            service.plan_get("/lcrc/group/e3sm/out.nc", tmp_path)

    def test_a_download_destination_outside_the_local_root_is_refused(self, tmp_path):
        allowed = tmp_path / "downloads"
        allowed.mkdir()
        service = TransferService(
            _profile(local_root=str(allowed)), FakeTransferClient()
        )
        with pytest.raises(PathOutsideRoot):
            service.plan_get("cases/out.nc", tmp_path / "elsewhere.nc")

    def test_collection_translation_applies_to_the_submitted_path(self, tmp_path):
        source = tmp_path / "mesh.nc"
        source.write_text("x")
        service = TransferService(
            _profile(collection_roots=("/scratch",)), FakeTransferClient()
        )
        plan = service.plan_put(source, "runs/mesh.nc")
        assert plan.destination_path == "/rjain/runs/mesh.nc"


class TestAnEndpointWithoutTheBlockMovesNoFiles:
    def test_no_write_root_refuses_rather_than_defaulting(self, tmp_path):
        source = tmp_path / "mesh.nc"
        source.write_text("x")
        service = TransferService(
            _profile(remote_write_root=None, remote_read_root=None),
            FakeTransferClient(),
        )
        with pytest.raises(TransferNotConfigured):
            service.plan_put(source, "mesh.nc")

    def test_no_local_collection_says_what_is_missing(self, tmp_path):
        source = tmp_path / "mesh.nc"
        source.write_text("x")
        service = TransferService(
            _profile(local_collection_id=None), FakeTransferClient()
        )
        with pytest.raises(TransferNotConfigured) as excinfo:
            service.plan_put(source, "mesh.nc")
        assert "local_collection_id" in str(excinfo.value)


class TestTheSubmittedPayloadSaysWhatItDoes:
    def test_a_submission_id_is_fetched_and_carried(self, tmp_path):
        source = tmp_path / "mesh.nc"
        source.write_text("x")
        client = FakeTransferClient()
        result = TransferService(_profile(), client).put(source, "runs/mesh.nc")
        payload = client.submitted[0]
        assert client.submission_ids == 1
        assert payload["submission_id"] == "submission-1"
        assert payload["source_endpoint"] == "local-uuid"
        assert payload["destination_endpoint"] == "remote-uuid"
        assert payload["DATA"][0]["destination_path"] == "/scratch/rjain/runs/mesh.nc"
        assert result["task_id"] == "task-1"

    def test_checksums_are_verified_and_mail_is_not_sent(self, tmp_path):
        source = tmp_path / "mesh.nc"
        source.write_text("x")
        client = FakeTransferClient()
        TransferService(_profile(), client).put(source, "runs/mesh.nc")
        payload = client.submitted[0]
        assert payload["verify_checksum"] is True
        assert payload["notify_on_succeeded"] is False
        assert payload["notify_on_failed"] is False

    def test_a_download_reverses_the_two_collections(self, tmp_path):
        client = FakeTransferClient()
        TransferService(_profile(), client).get("cases/out.nc", tmp_path / "out.nc")
        payload = client.submitted[0]
        assert payload["source_endpoint"] == "remote-uuid"
        assert payload["destination_endpoint"] == "local-uuid"

    def test_a_listing_goes_through_the_read_root(self):
        client = FakeTransferClient(
            ls_entries=[{"name": "out.nc", "type": "file", "size": 12}]
        )
        entries = TransferService(_profile(), client).ls("cases")
        assert client.ls_calls == [("remote-uuid", "/lcrc/group/e3sm/cases")]
        assert entries == [
            {"name": "out.nc", "type": "file", "size": 12, "last_modified": None}
        ]

    def test_status_reports_what_the_task_says(self):
        client = FakeTransferClient(task={"files_transferred": 3})
        status = TransferService(_profile(), client).status("task-1")
        assert status["status"] == "SUCCEEDED"
        assert status["files_transferred"] == 3
        assert status["fatal_error"] is None


class FakeProcess:
    """What ``subprocess.run`` returns, with nothing else attached."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    """Answers ``globus`` invocations from a table keyed on the first argument."""

    def __init__(self, replies):
        self.replies = replies
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        for key, reply in self.replies.items():
            if key in argv:
                return reply
        return FakeProcess(1, stderr=f"no fake reply for {argv}")


def _cli(replies):
    return CliTransferClient("/fake/globus", runner=FakeRunner(replies))


class TestTheCliIsAskedForMachineReadableOutput:
    """Every call parses stdout, so every call must have asked for JSON.

    A missing ``--format json`` does not fail; it returns the human table,
    which parses as nothing and surfaces as a bad-output error a long way from
    the flag that caused it.
    """

    def test_a_listing_names_the_collection_and_path_as_one_argument(self):
        client = _cli({"ls": FakeProcess(stdout='{"DATA": [{"name": "a.nc"}]}')})
        result = client.operation_ls("coll-1", path="/scratch")
        assert result == {"DATA": [{"name": "a.nc"}]}
        argv = client._runner.calls[0]
        assert argv[:2] == ["/fake/globus", "ls"]
        assert "coll-1:/scratch" in argv
        assert "--format" in argv and "json" in argv

    def test_a_listing_with_no_path_asks_for_the_collection_root(self):
        client = _cli({"ls": FakeProcess(stdout="{}")})
        client.operation_ls("coll-1")
        assert "coll-1:/" in client._runner.calls[0]

    def test_a_task_lookup_asks_for_json(self):
        client = _cli({"task": FakeProcess(stdout='{"status": "SUCCEEDED"}')})
        assert client.get_task("t-1") == {"status": "SUCCEEDED"}
        argv = client._runner.calls[0]
        assert argv[1:3] == ["task", "show"]
        assert argv[-1] == "t-1"


class TestASubmissionBecomesOneTransferCommand:
    """The payload is the wire shape; the CLI takes flags. Something translates."""

    def test_the_two_endpoints_and_paths_become_two_colon_arguments(self):
        client = _cli({"transfer": FakeProcess(stdout='{"task_id": "t-9"}')})
        result = client.submit_transfer(
            {
                "source_endpoint": "src",
                "destination_endpoint": "dst",
                "DATA": [{"source_path": "/a/x.nc", "destination_path": "/b/x.nc"}],
            }
        )
        assert result == {"task_id": "t-9"}
        argv = client._runner.calls[0]
        assert "src:/a/x.nc" in argv
        assert "dst:/b/x.nc" in argv
        assert argv[argv.index("--notify") + 1] == "off"

    def test_a_recursive_item_becomes_the_recursive_flag(self):
        client = _cli({"transfer": FakeProcess(stdout='{"task_id": "t"}')})
        client.submit_transfer(
            {
                "source_endpoint": "src",
                "destination_endpoint": "dst",
                "DATA": [
                    {
                        "source_path": "/a",
                        "destination_path": "/b",
                        "recursive": True,
                    }
                ],
            }
        )
        assert "--recursive" in client._runner.calls[0]

    def test_checksums_are_only_mentioned_when_they_are_turned_off(self):
        """Verifying is the CLI's default, so saying so again is noise.

        Saying nothing when the payload asks for verification is only correct
        while that stays the default, which is why the opposite case is the one
        spelled out on the command line.
        """
        on = _cli({"transfer": FakeProcess(stdout="{}")})
        on.submit_transfer(
            {
                "source_endpoint": "s",
                "destination_endpoint": "d",
                "verify_checksum": True,
                "DATA": [{"source_path": "/a", "destination_path": "/b"}],
            }
        )
        assert "--no-verify-checksum" not in on._runner.calls[0]

        off = _cli({"transfer": FakeProcess(stdout="{}")})
        off.submit_transfer(
            {
                "source_endpoint": "s",
                "destination_endpoint": "d",
                "verify_checksum": False,
                "DATA": [{"source_path": "/a", "destination_path": "/b"}],
            }
        )
        assert "--no-verify-checksum" in off._runner.calls[0]

    def test_a_batch_is_refused_rather_than_silently_truncated(self):
        """One command moves one thing. Sending the first of several is worse
        than sending none, because the caller is told it succeeded."""
        client = _cli({"transfer": FakeProcess(stdout="{}")})
        with pytest.raises(TransferError):
            client.submit_transfer(
                {
                    "source_endpoint": "s",
                    "destination_endpoint": "d",
                    "DATA": [
                        {"source_path": "/a", "destination_path": "/b"},
                        {"source_path": "/c", "destination_path": "/d"},
                    ],
                }
            )


class TestAnAuthFailureIsToldApartFromEveryOtherFailure:
    """Three unrelated-looking Globus errors all mean "go to a terminal".

    Missing tokens, a missing ``data_access`` consent, and an identity a
    collection's policy refuses are reported by three different subsystems in
    three different shapes, and the fix for all three is the same. Anything
    else -- a path that is not there, a collection that is down -- must not be
    dressed up as a login problem, because that sends the user to a browser to
    fix something a browser cannot fix.
    """

    @pytest.mark.parametrize(
        "stderr",
        [
            "MissingLoginError: Missing login for Globus Auth.",
            "The collection requires ConsentRequired for data_access",
            "session_required_single_domain: ncar.edu",
        ],
    )
    def test_a_credential_failure_asks_for_a_terminal(self, stderr):
        client = _cli({"ls": FakeProcess(1, stderr=stderr)})
        with pytest.raises(TransferLoginRequired) as caught:
            client.operation_ls("coll-1")
        assert "transfer setup" in str(caught.value)

    def test_a_missing_path_stays_a_plain_error(self):
        client = _cli({"ls": FakeProcess(1, stderr="Directory not found: /nope")})
        with pytest.raises(TransferError) as caught:
            client.operation_ls("coll-1", path="/nope")
        assert not isinstance(caught.value, TransferLoginRequired)
        assert "/nope" in str(caught.value)

    def test_the_failing_command_is_quoted_back(self):
        """Whatever went wrong, the user can retype the line and see it too."""
        client = _cli({"ls": FakeProcess(1, stderr="boom")})
        with pytest.raises(TransferError) as caught:
            client.operation_ls("coll-1", path="/x")
        assert "globus ls" in str(caught.value)
        assert "coll-1:/x" in str(caught.value)


class TestOutputThatIsNotJson:
    def test_unparseable_output_names_the_command_rather_than_the_parser(self):
        client = _cli({"task": FakeProcess(stdout="Task ID: t-1\nStatus: OK\n")})
        with pytest.raises(TransferError) as caught:
            client.get_task("t-1")
        assert "globus task show" in str(caught.value)

    def test_a_hung_command_is_given_up_on(self):
        def hang(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 5)

        client = CliTransferClient("/fake/globus", timeout_seconds=5, runner=hang)
        with pytest.raises(TransferError) as caught:
            client.whoami()
        assert "5 seconds" in str(caught.value)


class TestFindingTheBinary:
    """An MCP server started from a GUI has no shell PATH.

    ``shutil.which`` is the whole answer in a terminal and no answer at all in
    Claude Desktop, which is where most of these installs run.
    """

    def test_the_path_is_used_when_it_has_one(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/globus")
        assert find_globus_cli() == "/usr/bin/globus"

    def test_the_interpreter_prefix_is_searched_when_the_path_has_none(
        self, monkeypatch, tmp_path
    ):
        binary = tmp_path / "bin" / "globus"
        binary.parent.mkdir()
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        assert find_globus_cli() == str(binary)

    def test_an_absent_binary_says_how_to_get_one(self, monkeypatch, tmp_path):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        with pytest.raises(TransferError) as caught:
            find_globus_cli()
        assert "pip install globus-cli" in str(caught.value)


class TestARelativeLocalPathHasSomewhereToStart:
    """The remote side resolves against its root; the local side must match.

    Resolving against the process working directory looks the same in a
    terminal and is a different directory for every MCP client, none of them
    the one the caller had in mind.
    """

    def test_a_relative_path_lands_under_the_local_root(self, tmp_path):
        (tmp_path / "runs").mkdir()
        resolved = resolve_local("runs/mesh.nc", str(tmp_path))
        assert resolved == (tmp_path / "runs" / "mesh.nc").resolve()

    def test_the_working_directory_is_only_used_when_there_is_no_root(self, tmp_path):
        assert resolve_local("mesh.nc", None) == (Path.cwd() / "mesh.nc").resolve()

    def test_a_relative_path_still_cannot_climb_out_of_the_root(self, tmp_path):
        with pytest.raises(PathOutsideRoot):
            resolve_local("../elsewhere/mesh.nc", str(tmp_path))
