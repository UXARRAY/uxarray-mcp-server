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

    2026.7.0 computed face areas with an incorrect Jacobian and 2026.8.0
    matched structured-grid nodes in the lon/lat plane, so a run against
    either is testing something we have declared unfit to install. Read the
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
