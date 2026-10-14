"""``uxarray-mcp endpoints discover``.

The first thing a new user asks is "where do I get a UUID", and the honest
previous answer was "someone gives it to you". That is fine for a shared
facility endpoint and useless for anyone who just started their own: the
UUID is printed once, when the endpoint registers, and is easy to lose.

Globus Compute knows which endpoints an identity can see, so this command
asks it and prints a ready-to-paste ``endpoints add`` line for each one that
is not configured yet.
"""

from __future__ import annotations

import argparse

import pytest

from uxarray_mcp.cli import _suggest_prefixes, cmd_endpoints_discover


class _FakeClient:
    def __init__(self, endpoints):
        self._endpoints = endpoints

    def get_endpoints(self):
        return self._endpoints


@pytest.fixture
def discover(monkeypatch):
    """Run the command against a canned endpoint list.

    Patching ``globus_compute_sdk.Client`` means importing it, which the
    core CI lane cannot do -- it installs no optional extras. Hence the
    ``hpc`` marker on the classes that use this; the pure-logic tests below
    (prefix hints, alias choice) stay in the core lane where they belong.
    """

    def run(endpoints, *, json_output=False, configured=None):
        import globus_compute_sdk

        monkeypatch.setattr(
            globus_compute_sdk, "Client", lambda *a, **k: _FakeClient(endpoints)
        )

        if configured is not None:
            from uxarray_mcp import cli as cli_module

            class _Profile:
                def __init__(self, endpoint_id):
                    self.endpoint_id = endpoint_id

            class _Cfg:
                endpoints = {n: _Profile(u) for n, u in configured.items()}

            monkeypatch.setattr(cli_module, "load_config", lambda: _Cfg())

        args = argparse.Namespace(json=json_output)
        return cmd_endpoints_discover(args)

    return run


@pytest.mark.hpc
class TestItAnswersWhereDoIGetAUuid:
    def test_a_visible_endpoint_is_listed_with_its_uuid(self, discover, capsys):
        code = discover(
            [{"uuid": "abc-123", "name": "uxarray-chrysalis"}], configured={}
        )

        out = capsys.readouterr().out
        assert code == 0
        assert "abc-123" in out
        assert "uxarray-chrysalis" in out

    def test_an_unconfigured_endpoint_gets_a_pasteable_command(self, discover, capsys):
        discover([{"uuid": "abc-123", "name": "uxarray-chrysalis"}], configured={})

        out = capsys.readouterr().out
        assert "uxarray-mcp endpoints add chrysalis abc-123" in out
        assert "--path-prefix /lcrc/" in out

    def test_an_already_configured_endpoint_is_marked_not_re_suggested(
        self, discover, capsys
    ):
        """Printing an `add` line for something already added invites a mistake."""
        discover(
            [{"uuid": "abc-123", "name": "uxarray-chrysalis"}],
            configured={"chrysalis": "abc-123"},
        )

        out = capsys.readouterr().out
        assert "configured as 'chrysalis'" in out
        assert "endpoints add" not in out


@pytest.mark.hpc
class TestTheSuggestedNameNamesTheMachine:
    """``uxarray-chrysalis`` should suggest ``chrysalis``, not ``uxarray``.

    Taking the first token is the obvious implementation and the wrong one:
    every endpoint at a site tends to be prefixed with the project name, so
    the local alias would say nothing about which machine it is.
    """

    @pytest.mark.parametrize(
        "endpoint_name,expected",
        [
            ("uxarray-chrysalis", "chrysalis"),
            ("improv-uxarray", "improv"),
            ("ucar-uxarray-yac", "ucar"),
            ("casper-things", "casper"),
        ],
    )
    def test_the_site_word_wins(self, discover, capsys, endpoint_name, expected):
        discover([{"uuid": "u-1", "name": endpoint_name}], configured={})

        out = capsys.readouterr().out
        assert f"endpoints add {expected} u-1" in out

    def test_an_unrecognised_name_still_produces_a_usable_line(self, discover, capsys):
        """A cluster nobody wrote a page about must still work."""
        discover([{"uuid": "u-9", "name": "mylab-cluster"}], configured={})

        out = capsys.readouterr().out
        assert "endpoints add mylab u-9" in out
        # No prefix is known, so ask rather than invent one.
        assert "/your/data/root/" in out


class TestPrefixHints:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("ucar-uxarray-yac", ("/glade/",)),
            ("casper", ("/glade/",)),
            ("uxarray-chrysalis", ("/lcrc/",)),
            ("improv-uxarray", ("/gpfs/fs1/", "/home/")),
            ("perlmutter-ep", ("/pscratch/", "/global/")),
        ],
    )
    def test_known_sites_get_their_filesystem(self, name, expected):
        assert _suggest_prefixes(name) == expected

    def test_an_unknown_site_gets_nothing_rather_than_a_guess(self):
        """A wrong prefix routes work to the wrong machine, silently."""
        assert _suggest_prefixes("some-random-endpoint") == ()


@pytest.mark.hpc
class TestWhenThereIsNothingToShow:
    def test_an_empty_list_explains_both_reasons(self, discover, capsys):
        """ "No endpoints" has two very different causes; name them both."""
        code = discover([], configured={})

        out = capsys.readouterr().out
        assert code == 0
        assert "not started an endpoint" in out
        assert "belongs to someone else" in out


@pytest.mark.hpc
class TestTheRawResponseIsAvailable:
    def test_json_prints_the_service_payload(self, discover, capsys):
        import json

        code = discover(
            [{"uuid": "abc-123", "name": "ep", "owner": "someone"}],
            json_output=True,
            configured={},
        )

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload[0]["uuid"] == "abc-123"
        assert payload[0]["owner"] == "someone"
