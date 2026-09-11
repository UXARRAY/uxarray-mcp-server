"""An in-flight remote task must be findable after the process that sent it.

Before this, a submitted Globus Compute task existed in exactly one place: a
future held by a Python process that was blocked waiting on it. Kill that
process -- a timeout, a crashed client, a laptop closing -- and the job keeps
burning cluster time with nothing left anywhere that names it. The operation
record already survived the process; it just did not carry the handle.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from uxarray_mcp.state import (
    CURRENT_OPERATION,
    OperationTracker,
    create_operation,
    get_operation,
    record_task_handle,
)


class _LateFuture:
    """A future that gets its task id after submit, the way the real one does."""

    def __init__(self, delay: float = 0.0, task_id: str | None = "task-abc"):
        self.task_id: str | None = None
        self._done = False
        if delay:
            timer = threading.Timer(delay, self._assign, args=(task_id,))
            timer.daemon = True
            timer.start()
        else:
            self._assign(task_id)

    def _assign(self, task_id: str | None) -> None:
        self.task_id = task_id

    def done(self) -> bool:
        return self._done


class _Config:
    endpoint_id = "endpoint-uuid"
    endpoint_name = "chrysalis"
    timeout_seconds = 1


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestTheRecordCarriesTheHandle:
    def test_a_fresh_operation_declares_the_keys_as_empty(self, state_dir):
        """Present and null, not absent.

        A reader that has to distinguish "no task" from "old record written
        before this existed" gets to, and the file shape stops changing
        halfway through an operation's life.
        """
        record = create_operation(tool_name="inspect_mesh")

        assert record["endpoint_id"] is None
        assert record["task_id"] is None
        assert record["submitted_at"] is None

    def test_the_handle_is_written_where_another_process_can_read_it(self, state_dir):
        record = create_operation(tool_name="inspect_mesh")

        record_task_handle(
            record["operation_id"], task_id="task-abc", endpoint_id="endpoint-uuid"
        )

        reloaded = get_operation(record["operation_id"])
        assert reloaded["task_id"] == "task-abc"
        assert reloaded["endpoint_id"] == "endpoint-uuid"
        assert reloaded["submitted_at"] is not None
        assert "task-abc" in reloaded["events"][-1]["message"]

    def test_the_tracker_keeps_the_handle_in_hand_as_well(self, state_dir):
        """The error path reads it off the tracker, not off disk."""
        tracker = OperationTracker("inspect_mesh", endpoint_id="endpoint-uuid")

        tracker.record_submission("task-abc")

        assert tracker.task_id == "task-abc"
        assert get_operation(tracker.operation_id)["task_id"] == "task-abc"

    def test_a_second_process_can_find_the_task(self, state_dir, tmp_path):
        """The whole point, done the only way that proves it.

        Same assertion in-process would pass on a dict cached in memory.
        """
        tracker = OperationTracker("inspect_mesh", endpoint_id="endpoint-uuid")
        tracker.record_submission("task-abc")

        script = textwrap.dedent(
            """
            import json, os, sys
            from uxarray_mcp.state import get_operation
            print(json.dumps(get_operation(sys.argv[1])))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script, tracker.operation_id],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "UXARRAY_MCP_STATE_DIR": str(state_dir)},
        )

        recovered = json.loads(completed.stdout)
        assert recovered["task_id"] == "task-abc"
        assert recovered["endpoint_id"] == "endpoint-uuid"


class TestTheWatcherCatchesALateTaskId:
    """``submit()`` returns before the web service has acknowledged anything.

    ``future.task_id`` is ``None`` at that line, so reading it there stores
    nothing and looks like it worked.
    """

    def test_a_handle_that_arrives_late_is_still_recorded(self, state_dir):
        from uxarray_mcp.remote.agent import _record_task_handle_when_assigned

        tracker = OperationTracker("inspect_mesh")
        future = _LateFuture(delay=0.1)

        token = CURRENT_OPERATION.set(tracker)
        try:
            _record_task_handle_when_assigned(future, _Config())
            assert _wait_for(lambda: tracker.task_id == "task-abc")
        finally:
            CURRENT_OPERATION.reset(token)

        stored = get_operation(tracker.operation_id)
        assert stored["task_id"] == "task-abc"
        assert stored["endpoint_id"] == "endpoint-uuid"

    def test_an_untracked_submit_is_left_alone(self, state_dir):
        """Health probes and validation submits are not user work.

        They run with no tracker in context and must not invent an operation
        record to hang a handle on.
        """
        from uxarray_mcp.remote.agent import _record_task_handle_when_assigned

        before = len(list((state_dir / "operations").glob("*.json")))

        _record_task_handle_when_assigned(_LateFuture(), _Config())
        time.sleep(0.2)

        assert len(list((state_dir / "operations").glob("*.json"))) == before

    def test_the_watcher_gives_up_when_the_task_finishes_without_an_id(
        self, state_dir, monkeypatch
    ):
        """A submission that failed outright never gets an id.

        The watcher must notice and stop rather than hold a thread open for
        the full wait, and must not write a null handle over a real one.
        """
        from uxarray_mcp.remote import agent as agent_module

        monkeypatch.setattr(agent_module, "_TASK_ID_WAIT_SECONDS", 5.0)
        tracker = OperationTracker("inspect_mesh")
        future = _LateFuture(task_id=None)
        future._done = True

        token = CURRENT_OPERATION.set(tracker)
        try:
            agent_module._record_task_handle_when_assigned(future, _Config())
            time.sleep(0.2)
        finally:
            CURRENT_OPERATION.reset(token)

        assert tracker.task_id is None
        assert get_operation(tracker.operation_id)["task_id"] is None


class TestTheTimeoutSaysWhatIsStillRunning:
    def test_a_timeout_names_the_task_it_left_behind(self, state_dir, monkeypatch):
        """The message a user acts on is the one the exception carries."""
        from uxarray_mcp.tools import remote_tools

        class _Agent:
            config = _Config()

        monkeypatch.setattr(remote_tools, "_endpoint_is_ready", lambda _a: (True, "ok"))
        monkeypatch.setattr(
            remote_tools, "_path_is_locally_reachable", lambda _p: False
        )
        monkeypatch.setattr(
            "uxarray_mcp.remote.agent.get_agent", lambda **_kw: _Agent()
        )

        def _submit_then_time_out(_agent):
            CURRENT_OPERATION.get().record_submission("task-abc")
            raise TimeoutError("waited long enough")

        with pytest.raises(RuntimeError) as caught:
            remote_tools._run_with_optional_hpc(
                tool_name="inspect_mesh",
                use_remote=True,
                path_hint="/scratch/mesh.nc",
                session_id=None,
                local_call=lambda: {"_provenance": {}},
                remote_call=_submit_then_time_out,
            )

        assert "task-abc" in str(caught.value)

    def test_the_context_is_cleared_afterwards(self, state_dir, monkeypatch):
        """A tracker left in context would be adopted by the next submit."""
        from uxarray_mcp.tools import remote_tools

        class _Agent:
            config = _Config()

        monkeypatch.setattr(remote_tools, "_endpoint_is_ready", lambda _a: (True, "ok"))
        monkeypatch.setattr(
            "uxarray_mcp.remote.agent.get_agent", lambda **_kw: _Agent()
        )

        remote_tools._run_with_optional_hpc(
            tool_name="inspect_mesh",
            use_remote=True,
            path_hint=None,
            session_id=None,
            local_call=lambda: {"_provenance": {}},
            remote_call=lambda _a: {"_provenance": {}},
        )

        assert CURRENT_OPERATION.get() is None
