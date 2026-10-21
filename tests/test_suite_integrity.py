"""Checks on the test run itself, before any of its results mean anything.

A green suite is evidence only if the suite ran against the software it
claims to be testing. These assert that it did.
"""

from __future__ import annotations

import pytest

from tests.conftest import UXARRAY_IS_MOCKED


def test_the_suite_ran_against_a_real_uxarray():
    """Refuse to report green on a run that exercised MagicMocks.

    ``conftest`` substitutes stand-ins when uxarray is absent, which is what
    lets the pure-logic tests run on a bare checkout. The hazard is the case
    it cannot distinguish by outcome: a MagicMock returns a MagicMock for
    every attribute and call, so a suite running against one passes almost
    everything it asserts and reports the same green as a real run. Every
    number this server has ever published rests on the difference.
    """
    assert not UXARRAY_IS_MOCKED, (
        "uxarray was not importable, so the suite ran against MagicMocks and "
        "its result says nothing about uxarray. Install the package "
        "(`uv sync --dev`) and run again."
    )


def test_the_installed_uxarray_meets_the_declared_floor():
    """The floor exists because older releases return wrong numbers.

    2026.7.0 computed face areas with an incorrect Jacobian, 2026.8.0 matched
    structured-grid nodes in the lon/lat plane, and everything below 2026.9.0
    inflated the Green-Gauss gradient by ``A_dual/A_primal`` while dropping
    the spherical metric terms from curl and divergence, so a run against any
    of them is testing something we have declared unfit to install. Read the
    floor from the packaging metadata rather than repeating it here, so this
    cannot drift away from ``pyproject.toml``.
    """
    from importlib.metadata import requires
    from importlib.metadata import version as installed_version

    from packaging.requirements import Requirement
    from packaging.version import Version

    declared = [
        Requirement(spec)
        for spec in (requires("uxarray-mcp") or [])
        if Requirement(spec).name == "uxarray"
    ]
    if not declared:  # pragma: no cover - only if the dependency is dropped
        pytest.skip("uxarray is not a declared dependency of uxarray-mcp")

    found = Version(installed_version("uxarray"))
    assert declared[0].specifier.contains(found, prereleases=True), (
        f"installed uxarray {found} does not satisfy the declared "
        f"{declared[0]}; the suite is exercising a version we refuse to "
        f"install against."
    )


def test_the_suite_cannot_see_a_real_endpoint():
    """No test may resolve the machine's own HPC configuration.

    A developer with `~/.config/uxarray-mcp/config.yaml` used to get a real
    endpoint id here, and any tool called with `use_remote=True` then made a
    live Globus call that stalled to the SDK's 60 s default before falling
    back to local. That is a unit test whose runtime and result depend on a
    file outside the repository and on whether a cluster is up; the autouse
    `offline_config` fixture closes both discovery paths, and this asserts it
    is still closed.
    """
    from uxarray_mcp.remote.config import discover_config_path, load_config

    config = load_config(discover_config_path())

    assert config.endpoint_id is None
    assert config.endpoints == {}


class TestSetupScriptMatchesCI:
    """``SETUP.sh`` is the first thing a new contributor runs.

    It drifted: it ran a bare ``uv sync`` and an unfiltered ``pytest``,
    while the suite had moved to marker-based selection. Following it
    produced 19 failures that were purely missing optional dependencies --
    the script's own fault, on a tree where CI was green. These hold it to
    the same partition CI uses so the same drift is caught here instead of
    by someone's first afternoon.
    """

    @staticmethod
    def _setup_text():
        from pathlib import Path

        return (Path(__file__).resolve().parent.parent / "SETUP.sh").read_text()

    def test_it_installs_the_hpc_extra(self):
        """Without it, the hpc-marked tests fail on ModuleNotFoundError.

        They are mocked and need no cluster, so there is no reason for a
        contributor not to run them.
        """
        assert "uv sync --extra hpc --dev" in self._setup_text()

    def test_it_selects_by_marker_and_not_by_filename(self):
        """``pytest.ini`` says CI selects by marker, never by filename.

        The ``--ignore=tests/test_remote_agent.py`` that used to be here was
        hiding 16 tests that pass.
        """
        # Only the commands, not the comments explaining why `--ignore` is
        # the wrong tool -- those legitimately mention it by name.
        commands = [
            line
            for line in self._setup_text().splitlines()
            if "pytest" in line and not line.lstrip().startswith("#")
        ]
        assert commands, "SETUP.sh runs no tests at all"
        for line in commands:
            assert "--ignore" not in line, (
                f"select by marker, not by filename: {line.strip()}"
            )
        joined = "\n".join(commands)
        assert '-m "not hpc and not live and not yac"' in joined
        assert '-m "hpc and not yac"' in joined

    def test_it_does_not_gate_on_the_ambient_interpreter(self):
        """``.python-version`` pins 3.12 and uv provisions it.

        The old gate ran ``python3 -c 'assert sys.version_info >= (3, 11)'``
        and exited 1, so a machine whose system python3 was 3.9 could not
        run the script at all -- while ``uv sync`` on that same machine
        builds a working 3.12 environment.
        """
        text = self._setup_text()
        assert "Python 3.11 or newer is required" not in text, (
            "the ambient python3 is not the interpreter the project runs on"
        )
