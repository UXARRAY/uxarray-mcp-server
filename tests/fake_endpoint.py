"""A Globus Compute endpoint that lives in a subprocess instead of a cluster.

Why this exists. Every remote defect found in the CONUS-RRM work took roughly
half an hour to see: SSH with MFA, a redeploy, a Slurm queue, then one tool
call. Four separate bugs hid behind that latency -- a stale checkout, an
orphaned PID file, a client timeout shorter than the job, and an OOM-killed
worker -- and each was only distinguishable from the others *after* paying the
cost again. None of them needed a cluster to reproduce. They needed a worker
that is a different process, with its own memory limit and its own installed
packages, which is all a subprocess is.

What this fakes, and what it does not:

===========================  ==================================================
faithful                     the worker is a real separate process; the
                             function is serialized and shipped by value, so a
                             closure over the test's own state fails here
                             exactly as it fails on a cluster
faithful                     a memory cap is a real ``RLIMIT_AS``, so an
                             oversized job is really killed and arrives as the
                             same ``WorkerLost``-shaped failure
faithful                     the worker can be told to import from a different
                             directory, which is how version drift between a
                             deployed checkout and the submitter is reproduced
not faithful                 no Slurm queue, no network, no Globus auth. Cold
                             start is milliseconds, not 30 s
not faithful                 no multi-node scheduling, no srun, no MPI launcher
===========================  ==================================================

So this catches wiring, serialization, version-drift and memory-ceiling bugs
in seconds. It does not replace ``tests/test_remote_remap_live.py``, which is
the only thing that proves a real endpoint works.

Usage::

    with fake_endpoint(memory_limit_gib=2) as ep:
        result = await agent.calculate_area_remote(path, use_remote=True)
    assert ep.submissions == 1
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch


class FakeWorkerLost(RuntimeError):
    """Raised when the worker process dies, as a real endpoint's would be.

    The message deliberately mimics the shape Globus Compute produces --
    including the trailing "Python version mismatch" boilerplate -- because
    the server's error normalizer reads that text, and a simulator that
    emitted a tidier message would let a normalizer bug through.
    """

    def __init__(self, worker_id: int, host: str, detail: str = "") -> None:
        # The real message is thousands of characters: a full remote
        # traceback, then a serialization-strategy suggestion, then a
        # "Python version mismatch" footer. The length matters -- the
        # normalizer only rewrites messages over 600 chars, so a tidy
        # synthetic message would take a different code path and let a
        # normalizer bug through. The filler reproduces the frames.
        frames = "\n".join(
            f'  File "/parsl/executors/high_throughput/process_worker_pool.py", '
            f"line {line}, in _worker\n    raise v"
            for line in range(400, 460)
        )
        super().__init__(
            f"parsl.executors.high_throughput.errors.WorkerLost: Task failure "
            f"due to loss of worker {worker_id} on host {host}\n"
            f"{frames}\n{detail}\n"
            "example, to use globus_compute_sdk.serialize.AllCodeStrategies:\n"
            "  from globus_compute_sdk import Executor\n"
            " One common cause of WorkerLost exceptions is Python version "
            "mismatch\n between the submitting Globus Compute SDK and the "
            "Endpoint, as\n Python versions."
        )


#: Whether a memory ceiling can actually be imposed here.
#:
#: macOS refuses RLIMIT_AS, RLIMIT_DATA and RLIMIT_RSS with "current limit
#: exceeds maximum limit", so a cap would silently not apply. Rather than
#: pretend, tests that need one skip on darwin and run in CI, which is Linux.
MEMORY_LIMITS_ENFORCED = sys.platform.startswith("linux")


@dataclass
class FakeEndpoint:
    """Records what was submitted and how each call ended."""

    memory_limit_gib: float | None = None
    worker_pythonpath: str | None = None
    python_executable: str = sys.executable
    submissions: int = 0
    calls: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def run(self, func: Callable, args: tuple, kwargs: dict) -> Any:
        """Execute ``func`` in a child process and return its result."""
        self.submissions += 1
        self.calls.append(getattr(func, "__name__", repr(func)))

        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / "call.pkl"
            result_path = Path(tmp) / "result.pkl"
            # dill, not pickle: Globus Compute serializes with dill, which can
            # ship a function defined inside a test. Using pickle here would
            # reject those and make the simulator stricter than the thing it
            # simulates -- failing tests that would really have worked.
            import dill

            payload.write_bytes(dill.dumps((func, args, kwargs), recurse=True))

            runner = textwrap.dedent(
                f"""
                import dill, resource, sys
                limit = {self._limit_bytes()!r}
                if limit is not None:
                    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
                func, args, kwargs = dill.loads(open({str(payload)!r}, "rb").read())
                out = func(*args, **kwargs)
                open({str(result_path)!r}, "wb").write(dill.dumps(out))
                """
            )

            env = dict(os.environ)
            if self.worker_pythonpath is not None:
                env["PYTHONPATH"] = self.worker_pythonpath

            proc = subprocess.run(
                [self.python_executable, "-c", runner],
                capture_output=True,
                text=True,
                env=env,
                timeout=600,
            )

            if proc.returncode != 0 or not result_path.exists():
                tail = (proc.stderr or "")[-1500:]
                self.failures.append(tail)
                # MemoryError from RLIMIT_AS, or a signal, both mean the
                # worker did not survive -- which is what the caller sees.
                raise FakeWorkerLost(0, "fake-worker-0", tail)

            import dill

            return dill.loads(result_path.read_bytes())

    def _limit_bytes(self) -> int | None:
        if self.memory_limit_gib is None:
            return None
        return int(self.memory_limit_gib * 1024**3)


@contextlib.contextmanager
def fake_endpoint(
    memory_limit_gib: float | None = None,
    worker_pythonpath: str | None = None,
) -> Iterator[FakeEndpoint]:
    """Route ``globus_compute_sdk.Executor`` submissions to a subprocess.

    Parameters
    ----------
    memory_limit_gib
        Hard ``RLIMIT_AS`` for the worker. A job that exceeds it is really
        killed, so the failure path is exercised rather than mocked.
    worker_pythonpath
        ``PYTHONPATH`` for the worker only. Point it at an older checkout to
        reproduce the deployed-code-is-stale failure without a cluster.
    """
    endpoint = FakeEndpoint(
        memory_limit_gib=memory_limit_gib,
        worker_pythonpath=worker_pythonpath,
    )

    class _Future:
        def __init__(self, fn, args, kwargs):
            self._fn, self._args, self._kwargs = fn, args, kwargs

        def result(self, timeout=None):  # noqa: ARG002 - matches the SDK
            return endpoint.run(self._fn, self._args, self._kwargs)

    class _Executor:
        def __init__(self, *a, **k):
            self.client = type("C", (), {"fx_serializer": None})()
            self._stopped = False

        def submit(self, fn, *args, **kwargs):
            return _Future(fn, args, kwargs)

        def shutdown(self, *a, **k):
            self._stopped = True

    with patch("globus_compute_sdk.Executor", _Executor):
        yield endpoint
