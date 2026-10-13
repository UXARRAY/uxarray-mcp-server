"""``doctor --summary``: the same report, readable.

``doctor`` prints the full JSON by default and that stays the contract --
scripts parse it, and the flag is additive. But the first command a new user
runs should not be two hundred lines of nested objects they have to read to
find the one failing line, and the confusion this project actually hears
about is Compute versus Transfer: a working endpoint that still cannot move
a file.

Every assertion below is about rendering. The summary recomputes nothing, so
it cannot disagree with the JSON printed beside it.
"""

from __future__ import annotations

from uxarray_mcp.cli import render_doctor_summary


def _report(**overrides):
    base = {
        "passed": True,
        "mode": "local",
        "checks": [
            {"name": "config", "passed": True, "summary": "Configured endpoint x."},
        ],
    }
    base.update(overrides)
    return base


class TestTheVerdictIsTheFirstThingYouSee:
    def test_a_passing_report_says_pass(self):
        assert render_doctor_summary(_report()).splitlines()[0] == "PASS  overall"

    def test_a_failing_report_says_fail(self):
        text = render_doctor_summary(_report(passed=False))
        assert text.splitlines()[0] == "FAIL  overall"

    def test_the_mode_is_reported(self):
        assert "mode: local" in render_doctor_summary(_report())


class TestEachCheckIsOneLine:
    def test_a_passing_check_is_marked_ok(self):
        text = render_doctor_summary(_report())
        assert "ok    config: Configured endpoint x." in text

    def test_a_failing_check_is_marked_fail(self):
        text = render_doctor_summary(
            _report(
                passed=False,
                checks=[
                    {
                        "name": "endpoint_status",
                        "passed": False,
                        "summary": "Endpoint manager reports status='offline'.",
                    }
                ],
            )
        )
        assert "FAIL  endpoint_status" in text

    def test_guidance_is_shown_for_a_failing_check(self):
        """The fix belongs next to the failure, not in a separate document."""
        text = render_doctor_summary(
            _report(
                passed=False,
                checks=[
                    {
                        "name": "endpoint_status",
                        "passed": False,
                        "summary": "offline",
                        "guidance": "Start or restart the endpoint.",
                    }
                ],
            )
        )
        assert "Start or restart the endpoint." in text

    def test_guidance_is_not_shown_for_a_passing_check(self):
        """Advice on something that already works is noise."""
        text = render_doctor_summary(
            _report(
                checks=[
                    {
                        "name": "config",
                        "passed": True,
                        "summary": "fine",
                        "guidance": "Do not show me.",
                    }
                ]
            )
        )
        assert "Do not show me." not in text


class TestComputeIsNotTransfer:
    """The distinction that trips up first-time users.

    Globus Compute and Globus Transfer are separate services with separate
    consents, so an endpoint that runs jobs happily may still be unable to
    copy a file. ``docs/data-transfer.md`` explains it, but a user reaching
    for ``doctor`` has not read that yet.
    """

    def test_an_endpoint_without_transfers_says_so_in_plain_words(self):
        text = render_doctor_summary(
            _report(
                checks=[
                    {
                        "name": "transfer",
                        "passed": True,
                        "summary": (
                            "No globus_transfer block configured; this endpoint "
                            "moves no files."
                        ),
                    }
                ]
            )
        )
        assert "separate service" in text
        assert "uxarray-mcp transfer setup" in text

    def test_a_configured_transfer_does_not_get_the_note(self):
        text = render_doctor_summary(
            _report(
                checks=[
                    {
                        "name": "transfer",
                        "passed": True,
                        "summary": "globus_transfer configured for collection abc.",
                    }
                ]
            )
        )
        assert "separate service" not in text


class TestItPointsAtTheFullReport:
    def test_the_json_is_still_discoverable(self):
        """The summary is a view, not a replacement."""
        assert "without --summary" in render_doctor_summary(_report())
