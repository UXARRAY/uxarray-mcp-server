"""Tests for the CalVer version rules and the uxarray pin they carry.

The release job decides a version number and rewrites four files with it while
nobody is watching, so the arithmetic is the part that has to be right before
it runs. Upstream is the input: its `year.month` is copied, its patch is not,
and the pin that says which upstream months we accept moves with it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release.py"
_spec = importlib.util.spec_from_file_location("prepare_release_calver", _SCRIPT)
assert _spec and _spec.loader
prepare_release = importlib.util.module_from_spec(_spec)
sys.modules["prepare_release_calver"] = prepare_release
_spec.loader.exec_module(prepare_release)

_next_version = prepare_release._next_version
_parse_version = prepare_release._parse_version
_uxarray_pin = prepare_release._uxarray_pin
_latest_upstream = prepare_release._latest_upstream


def _pypi(*versions: str, yanked: set[str] | None = None) -> dict:
    """A PyPI JSON payload carrying exactly these releases."""
    yanked = yanked or set()
    return {
        "info": {"version": versions[-1] if versions else ""},
        "releases": {
            version: [
                {"filename": f"uxarray-{version}.tar.gz", "yanked": version in yanked}
            ]
            for version in versions
        },
    }


class TestTheVersionFollowsUpstreamsMonth:
    def test_a_second_release_in_upstreams_month_bumps_only_our_patch(self):
        assert _next_version("2026.9.0", "2026.9.0") == "2026.9.1"

    def test_a_new_upstream_month_resets_the_patch(self):
        assert _next_version("2026.9.3", "2026.10.0") == "2026.10.0"

    def test_the_first_calver_release_lands_on_upstreams_month(self):
        """`0.3.1` is not a month, so it can never match one."""
        assert _next_version("0.3.1", "2026.9.0") == "2026.9.0"

    def test_a_month_upstream_skipped_is_simply_not_used(self):
        """Upstream skipped 2026.01 and 2026.05. We follow where it went.

        The intervening months are not released quietly on our side; the
        version jumps with upstream's.
        """
        assert _next_version("2026.4.2", "2026.6.0") == "2026.6.0"

    def test_upstream_releasing_twice_in_a_month_does_not_move_our_month(self):
        """August 2026 had two upstream releases and would have had one of ours.

        Upstream's own patch is not mirrored -- only the month is -- so our
        patch counts our releases, not theirs.
        """
        assert _next_version("2026.8.0", "2026.8.1") == "2026.8.1"
        assert _next_version("2026.8.1", "2026.8.2") == "2026.8.2"

    def test_december_is_not_a_thirteenth_month(self):
        assert _next_version("2026.11.0", "2026.12.0") == "2026.12.0"
        assert _next_version("2026.12.0", "2027.1.0") == "2027.1.0"


class TestZeroPaddingIsRefused:
    """Upstream tags `v2026.09.0`; PEP 440 publishes it as `2026.9.0`.

    Copying the padding across would ship a dist whose version disagrees with
    the tag it was built from, so the padded form is rejected where it enters
    rather than normalized silently.
    """

    def test_a_padded_month_is_rejected(self):
        with pytest.raises(ValueError, match="Zero-padded"):
            _parse_version("2026.09.0")

    def test_the_message_names_the_version_to_use_instead(self):
        with pytest.raises(ValueError, match=r"Use 2026\.9\.0"):
            _parse_version("2026.09.0")

    def test_a_padded_patch_is_rejected_too(self):
        with pytest.raises(ValueError, match="Zero-padded"):
            _parse_version("2026.9.01")

    def test_a_plain_zero_is_not_padding(self):
        assert _parse_version("2026.9.0") == (2026, 9, 0)

    def test_padded_upstream_cannot_sneak_in_through_next_version(self):
        with pytest.raises(ValueError, match="Zero-padded"):
            _next_version("2026.8.0", "2026.09.0")


class TestThePinMovesBothEnds:
    def test_the_ceiling_is_the_month_after_upstream(self):
        assert _uxarray_pin("2026.9.0") == "uxarray>=2026.9.0,<2026.10"

    def test_the_floor_is_the_upstream_being_released_against(self):
        assert _uxarray_pin("2026.10.2").startswith("uxarray>=2026.10.2,")

    def test_december_rolls_the_ceiling_into_the_next_year(self):
        """`<2026.13` is not a version anyone will ever publish."""
        assert _uxarray_pin("2026.12.0") == "uxarray>=2026.12.0,<2027.1"

    def test_the_pin_is_rewritten_whole_in_pyproject(self, tmp_path, monkeypatch):
        """A floor raised without its ceiling is the bug this guards.

        The next upstream month would then be excluded by a ceiling written
        for the month before, and the package becomes uninstallable beside
        the release it was tested against.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "dependencies = [\n"
            '    "pyyaml>=6.0.1",\n'
            '    "uxarray>=2026.9.0,<2026.10",\n'
            "]\n"
        )
        monkeypatch.setattr(prepare_release, "PYPROJECT", pyproject)

        prepare_release._write_uxarray_pin("2026.10.0")

        assert '"uxarray>=2026.10.0,<2026.11",' in pyproject.read_text()
        assert '"pyyaml>=6.0.1",' in pyproject.read_text()

    def test_a_bare_floor_gains_a_ceiling(self):
        """What `pyproject.toml` carries today is a floor and nothing else."""
        text = 'dependencies = [\n    "uxarray>=2026.9.0",\n]\n'
        assert (
            prepare_release.UXARRAY_PIN_RE.sub(
                '\\g<indent>"' + _uxarray_pin("2026.9.0") + '",', text
            )
            == 'dependencies = [\n    "uxarray>=2026.9.0,<2026.10",\n]\n'
        )

    def test_an_ambiguous_pyproject_is_refused_rather_than_guessed(
        self, tmp_path, monkeypatch
    ):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('    "uxarray>=2026.9.0",\n    "uxarray-viz>=1.0",\n')
        monkeypatch.setattr(prepare_release, "PYPROJECT", pyproject)

        with pytest.raises(RuntimeError, match="exactly one uxarray"):
            prepare_release._write_uxarray_pin("2026.10.0")


class TestUpstreamIsReadFromPypi:
    def test_the_newest_release_wins_not_the_last_key(self):
        """Dict order in the JSON is upload order, which is not version order."""
        payload = _pypi("2026.4.0", "2026.10.0", "2026.9.0")
        assert _latest_upstream(fetch=lambda url: payload) == "2026.10.0"

    def test_prereleases_are_not_months_we_mirror(self):
        payload = _pypi("2026.9.0", "2026.10.0rc1")
        assert _latest_upstream(fetch=lambda url: payload) == "2026.9.0"

    def test_a_fully_yanked_release_is_skipped(self):
        payload = _pypi("2026.9.0", "2026.10.0", yanked={"2026.10.0"})
        assert _latest_upstream(fetch=lambda url: payload) == "2026.9.0"

    def test_padding_from_pypi_is_normalized_not_propagated(self):
        payload = _pypi("2026.09.0")
        assert _latest_upstream(fetch=lambda url: payload) == "2026.9.0"

    def test_an_unreachable_index_decides_nothing(self):
        """No answer is not `0.0.0`. The caller falls back to a patch bump."""

        def _fail(url):
            raise OSError("no route to host")

        assert _latest_upstream(fetch=_fail) is None


class TestTheDailyPollDecidesWhenToRelease:
    """A daily cron asks this script "is there anything to do today".

    Commits are no longer the only reason to answer yes: a new upstream month
    is a release even when nothing in this repository changed, because the pin
    that says which upstream we support is itself the change.
    """

    @pytest.fixture
    def sandbox(self, tmp_path, monkeypatch):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            'version = "2026.9.0"\n'
            "dependencies = [\n"
            '    "uxarray>=2026.9.0,<2026.10",\n'
            "]\n"
        )
        init = tmp_path / "__init__.py"
        init.write_text('__version__ = "2026.9.0"\n')
        recipe = tmp_path / "meta.yaml"
        recipe.write_text('{% set version = "2026.9.0" %}\n')
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## Unreleased\n\n- Something.\n")

        monkeypatch.setattr(prepare_release, "PYPROJECT", pyproject)
        monkeypatch.setattr(prepare_release, "INIT", init)
        monkeypatch.setattr(prepare_release, "CONDA_RECIPE", recipe)
        monkeypatch.setattr(prepare_release, "CHANGELOG", changelog)
        monkeypatch.setattr(prepare_release, "_relock", lambda version: None)
        monkeypatch.setattr(prepare_release, "_latest_tag", lambda: "v2026.9.0")

        output = tmp_path / "github_output"
        output.write_text("")
        monkeypatch.setenv("GITHUB_OUTPUT", str(output))
        monkeypatch.setattr(sys, "argv", ["prepare_release.py"])
        return {"pyproject": pyproject, "changelog": changelog, "output": output}

    def _outputs(self, sandbox) -> dict[str, str]:
        return dict(
            line.split("=", 1)
            for line in sandbox["output"].read_text().splitlines()
            if line
        )

    def test_a_new_upstream_month_is_a_release_with_no_commits_of_our_own(
        self, sandbox, monkeypatch
    ):
        monkeypatch.setattr(prepare_release, "_commits_since", lambda tag: 0)
        monkeypatch.setattr(prepare_release, "_latest_upstream", lambda: "2026.10.0")

        assert prepare_release.main() == 0

        outputs = self._outputs(sandbox)
        assert outputs["release_needed"] == "true"
        assert outputs["version"] == "2026.10.0"
        assert outputs["tag"] == "v2026.10.0"
        assert outputs["upstream_is_new"] == "true"
        assert '"uxarray>=2026.10.0,<2026.11",' in sandbox["pyproject"].read_text()
        assert "## 2026.10.0 —" in sandbox["changelog"].read_text()

    def test_the_same_upstream_and_no_commits_writes_nothing(
        self, sandbox, monkeypatch
    ):
        monkeypatch.setattr(prepare_release, "_commits_since", lambda tag: 0)
        monkeypatch.setattr(prepare_release, "_latest_upstream", lambda: "2026.9.0")
        before = sandbox["pyproject"].read_text()

        assert prepare_release.main() == 0

        assert self._outputs(sandbox)["release_needed"] == "false"
        assert sandbox["pyproject"].read_text() == before
        assert "## 2026" not in sandbox["changelog"].read_text()

    def test_an_unreachable_pypi_falls_back_to_a_patch_bump(self, sandbox, monkeypatch):
        """The version still moves, and the pin is left exactly as it was.

        Guessing a ceiling from a version we could not read would be worse
        than shipping the one that was already reviewed.
        """
        monkeypatch.setattr(prepare_release, "_commits_since", lambda tag: 3)
        monkeypatch.setattr(prepare_release, "_latest_upstream", lambda: None)

        assert prepare_release.main() == 0

        assert self._outputs(sandbox)["version"] == "2026.9.1"
        assert '"uxarray>=2026.9.0,<2026.10",' in sandbox["pyproject"].read_text()


class TestTheRealPyprojectStaysParseable:
    def test_the_shipped_pin_matches_exactly_once(self):
        text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
        assert len(prepare_release.UXARRAY_PIN_RE.findall(text)) == 1

    def test_the_shipped_floor_is_readable(self):
        assert _parse_version(prepare_release._current_uxarray_floor())
