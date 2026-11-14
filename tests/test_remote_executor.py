"""Submit/timeout/redeem/classify, with the Globus Executor stubbed out."""

from __future__ import annotations

import time
from concurrent.futures import Future
from typing import Any

import pytest

from uxarray_mcp.remote import executor
from uxarray_mcp.remote.config import EndpointProfile, HPCConfig


class _StubExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, tuple[Any, ...]]] = []
        self.next: Future[Any] = Future()

    def submit(self, fn: Any, *args: Any) -> Future[Any]:
        self.calls.append((fn, args))
        fut, self.next = self.next, Future()
        return fut


@pytest.fixture
def stub(monkeypatch, state_dir):
    executor.reset()
    s = _StubExecutor()
    monkeypatch.setattr(executor, "_executor_for", lambda cfg: s)
    return s


@pytest.fixture
def config():
    return HPCConfig(
        endpoints={
            "ep": EndpointProfile(
                name="ep", endpoint_id="0" * 36, path_prefixes=("/hpc/",)
            )
        },
        default_endpoint="ep",
        execution_mode="auto",
        timeout_seconds=1,
    )


def _worker(**over: Any) -> dict[str, Any]:
    import uxarray

    from uxarray_mcp import __version__

    base = {
        "hostname": "n1",
        "uxarray_version": uxarray.__version__,
        "server_version": __version__,
    }
    base.update(over)
    return base


def test_success_attaches_remote_block_and_completes_operation(stub, config):
    stub.next.set_result({"n_face": 12, "_worker": _worker()})
    out = executor.submit("inspect_mesh", {"grid_path": "/hpc/a.nc"}, config=config)
    assert out["n_face"] == 12
    assert out["_remote"]["endpoint"] == "ep" and out["_remote"]["hostname"] == "n1"
    assert "warnings" not in out
    fn, args = stub.calls[0]
    assert fn.__name__ == "run_op" and args == (
        "inspect_mesh",
        {"grid_path": "/hpc/a.nc"},
    )

    from uxarray_mcp.server.state import get_operation

    assert get_operation(out["_remote"]["operation_id"])["status"] == "completed"


def test_version_drift_is_reported_once_per_process(stub, config):
    stub.next.set_result({"_worker": _worker(uxarray_version="0.0.1")})
    first = executor.submit("x", {}, config=config)
    assert any("uxarray version drift" in w for w in first["warnings"])
    stub.next.set_result({"_worker": _worker(uxarray_version="0.0.1")})
    second = executor.submit("x", {}, config=config)
    assert "warnings" not in second


def test_timeout_returns_redeemable_handle(stub, config):
    pending = stub.next  # never resolved before the timeout
    out = executor.submit("slow", {}, timeout_seconds=1, config=config)
    assert out["status"] == "running"
    op = out["operation_id"]
    assert executor.redeem(op)["status"] == "running"
    pending.set_result({"value": 42, "_worker": _worker()})
    done = executor.redeem(op)
    assert done["value"] == 42 and done["_remote"]["operation_id"] == op
    with pytest.raises(executor.RemoteError) as exc:
        executor.redeem("op-does-not-exist")
    assert exc.value.code == executor.OPERATION_UNKNOWN


@pytest.mark.parametrize(
    "message,code",
    [
        (
            "FileNotFoundError: [Errno 2] No such file or directory: '/hpc/x.nc'",
            executor.FILE_NOT_FOUND_ON_WORKER,
        ),
        (
            "ModuleNotFoundError: No module named 'uxarray_mcp'",
            executor.WORKER_MISSING_PACKAGE,
        ),
        (
            'File "coverage.py", line 16\n    import numpy as np\n'
            "ModuleNotFoundError: No module named 'numpy'",
            executor.WORKER_MISSING_PACKAGE,
        ),
        ("ComputeAPIError ENDPOINT_NOT_ONLINE", executor.NO_WORKER),
        (
            "('POST', '.../submit', 'Bearer', 422, 'SEMANTICALLY_INVALID', "
            "'Request payload failed validation: Failed to start or unexpected error:\\n"
            "  (OSError) [Errno 9] Bad file descriptor')",
            executor.ENDPOINT_OFFLINE,
        ),
        ("Task failure due to loss of worker 3 on host n2", executor.WORKER_LOST),
        ("x" * 700 + "\nValueError: bad", executor.REMOTE_FAILED),
    ],
)
def test_worker_errors_are_classified(stub, config, message, code):
    stub.next.set_exception(RuntimeError(message))
    with pytest.raises(executor.RemoteError) as exc:
        executor.submit("x", {}, config=config)
    assert exc.value.code == code
    assert exc.value.operation_id
    assert len(str(exc.value)) < 400


def test_unconfigured_endpoint_is_a_typed_error(state_dir):
    with pytest.raises(executor.RemoteError) as exc:
        executor.submit("x", {}, config=HPCConfig())
    assert exc.value.code == executor.NOT_CONFIGURED


def test_shim_is_self_contained():
    """The shipped function must not reference module globals."""
    import inspect

    from uxarray_mcp.remote import shim

    src = inspect.getsource(shim.run_op)
    assert "from uxarray_mcp.core import ops" in src
    assert shim.run_op.__code__.co_names  # has imports inside; no free vars
    assert not shim.run_op.__code__.co_freevars


def test_shim_runs_a_core_op_locally(structured_mesh_files):
    from uxarray_mcp.remote import shim

    grid, _ = structured_mesh_files
    t = time.monotonic()
    out = shim.run_op("header_facts", {"path": grid})
    assert out["n_face"] > 0
    assert out["_worker"]["server_version"]
    assert time.monotonic() - t < 5
