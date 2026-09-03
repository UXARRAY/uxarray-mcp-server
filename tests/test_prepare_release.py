"""Tests for the release preparation script.

The release job runs unattended once a month, so the parts of it that rewrite
files in place are the parts nobody watches. These cover the changelog stamp,
which is the one that decides what a published release says it contains.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release.py"
_spec = importlib.util.spec_from_file_location("prepare_release", _SCRIPT)
assert _spec and _spec.loader
prepare_release = importlib.util.module_from_spec(_spec)
sys.modules["prepare_release"] = prepare_release
_spec.loader.exec_module(prepare_release)

stamp_changelog = prepare_release.stamp_changelog

_CHANGELOG = """# Changelog

## Unreleased

### Fixed
- Something.

## 0.3.0 — 2026-08-29

### Changed
- Something older.
"""


def test_unreleased_notes_move_under_the_new_version():
    stamped = stamp_changelog(_CHANGELOG, "0.3.1", "2026-09-05")

    assert "## 0.3.1 — 2026-09-05" in stamped
    # The notes have to land under the version heading, not stay above it:
    # that is the whole point of stamping.
    body = stamped.split("## 0.3.1 — 2026-09-05", 1)[1]
    assert "- Something." in body.split("## 0.3.0", 1)[0]


def test_an_empty_unreleased_section_is_left_for_the_next_cycle():
    stamped = stamp_changelog(_CHANGELOG, "0.3.1", "2026-09-05")

    between = stamped.split("## Unreleased", 1)[1].split("## 0.3.1", 1)[0]
    assert between.strip() == ""


def test_stamping_twice_does_not_stack_headings():
    """A re-run of the release job must not add a second heading.

    The job is retryable, and the retry starts from a working tree that may
    already carry the first run's stamp.
    """
    once = stamp_changelog(_CHANGELOG, "0.3.1", "2026-09-05")
    twice = stamp_changelog(once, "0.3.1", "2026-09-06")

    assert once == twice
    assert twice.count("## 0.3.1") == 1


def test_a_changelog_with_no_unreleased_heading_refuses():
    """Guessing where the notes start would publish the wrong ones."""
    with pytest.raises(RuntimeError, match="no '## Unreleased' heading"):
        stamp_changelog("# Changelog\n\n## 0.3.0 — 2026-08-29\n", "0.3.1", "2026-09-05")


def test_the_real_changelog_has_the_heading_the_script_needs():
    """The script's one assumption, checked against the file it will edit."""
    text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text()

    stamped = stamp_changelog(text, "99.0.0", "2026-09-05")
    assert "## 99.0.0 — 2026-09-05" in stamped
