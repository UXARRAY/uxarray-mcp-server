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

import pytest

from uxarray_mcp.remote.config import GlobusTransferProfile
from uxarray_mcp.remote.transfer import (
    PathOutsideRoot,
    TransferError,
    TransferNotConfigured,
    TransferService,
    bounded_preview,
    collapse,
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
