"""The worker reports the version of the code it is running.

Both clusters run this package from a git checkout installed editable, and
an editable install does not rewrite its ``.dist-info`` when the checkout is
pulled. ``importlib.metadata.version()`` therefore kept answering 2026.9.0
after a successful update to 2026.9.1, and the drift warning fired against a
worker that was in fact current.

That is worse than no warning. The obvious response is to redo an update
that already worked, and the real drift -- a genuinely stale worker -- is
indistinguishable from the false one.

Reading ``__version__`` out of the resolved source answers the question
actually being asked: which code will run.
"""

from __future__ import annotations

import inspect
import re

import pytest

from uxarray_mcp.remote import compute_functions as cf

#: Every worker function that reports a runtime block.
_REPORTERS = [
    obj
    for _name, obj in vars(cf).items()
    if inspect.isfunction(obj) and "mcp_server_version" in inspect.getsource(obj)
]


def test_there_are_reporters_to_check():
    """Guard the guard: a renamed field would empty the list silently."""
    assert _REPORTERS, "no worker function reports mcp_server_version"


@pytest.mark.parametrize("function", _REPORTERS, ids=lambda f: f.__name__)
class TestEveryReporterPrefersTheRunningCode:
    def test_it_reads_version_from_the_source_file(self, function):
        """``__version__`` is consulted, not just the installed metadata."""
        source = inspect.getsource(function)
        assert "__version__" in source, (
            f"{function.__name__} reports a version without reading "
            "__version__; an editable install will make it stale"
        )

    def test_metadata_remains_as_a_fallback(self, function):
        """A wheel install has no checkout to read, so keep the old path."""
        source = inspect.getsource(function)
        assert "importlib.metadata" in source

    def test_it_does_not_import_the_package(self, function):
        """Importing would break the self-contained rule for real.

        A worker resolves ``uxarray_mcp`` against its own copy, so importing
        it makes the payload non-self-contained -- and raises outright where
        the package is absent. ``find_spec`` returns ``None`` instead.
        """
        code = "\n".join(
            line.split("#", 1)[0] for line in inspect.getsource(function).splitlines()
        )
        without_find_spec = re.sub(
            r"find_spec\(\s*[^)]*\)", "find_spec(...)", code, flags=re.S
        )
        offenders = [
            line for line in without_find_spec.splitlines() if "uxarray_mcp" in line
        ]
        assert offenders == [], offenders


class TestTheVersionLineParses:
    def test_the_shipped_init_matches_the_pattern_the_worker_scans(self):
        """The worker takes the first ``__version__`` line and splits on quotes.

        If ``src/uxarray_mcp/__init__.py`` ever states its version another
        way -- single quotes, a computed value -- the scan returns something
        wrong rather than failing, so pin the shape here.
        """
        from pathlib import Path

        init = (
            Path(__file__).resolve().parents[1] / "src" / "uxarray_mcp" / "__init__.py"
        )
        line = next(
            line
            for line in init.read_text(encoding="utf-8").splitlines()
            if line.startswith("__version__")
        )

        parsed = line.split('"')[1]

        from uxarray_mcp import __version__

        assert parsed == __version__
