"""The submitter-Python guard that replaced the hard 3.12 pin.

``requires-python`` used to be ``>=3.12,<3.13`` because Globus Compute's
serializer breaks across minor versions (globus/globus-compute#2139). That
made every local-only user carry a constraint belonging to an opt-in feature,
and it blocked conda and non-3.12 container bases.

The constraint now lives in ``uxarray_mcp.remote`` as a runtime warning on the
paths that actually submit remote work. These tests pin the two properties that
make that trade safe: a local-only session on any supported Python stays
silent, and a remote opt-in on an unsupported submitter warns.
"""

from __future__ import annotations

import sys
import warnings

import pytest

from uxarray_mcp import remote


def _version_info(major: int, minor: int, micro: int = 0):
    """Build a stand-in for ``sys.version_info``.

    A bare tuple is not sufficient. ``remote.sys`` is the one global ``sys``
    module, so patching it is visible to every module in the process --
    including ``provenance``, which reads ``version_info.major``. Replacing it
    with ``(3, 13, 0)`` makes unrelated code raise ``AttributeError`` and the
    test fails for a reason that has nothing to do with what it is testing.
    ``sys.version_info`` is a structseq: indexable *and* attribute-addressable.
    """

    class _VersionInfo(tuple):
        @property
        def major(self):
            return self[0]

        @property
        def minor(self):
            return self[1]

        @property
        def micro(self):
            return self[2]

        @property
        def releaselevel(self):
            return self[3]

        @property
        def serial(self):
            return self[4]

    return _VersionInfo((major, minor, micro, "final", 0))


@pytest.fixture
def as_python(monkeypatch):
    """Run the body as though the interpreter were a given Python version."""

    def _set(major: int, minor: int) -> None:
        monkeypatch.setattr(sys, "version_info", _version_info(major, minor))

    return _set


class TestSupportPredicate:
    def test_reports_support_for_the_running_interpreter(self, as_python):
        """The predicate reads the live interpreter, not a hardcoded answer."""
        as_python(3, 12)
        assert remote.submitter_python_supported() is True

        as_python(3, 13)
        assert remote.submitter_python_supported() is False

        as_python(3, 11)
        assert remote.submitter_python_supported() is False

    def test_supported_set_is_not_empty(self):
        """A typo emptying the tuple would silently warn on every interpreter."""
        assert remote.SUPPORTED_SUBMITTER_PYTHON


class TestWarning:
    def test_silent_on_a_supported_submitter(self, as_python):
        as_python(3, 12)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            remote.warn_if_unsupported_submitter()
        assert caught == []

    def test_warns_on_an_unsupported_submitter(self, as_python):
        as_python(3, 13)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            remote.warn_if_unsupported_submitter()

        assert len(caught) == 1
        assert issubclass(caught[0].category, RuntimeWarning)
        message = str(caught[0].message)
        # The warning has to say which Python is running, which is supported,
        # and that local work is fine -- otherwise a local-only user who trips
        # it will think their install is broken.
        assert "3.13" in message
        assert "3.12" in message
        assert "Local execution is unaffected" in message

    def test_warns_rather_than_raises(self, as_python):
        """Import-time failure would break local servers on 3.11/3.13.

        ``uxarray_mcp.tools`` imports remote helpers unconditionally to build
        the tool surface, so this must never escalate to an exception.
        """
        as_python(3, 13)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(RuntimeWarning):
                remote.warn_if_unsupported_submitter()


class TestLocalPathStaysSilent:
    """The whole point of the change: local-only users pay nothing."""

    def test_importing_the_package_does_not_warn(self, as_python):
        as_python(3, 13)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import importlib

            import uxarray_mcp.app

            importlib.reload(uxarray_mcp.app)
        assert [w for w in caught if "Globus" in str(w.message)] == []

    def test_building_the_registry_does_not_warn(self, as_python):
        as_python(3, 13)
        from uxarray_mcp.app import make_registry

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            make_registry()
        assert [w for w in caught if "Globus" in str(w.message)] == []

    def test_switching_to_local_mode_does_not_warn(
        self, monkeypatch, as_python, tmp_path
    ):
        """Switching *to* local is always safe, whatever the interpreter."""
        monkeypatch.setenv("UXARRAY_MCP_CONFIG", str(tmp_path / "config.yaml"))
        as_python(3, 13)

        from uxarray_mcp.tools.execution_control import set_execution_mode

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            set_execution_mode("local")
        assert [w for w in caught if "Globus" in str(w.message)] == []
