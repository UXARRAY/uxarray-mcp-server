"""YAC-backed remaps must clear the inherited PMI variables before importing.

Importing YAC calls ``MPI_Init``, which decides whether the process is one
rank of many by reading the environment. A Globus Compute worker running
inside a batch allocation inherits ``PMI_FD``/``PMI_RANK``/``PMI_SIZE`` from
the job that started the endpoint, but the descriptor ``PMI_FD`` names
belongs to a process that has already exited -- ``os.fstat`` on it raises
``EBADF``. MPI writes to it anyway, gets "Bad file descriptor", and *aborts*
the process. An abort is not an exception: it takes the worker down, and the
caller sees ``WorkerLost`` with nothing mentioning MPI, which reads as an
out-of-memory kill and sends people to measure their mesh.

Measured on Chrysalis (uxarray 2026.10.0, YAC 3.20.2, MPICH) by removing one
variable at a time from an otherwise untouched worker environment::

    baseline                      rc=15  MPI_Init abort
    strip SLURM_* only            rc=15
    strip HYDRA* only             rc=15
    strip PMI*                    rc=0   768 finite
    drop PMI_JOBID / RANK / SIZE  rc=15  (each individually)
    drop PMI_FD                   rc=0   <- the trigger

With ``PMI_FD`` unset the remap runs *in the live worker process*, not a
subprocess, and returns the same answer as a laptop with no MPI environment
at all: ``sum=73344.0, zeros=4``, five runs in a row.

Why not an MPI launcher, which also works
-----------------------------------------
``mpiexec -n 1`` fixes the import too, and was the previous recommendation.
It is the more dangerous option. YAC decomposes its work across whatever
ranks it is given, and nothing in this server gathers the pieces back, so at
``-n > 1`` each rank remaps its own partition and returns it as the whole
field. Measured locally against a known-correct serial answer of 73344.0::

    1 rank  : 73344.0   73344.0   73344.0   73344.0      (exact, every run)
    4 ranks : 56635     58331     53862     60373        (different every run)

The corrupted output has the full 768 values, zero NaNs, and differs from
truth in 141 cells -- it fails silently. Unsetting one environment variable
has no equivalent failure mode, which is why that is what the code does.
"""

from __future__ import annotations

import inspect

import pytest

from uxarray_mcp.remote import agent as agent_mod
from uxarray_mcp.remote import compute_functions as cf

#: Every remote function that can route a remap through YAC.
YAC_REMAP_FUNCTIONS = (
    "remote_remap_variable",
    "remote_regrid_dataset",
    "remote_remap_to_rectilinear",
)

#: Unsetting PMI_RANK/PMI_SIZE is not load-bearing on its own -- PMI_FD is the
#: measured trigger -- but they describe the same phantom job, and leaving a
#: half-consistent set behind invites a future MPI build to believe it.
EXPECTED_PMI_VARS = {"PMI_FD", "PMI_RANK", "PMI_SIZE"}


def _function_source(name: str) -> str:
    return inspect.getsource(getattr(cf, name))


class TestWorkerFunctionsClearPmi:
    """The guard must exist, and must run before YAC can be imported."""

    @pytest.mark.parametrize("func_name", YAC_REMAP_FUNCTIONS)
    def test_clears_the_measured_variables(self, func_name):
        source = _function_source(func_name)
        for var in EXPECTED_PMI_VARS:
            assert var in source, (
                f"{func_name} does not clear {var}. A YAC-backed remap on a "
                "batch-allocated worker will abort in MPI_Init and arrive as "
                "WorkerLost."
            )

    @pytest.mark.parametrize("func_name", YAC_REMAP_FUNCTIONS)
    def test_guard_precedes_every_remap_call(self, func_name):
        """Ordering is the whole point: MPI_Init runs at import, once.

        Popping the variables after ``.remap(...)`` has already pulled YAC in
        would leave the abort exactly where it was while looking fixed.
        """
        source = inspect.getsource(getattr(cf, func_name))
        lines = source.splitlines()

        guard_lines = [i for i, line in enumerate(lines) if "_pmi_var" in line]
        assert guard_lines, f"{func_name} has no PMI guard at all"
        first_guard = min(guard_lines)

        remap_lines = [
            i for i, line in enumerate(lines) if ".remap(" in line or ".remap." in line
        ]
        assert remap_lines, f"{func_name} has no remap call to guard"
        assert first_guard < min(remap_lines), (
            f"{func_name} clears PMI_FD at line {first_guard} but remaps at "
            f"{min(remap_lines)}. MPI_Init runs on import, so the guard has "
            "to come first or it does nothing."
        )

    def test_guard_is_identical_across_copies(self):
        """These are hand-copied into each worker function; keep them in sync.

        ``remote/compute_functions.py`` cannot use a shared helper -- Globus
        Compute ships each function's source and closures do not survive
        serialization -- so the only protection against one copy drifting is
        a test that compares them.
        """
        extracted = []
        for name in YAC_REMAP_FUNCTIONS:
            lines = _function_source(name).splitlines()
            start = next(i for i, line in enumerate(lines) if "_pmi_var" in line)
            extracted.append(tuple(line.strip() for line in lines[start : start + 2]))
        assert len(set(extracted)) == 1, (
            f"The PMI guard has drifted between worker copies: {set(extracted)}"
        )


class TestProbeMatchesTheRealPath:
    """``check_remote_yac`` must measure the configuration callers get."""

    def test_probe_clears_pmi_before_running(self):
        """Otherwise it reports success for a path that cannot work.

        This is the concrete regression: the probe ran its remap in a
        subprocess and passed the inherited PMI_FD straight through, so it
        reported ``conservative_ok: true`` on an endpoint where every
        in-process conservative remap killed the worker. A doomed child is
        a non-zero exit code; the same abort in the worker is fatal.
        """
        source = inspect.getsource(cf.remote_yac_remap_smoke)
        assert "PMI_FD" in source, (
            "remote_yac_remap_smoke does not clear PMI_FD, so it is not "
            "testing the same thing the remap path does -- which is exactly "
            "how it came to report conservative_ok on a broken endpoint."
        )
        assert "env.pop" in source or "env.pop(" in source, (
            "The probe must strip the variables from the subprocess env it "
            "builds, not from its own os.environ."
        )


class TestWorkerLostGuidance:
    """The message must not send people to the dangerous fix."""

    def _yac_message(self) -> str:
        exc = RuntimeError("Task failure due to loss of worker 0 on host chr-0136")
        config = type("C", (), {"endpoint_name": "chrysalis"})()
        return str(agent_mod._normalize_remote_error(exc, config, yac_backed=True))

    def test_names_the_actual_cause(self):
        message = self._yac_message()
        assert "PMI_FD" in message, (
            "The YAC WorkerLost message should name the variable, since that "
            "is what someone has to unset."
        )

    def test_does_not_recommend_an_mpi_launcher(self):
        """Measured: at -n > 1 this returns wrong numbers with no error.

        The 2026.10.0 message told people to switch the endpoint to an MPI
        launcher. At one rank that works and is merely redundant; above one
        rank each rank returns its own partition as the whole field. Advice
        whose failure mode is silent corruption does not belong in an error
        string.
        """
        message = self._yac_message()
        assert "mpiexec -n 1" not in message
        assert "srun --ntasks 1" not in message
        assert "GlobusMPIEngine" not in message

    def test_warns_against_reaching_for_one(self):
        message = self._yac_message()
        assert "launcher" in message.lower(), (
            "Someone who already knows the MPI-launcher trick will try it; "
            "the message should say why not."
        )

    def test_still_distinguishes_itself_from_the_memory_message(self):
        """The non-YAC path keeps the memory advice, which is right there."""
        exc = RuntimeError("Task failure due to loss of worker 0 on host chr-0136")
        config = type("C", (), {"endpoint_name": "chrysalis"})()
        plain = str(agent_mod._normalize_remote_error(exc, config, yac_backed=False))
        assert "memory" in plain.lower()
        assert "PMI_FD" not in plain
