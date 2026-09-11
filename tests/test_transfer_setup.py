"""``transfer setup``, driven with no globus binary and no browser.

The command exists because getting Globus Transfer working by hand means
finding out about seven prerequisites in the worst possible order. So the thing
worth testing is not that each check runs -- it is that each one reports the
*right* state, including the two that are easy to get confidently wrong: a
read-only share reported as fine, and an ordinary error reported as a login
problem.

Nothing here launches a browser, reads the real config, or touches the network.
Every subprocess call and every prompt is injected.
"""

from __future__ import annotations

import sys

import pytest

from uxarray_mcp.remote import gcp
from uxarray_mcp.transfer_setup import (
    KNOWN_COLLECTIONS,
    TransferSetup,
    known_collection_for,
)


class FakeProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Recorder:
    """Stands in for both ``subprocess.run`` and ``print``."""

    def __init__(self, replies=None):
        self.replies = replies or {}
        self.calls: list[list[str]] = []
        self.lines: list[str] = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        for key, reply in self.replies.items():
            if any(key in str(part) for part in argv):
                return reply
        return FakeProcess(1, stderr="unexpected call")

    def emit(self, line):
        self.lines.append(str(line))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _setup(rec, **kwargs):
    kwargs.setdefault("endpoint", "ucar-uxarray-yac")
    return TransferSetup(runner=rec.run, emit=rec.emit, **kwargs)


class TestTheFacilityCollectionIsNamedNotSearchedFor:
    """A name search returns a page of look-alikes with no way to pick.

    Facilities publish a guest collection per project and users publish their
    own, so "GLADE" matches many collections and only one of them serves the
    filesystem the compute endpoint runs on. The table is the answer.
    """

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("ucar-uxarray-yac", "ncar"),
            ("derecho", "ncar"),
            ("alcf-polaris", "polaris"),
            ("aurora-flare", "aurora"),
            ("nersc-perlmutter", "perlmutter"),
        ],
    )
    def test_an_endpoint_name_finds_its_facility(self, name, expected):
        found = known_collection_for(name)
        assert found is not None
        assert found.collection_id == KNOWN_COLLECTIONS[expected].collection_id

    def test_an_unknown_endpoint_is_asked_about_rather_than_guessed(self):
        """Chrysalis and Improv have no published collection. Inventing a UUID
        for them would send a transfer to a real collection belonging to
        somebody else."""
        rec = Recorder()
        setup = _setup(rec, endpoint="chrysalis", check_only=True)
        assert setup.step_remote_collection() is None
        assert "unknown" in rec.text


class TestTheWriteBitOnThisMachinesShare:
    """The default share is the home directory with the write bit clear.

    Nothing announces this. An upload works, because it only reads here; a
    download fails on the destination write, which reads as a network problem
    and is not. It is the failure that costs an afternoon, so it is checked
    before anything is submitted.
    """

    def test_a_read_only_share_is_reported_as_the_problem_it_is(self, monkeypatch):
        monkeypatch.setattr(
            gcp,
            "share_for",
            lambda path, runner=None: gcp.GcpShare(
                "/Users/x", readable=True, writable=False
            ),
        )
        rec = Recorder()
        _setup(rec, check_only=True)._step_gcp_share("/Users/x/work")
        assert "READ-ONLY" in rec.text
        assert "TODO" in rec.text

    def test_a_writable_share_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(
            gcp,
            "share_for",
            lambda path, runner=None: gcp.GcpShare(
                "/Users/x", readable=True, writable=True
            ),
        )
        rec = Recorder()
        _setup(rec, check_only=True)._step_gcp_share("/Users/x/work")
        assert "READ-ONLY" not in rec.text
        assert "[ok" in rec.text

    def test_a_path_nobody_shared_is_a_different_complaint(self, monkeypatch):
        """Not shared and shared read-only need different fixes, so they are
        different lines."""
        monkeypatch.setattr(gcp, "share_for", lambda path, runner=None: None)
        rec = Recorder()
        _setup(rec, check_only=True)._step_gcp_share("/tmp/elsewhere")
        assert "not in Globus Connect Personal's shared paths" in rec.text

    def test_the_fix_names_this_platforms_way_of_doing_it(self, monkeypatch):
        setup = TransferSetup()
        monkeypatch.setattr(sys, "platform", "darwin")
        assert "Preferences" in setup._share_fix("/Users/x")
        monkeypatch.setattr(sys, "platform", "linux")
        assert "config-paths" in setup._share_fix("/home/x")


class TestConsentIsProvedByUsingIt:
    """Asking Globus whether a consent exists is not the same as having it.

    A collection can also refuse a session identity, which no consent check
    sees. Listing a directory exercises token, consent, identity policy and
    path in one call and moves nothing.
    """

    def test_a_listing_that_works_is_the_end_of_it(self):
        rec = Recorder({"ls": FakeProcess(0, stdout="a.nc")})
        ok = _setup(rec).step_consent("/fake/globus", "coll-1", "/scratch")
        assert ok
        assert len(rec.calls) == 1

    def test_a_refused_listing_offers_the_scope_for_that_collection(self):
        rec = Recorder({"ls": FakeProcess(1, stderr="ConsentRequired")})
        ok = _setup(rec, check_only=True).step_consent("/fake/globus", "coll-1", "/x")
        assert not ok
        assert "globus session consent" in rec.text
        assert "coll-1/data_access" in rec.text

    def test_the_local_collection_is_never_asked_for_a_scope(self):
        """Only Globus Connect Server v5 collections have ``data_access``. A
        Globus Connect Personal collection does not, and requesting one fails
        with UNKNOWN_SCOPE_ERROR, leaving the login permanently incomplete --
        which is the defect this whole change removes."""
        rec = Recorder({"ls": FakeProcess(1, stderr="ConsentRequired")})
        setup = _setup(rec, check_only=True)
        setup.step_consent("/fake/globus", "remote-coll", "/x")
        consent_lines = [line for line in rec.lines if "session consent" in line]
        assert consent_lines
        assert all("remote-coll" in line for line in consent_lines)


class TestCheckModeChangesNothing:
    def test_no_offer_is_taken_even_when_the_answer_would_be_yes(self):
        rec = Recorder()

        def refuse(prompt):
            raise AssertionError(f"--check asked a question: {prompt!r}")

        setup = TransferSetup(
            endpoint="x", check_only=True, runner=rec.run, emit=rec.emit, prompt=refuse
        )
        assert setup._confirm("do a thing?") is False
        assert setup._ask("a value: ", "fallback") == "fallback"

    def test_a_missing_login_does_not_stop_the_local_checks(
        self, monkeypatch, tmp_path
    ):
        """The Globus Connect Personal state is read off local files and is the
        most likely thing to be quietly wrong, so a report that stopped at the
        login would hide it."""
        monkeypatch.setenv("UXARRAY_MCP_CONFIG", str(tmp_path / "config.yaml"))
        monkeypatch.setattr(gcp, "is_running", lambda runner=None: True)
        monkeypatch.setattr(
            gcp,
            "share_for",
            lambda path, runner=None: gcp.GcpShare("/h", readable=True, writable=False),
        )
        monkeypatch.setattr(gcp, "collection_id", lambda: "local-uuid")
        rec = Recorder(
            {
                "whoami": FakeProcess(1, stderr="MissingLoginError"),
                "endpoint": FakeProcess(0, stdout=""),
            }
        )
        setup = _setup(rec, check_only=True)
        setup.find_cli = lambda: "/fake/globus"
        setup.run()
        titles = [result.title for result in setup.results]
        assert "globus login" in titles
        assert any("writable" in title for title in titles)
        assert "this machine's collection" in titles

    def test_the_exit_code_says_whether_anything_is_outstanding(self, monkeypatch):
        rec = Recorder()
        setup = _setup(rec, check_only=True)
        setup.find_cli = lambda: None
        assert setup.run() == 1
