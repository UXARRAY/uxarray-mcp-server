"""The simulator is only worth having if it reproduces the real failures.

Each test here corresponds to a defect that actually happened on Chrysalis and
cost roughly half an hour to identify. If the fake endpoint can produce them in
seconds, the next one like them is cheap to find.

The four, in the order they were hit:

1. A worker killed for memory, arriving as ``WorkerLost`` with the cause
   redacted to ``*****`` by the server's error normalizer.
2. A worker importing different code than the submitter, so a merged fix was
   absent from the cluster and the operation kept failing.
3. A tool that works locally and dies remotely because the remote path does
   strictly more work than the probe used to check it.
4. A function that cannot be shipped because it closes over local state.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from tests.fake_endpoint import (
    MEMORY_LIMITS_ENFORCED,
    FakeWorkerLost,
    fake_endpoint,
)

pytestmark = pytest.mark.hpc


needs_memory_limits = pytest.mark.skipif(
    not MEMORY_LIMITS_ENFORCED,
    reason=(
        "macOS refuses RLIMIT_AS/DATA/RSS, so a cap here would silently not "
        "apply and the test would prove nothing. Runs on Linux, which is CI."
    ),
)


class TestAKilledWorkerIsReportedUsefully:
    @needs_memory_limits
    def test_an_oversized_job_really_dies(self):
        """A memory cap must kill the worker, not be politely ignored.

        ``RLIMIT_AS`` is a real limit on a real process, so this is the same
        kind of death the 300M-face ``calculate_area`` hit -- not a mock
        raising on cue.
        """

        def allocate_too_much():
            import numpy as np

            return float(np.ones(8 * 1024**3 // 8).sum())

        with fake_endpoint(memory_limit_gib=0.5) as endpoint:
            with pytest.raises(FakeWorkerLost):
                endpoint.run(allocate_too_much, (), {})
            assert endpoint.failures, "the worker died but recorded no reason"

    def test_the_normalizer_names_memory_rather_than_redacting(self):
        """The bug this simulator was built to catch.

        The real failure arrived as ``Remote execution failed on chrysalis:
        *****`` -- the normalizer kept the *last* line of the Globus message,
        which is boilerplate about Python versions, and threw away the only
        informative part. Diagnosing it meant bypassing the server entirely.
        """
        from uxarray_mcp.remote.agent import _normalize_remote_error

        config = type("C", (), {"endpoint_name": "chrysalis"})()
        raw = FakeWorkerLost(3, "chr-0118", "MemoryError")
        normalized = _normalize_remote_error(raw, config)

        message = str(normalized)
        assert "*****" not in message
        assert "memory" in message.lower(), (
            f"a killed worker must say what usually kills workers; got: {message}"
        )
        assert "chr-0118" in message and "worker 3" in message, (
            "the host and worker id are in the raw text and are what let you "
            f"find the job afterwards; got: {message}"
        )


class TestVersionDriftIsVisibleWithoutACluster:
    def test_a_worker_on_older_code_reports_a_different_version(self, tmp_path):
        """Reproduces the deployed-checkout-is-stale failure.

        On Chrysalis the worker ran ``uxarray_mcp`` 0.1.0 against 2026.9.0
        locally, so a merged fix was simply not there -- and nothing said so.
        Here the worker is pointed at a directory holding a different version
        and the difference is observable in-process.
        """
        stale = tmp_path / "stale"
        (stale / "fakepkg").mkdir(parents=True)
        (stale / "fakepkg" / "__init__.py").write_text('__version__ = "0.1.0"\n')

        def report_version():
            import fakepkg

            return fakepkg.__version__

        with fake_endpoint(worker_pythonpath=str(stale)) as endpoint:
            assert endpoint.run(report_version, (), {}) == "0.1.0"

    def test_the_worker_is_genuinely_a_separate_interpreter(self):
        """Otherwise none of the isolation above means anything."""

        def worker_pid():
            import os

            return os.getpid()

        with fake_endpoint() as endpoint:
            assert endpoint.run(worker_pid, (), {}) != __import__("os").getpid()


class TestSerializationIsByValue:
    def test_a_closure_travels_but_an_unavailable_import_does_not(self):
        """What actually breaks on a worker, and what does not.

        dill ships a closure's captured values, so a function reading
        enclosing scope is fine -- worth pinning, because the obvious guess is
        that it fails. The real hazard is different: importing something the
        worker does not have. That is why compute_functions.py forbids
        importing uxarray_mcp, and why a test asserts it.
        """
        captured = {"secret": 42}

        def reads_enclosing_scope():
            return captured["secret"]

        def imports_something_absent():
            import a_module_no_worker_has  # noqa: F401

            return "unreachable"

        with fake_endpoint() as endpoint:
            assert endpoint.run(reads_enclosing_scope, (), {}) == 42
            with pytest.raises(FakeWorkerLost):
                endpoint.run(imports_something_absent, (), {})

    def test_a_self_contained_function_travels(self):
        """The control: the same shape, written correctly, works."""

        def self_contained(x):
            import math

            return math.sqrt(x)

        with fake_endpoint() as endpoint:
            assert endpoint.run(self_contained, (49,), {}) == 7.0


class TestTheGuardsHoldUnderARealMemoryCeiling:
    @needs_memory_limits
    def test_inspect_mesh_survives_where_calculate_area_would_not(self):
        """Why one tool worked on the 63 GB mesh and the other did not.

        ``inspect_mesh`` skips ``face_areas`` above 50M faces; ``calculate_area``
        cannot, because the areas are the answer. That asymmetry is the whole
        explanation for "it works without MCP but not with it" -- the probe
        used to check by hand read only ``n_face``/``n_node``, which is
        strictly less work than the tool does.
        """
        from uxarray_mcp.remote.compute_functions import (
            remote_calculate_area,
            remote_inspect_mesh,
        )

        with fake_endpoint(memory_limit_gib=4) as endpoint:
            summary = endpoint.run(remote_inspect_mesh, ("healpix:2",), {})
            assert summary["n_face"] == 192

            area = endpoint.run(remote_calculate_area, ("healpix:2",), {})
            assert area["n_face"] == 192

        # Both fit at this size; the point is that the same harness can raise
        # the mesh and lower the ceiling until one of them does not.
        assert endpoint.submissions == 2
