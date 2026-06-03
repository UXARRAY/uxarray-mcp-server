"""Execution mode control and HPC diagnostics tools."""

from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path
from typing import Any, Dict, List

import yaml

from uxarray_mcp.provenance import attach_provenance
from uxarray_mcp.remote.config import normalize_execution_mode
from uxarray_mcp.state import OperationTracker

_VALID_MODES = ("local", "hpc", "auto")
_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config.yaml"


def _load_globus_compute_sdk():
    """Load Globus Compute SDK classes only when HPC functionality is needed."""
    from globus_compute_sdk import Client, Executor
    from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

    return Client, Executor, AllCodeStrategies, ComputeSerializer


def _make_check(
    name: str,
    passed: bool,
    summary: str,
    *,
    details: Dict[str, Any] | None = None,
    guidance: str | None = None,
) -> Dict[str, Any]:
    """Build a consistent diagnostic check payload."""
    result: Dict[str, Any] = {
        "name": name,
        "passed": passed,
        "summary": summary,
    }
    if details:
        result["details"] = details
    if guidance:
        result["guidance"] = guidance
    return result


def _guidance_for_error(message: str) -> str | None:
    """Return targeted next-step guidance for common HPC setup failures."""
    lowered = message.lower()

    if (
        "authorization code" in lowered
        or "eof was read when an authorization code was expected" in lowered
    ):
        return (
            "Local Globus auth is missing. Run `uv run python -c "
            '"from globus_compute_sdk import Client; Client()"` in an '
            "interactive terminal and complete the browser login flow."
        )
    if (
        "missingtokeneror" in lowered
        or "missingtokenderror" in lowered
        or "funcx_service" in lowered
    ):
        return (
            "Local Globus tokens are missing for the Compute service. "
            "Re-run the interactive `Client()` login flow on the machine "
            "hosting the MCP server."
        )
    if "qsub: command not found" in lowered:
        return (
            "The spawned user endpoint cannot find PBS commands. Add `/opt/pbs/bin` "
            "to the endpoint environment (for example via `user_environment.yaml` "
            "or `endpoint_setup`) and restart the endpoint."
        )
    if "systemexit" in lowered and "73" in lowered:
        return (
            "The child endpoint exited during startup. On clusters like Improv, "
            "this often means stale daemon PID files or competing endpoint starts "
            "across multiple login nodes. Kill old endpoint processes, remove "
            "`~/.globus_compute/.../daemon.pid`, and restart the endpoint from a "
            "single login node only."
        )
    if "access_refused" in lowered or "invalid credentials" in lowered:
        return (
            "The endpoint manager or child endpoint lost its AMQP credentials. "
            "Restart the endpoint and, if needed, re-run `globus-compute-endpoint "
            "start <name>` interactively on the cluster."
        )
    if "no module named 'uxarray'" in lowered:
        return (
            "Install `uxarray` in the remote endpoint environment used by the worker "
            "nodes, then restart the endpoint."
        )
    if "no module named 'globus_compute_sdk'" in lowered:
        return (
            "Install the HPC dependencies locally with `uv sync --extra hpc` "
            "before using remote execution."
        )
    return None


def _exception_details(exc: Exception) -> Dict[str, Any]:
    """Return a richer, serializable view of an exception chain."""
    details: Dict[str, Any] = {
        "error": str(exc),
        "exception_type": type(exc).__name__,
        "exception_repr": repr(exc),
    }

    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        details["cause_type"] = type(cause).__name__
        details["cause"] = str(cause)
        details["cause_repr"] = repr(cause)

    context = getattr(exc, "__context__", None)
    if context is not None and context is not cause:
        details["context_type"] = type(context).__name__
        details["context"] = str(context)
        details["context_repr"] = repr(context)

    return details


def _run_sync(awaitable_factory) -> Dict[str, Any]:
    """Run an async call from sync code in CLI and FastMCP contexts."""
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, awaitable_factory()).result()
    except RuntimeError:
        return asyncio.run(awaitable_factory())


def probe_path_access(
    file_path: str,
    use_remote: bool = False,
    inspect_netcdf: bool = True,
    endpoint: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    """Probe whether a path is reachable and readable.

    Use this before `inspect_mesh` or `inspect_variable` when bringing up
    a new cluster. It answers the simpler question first: can the endpoint read
    the exact target path at all?
    """
    tracker = OperationTracker("probe_path_access", session_id=session_id)
    tracker.stage("preparing", "Preparing path probe.")
    from uxarray_mcp.remote.compute_functions import remote_probe_path

    if not use_remote:
        tracker.stage("running", "Running path probe locally.")
        result = remote_probe_path(file_path, inspect_netcdf)
        result = attach_provenance(
            result,
            tool="probe_path_access",
            inputs={
                "file_path": file_path,
                "use_remote": use_remote,
                "inspect_netcdf": inspect_netcdf,
                "endpoint": endpoint,
                "session_id": session_id,
            },
            venue="local",
        )
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.succeed("Local path probe completed.")
        return result

    from uxarray_mcp.remote.agent import get_agent

    agent = get_agent(endpoint=endpoint, path=file_path)
    if not agent.config.endpoint_id:
        tracker.stage("fallback", "No endpoint configured; probing locally.")
        result = remote_probe_path(file_path, inspect_netcdf)
        result = attach_provenance(
            result,
            tool="probe_path_access",
            inputs={
                "file_path": file_path,
                "use_remote": use_remote,
                "inspect_netcdf": inspect_netcdf,
                "endpoint": endpoint,
                "session_id": session_id,
            },
            venue="local",
        )
        result["_provenance"]["warnings"].append(
            "No HPC endpoint configured; ran path probe locally."
        )
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.succeed(
            "Path probe completed locally because no endpoint is configured."
        )
        return result

    tracker.stage("submitted", "Submitting remote path probe.")
    result = _run_sync(
        lambda: agent.probe_path_remote(file_path, inspect_netcdf, use_remote)
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    tracker.succeed("Remote path probe completed.")
    return result


def validate_hpc_setup(
    run_remote_probe: bool = True,
    probe_timeout_seconds: int = 30,
    sample_path: str | None = None,
    endpoint: str | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    """Validate end-to-end HPC readiness beyond simple endpoint registration.

    The existing endpoint health check only proves that the endpoint manager is
    visible to Globus Compute. This diagnostic goes deeper: it validates local
    SDK/auth state, endpoint status, and optionally submits a tiny remote probe
    so scheduler or worker bootstrap failures surface as structured output.
    """
    tracker = OperationTracker("validate_hpc_setup", session_id=session_id)
    tracker.stage("config", "Loading HPC configuration.")
    from uxarray_mcp.remote.config import load_config

    base_config = load_config(_CONFIG_PATH)
    config = base_config.for_endpoint(endpoint=endpoint, path=sample_path)
    checks: List[Dict[str, Any]] = []
    checks.append(
        _make_check(
            "config",
            bool(config.endpoint_id),
            (
                f"Configured endpoint_id={config.endpoint_id!r} "
                f"({config.endpoint_name or 'default'}) in {_CONFIG_PATH.name}."
                if config.endpoint_id
                else f"No endpoint could be resolved in {_CONFIG_PATH.name}."
            ),
            details={
                "mode": config.execution_mode,
                "endpoint_name": config.endpoint_name,
                "default_endpoint": config.default_endpoint,
                "configured_endpoints": config.endpoint_names,
                "config_path": str(_CONFIG_PATH),
            },
            guidance=(
                "Copy config.yaml.example to config.yaml and set "
                "`hpc.globus_compute.endpoint_id`, or define "
                "`hpc.endpoints` and pass endpoint='name'."
                if not config.endpoint_id
                else None
            ),
        )
    )

    endpoint_status = "no_endpoint"
    remote_probe: Dict[str, Any] | None = None
    sample_path_probe: Dict[str, Any] | None = None
    result: Dict[str, Any]

    if not config.endpoint_id:
        result = {
            "passed": False,
            "mode": config.execution_mode,
            "endpoint_name": config.endpoint_name,
            "endpoint_id": config.endpoint_id,
            "endpoint_status": endpoint_status,
            "checks": checks,
            "remote_probe": remote_probe,
            "sample_path_probe": sample_path_probe,
        }
        result = attach_provenance(
            result,
            tool="validate_hpc_setup",
            inputs={
                "run_remote_probe": run_remote_probe,
                "probe_timeout_seconds": probe_timeout_seconds,
                "sample_path": sample_path,
                "endpoint": endpoint,
                "session_id": session_id,
            },
        )
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.fail("HPC validation failed because no endpoint is configured.")
        return result

    try:
        tracker.stage("dependencies", "Loading local Globus Compute dependencies.")
        Client, Executor, AllCodeStrategies, ComputeSerializer = (
            _load_globus_compute_sdk()
        )
    except ImportError as exc:
        checks.append(
            _make_check(
                "local_dependencies",
                False,
                "Local HPC dependencies are not installed.",
                details=_exception_details(exc),
                guidance="Run `uv sync --extra hpc` in this checkout.",
            )
        )
        result = {
            "passed": False,
            "mode": config.execution_mode,
            "endpoint_name": config.endpoint_name,
            "endpoint_id": config.endpoint_id,
            "endpoint_status": endpoint_status,
            "checks": checks,
            "remote_probe": remote_probe,
            "sample_path_probe": sample_path_probe,
        }
        result = attach_provenance(
            result,
            tool="validate_hpc_setup",
            inputs={
                "run_remote_probe": run_remote_probe,
                "probe_timeout_seconds": probe_timeout_seconds,
                "sample_path": sample_path,
                "endpoint": endpoint,
                "session_id": session_id,
            },
        )
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.fail("HPC validation failed because local dependencies are missing.")
        return result

    try:
        tracker.stage("auth", "Querying endpoint status through the local SDK.")
        from uxarray_mcp.remote import health as _health

        client = _health._get_client()
        raw_endpoint_status = client.get_endpoint_status(config.endpoint_id)
        endpoint_payload = (
            raw_endpoint_status
            if isinstance(raw_endpoint_status, dict)
            else {"status": str(raw_endpoint_status)}
        )
        endpoint_status = endpoint_payload.get("status", "unknown")
        checks.append(
            _make_check(
                "endpoint_status",
                endpoint_status in {"online", "healthy"},
                f"Endpoint manager reports status={endpoint_status!r}.",
                details={"raw_status": endpoint_payload},
                guidance=(
                    None
                    if endpoint_status in {"registered", "active", "online", "healthy"}
                    else "Start or restart the endpoint on the cluster before using remote execution."
                ),
            )
        )
    except Exception as exc:
        message = str(exc) or repr(exc)
        checks.append(
            _make_check(
                "local_auth",
                False,
                "Local Globus Compute client could not query endpoint status.",
                details=_exception_details(exc),
                guidance=_guidance_for_error(message),
            )
        )
        result = {
            "passed": False,
            "mode": config.execution_mode,
            "endpoint_name": config.endpoint_name,
            "endpoint_id": config.endpoint_id,
            "endpoint_status": "unreachable",
            "checks": checks,
            "remote_probe": remote_probe,
            "sample_path_probe": sample_path_probe,
        }
        result = attach_provenance(
            result,
            tool="validate_hpc_setup",
            inputs={
                "run_remote_probe": run_remote_probe,
                "probe_timeout_seconds": probe_timeout_seconds,
                "sample_path": sample_path,
                "endpoint": endpoint,
                "session_id": session_id,
            },
        )
        result["_provenance"]["operation_id"] = tracker.operation_id
        tracker.fail("HPC validation failed while querying endpoint status.")
        return result

    if run_remote_probe and endpoint_status in {"online", "healthy"}:
        from uxarray_mcp.remote.compute_functions import (
            remote_probe_path,
            remote_runtime_probe,
        )

        try:
            tracker.stage("submitted", "Submitting remote runtime probe.")
            executor = Executor(
                endpoint_id=config.endpoint_id,
                serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
            )
            future = executor.submit(remote_runtime_probe)
            remote_probe = future.result(
                timeout=min(config.timeout_seconds, probe_timeout_seconds)
            )
            checks.append(
                _make_check(
                    "remote_probe",
                    True,
                    "A tiny remote task executed successfully on the HPC worker.",
                    details=remote_probe,
                )
            )
            if sample_path:
                tracker.stage("verifying", "Submitting remote sample-path probe.")
                sample_future = executor.submit(remote_probe_path, sample_path, True)
                sample_path_probe = sample_future.result(
                    timeout=min(config.timeout_seconds, probe_timeout_seconds)
                )
                sample_ok = bool(
                    sample_path_probe.get("exists")
                    and sample_path_probe.get("readable")
                )
                checks.append(
                    _make_check(
                        "sample_path_probe",
                        sample_ok,
                        (
                            f"Remote worker can read sample path {sample_path!r}."
                            if sample_ok
                            else f"Remote worker could not read sample path {sample_path!r}."
                        ),
                        details=sample_path_probe,
                        guidance=(
                            None
                            if sample_ok
                            else "Verify that the path exists on the remote filesystem and that the endpoint identity can read it."
                        ),
                    )
                )
        except Exception as exc:
            message = str(exc) or repr(exc)
            checks.append(
                _make_check(
                    "remote_probe",
                    False,
                    "The endpoint manager is online, but a real remote task failed.",
                    details=_exception_details(exc),
                    guidance=_guidance_for_error(message)
                    or (
                        "Inspect the child endpoint logs on the cluster. "
                        "The manager may be online while the spawned user endpoint "
                        "or scheduler submission path is failing."
                    ),
                )
            )

    passed = all(check["passed"] for check in checks)
    result = {
        "passed": passed,
        "mode": config.execution_mode,
        "endpoint_name": config.endpoint_name,
        "endpoint_id": config.endpoint_id,
        "endpoint_status": endpoint_status,
        "checks": checks,
        "remote_probe": remote_probe,
        "sample_path_probe": sample_path_probe,
    }
    result = attach_provenance(
        result,
        tool="validate_hpc_setup",
        inputs={
            "run_remote_probe": run_remote_probe,
            "probe_timeout_seconds": probe_timeout_seconds,
            "sample_path": sample_path,
            "endpoint": endpoint,
            "session_id": session_id,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    if passed:
        tracker.succeed("HPC validation completed.")
    else:
        tracker.fail("HPC validation completed with failed checks.")
    return result


def get_execution_mode() -> Dict[str, Any]:
    """Return the current execution mode and endpoint manager status.

    Returns
    -------
    dict
        Dictionary with keys ``mode``, ``endpoint_id``, ``endpoint_status``,
        ``description``, and ``status_note``.

        ``endpoint_status`` is one of:

        - ``"registered"`` — manager is running; tasks can be submitted and the
          scheduler will allocate workers on demand.
        - ``"offline"`` — manager is not running; SSH in and run
          ``globus-compute-endpoint start <name>``.
        - ``"unreachable"`` — cannot contact Globus Compute.
        - ``"no_endpoint"`` — no endpoint is configured.

        To confirm a worker actually responds, call ``endpoint_status(probe=True)``
        or ``validate_hpc_setup()``.

    Examples
    --------
    >>> get_execution_mode()
    {"mode": "auto", "endpoint_id": "00000000-...", "endpoint_status": "registered"}
    """
    from uxarray_mcp.remote.config import load_config
    from uxarray_mcp.remote.health import check_endpoint_manager_status

    config = load_config(_CONFIG_PATH)
    status_info = check_endpoint_manager_status(config)

    descriptions = {
        "local": "All computations run on this machine regardless of HPC availability.",
        "hpc": "All computations are sent to the HPC endpoint. Fails if endpoint is offline.",
        "auto": "Uses HPC when the endpoint manager is registered, local otherwise.",
    }

    result: Dict[str, Any] = {
        "mode": config.execution_mode,
        "endpoint_name": config.endpoint_name,
        "endpoint_id": config.endpoint_id,
        "default_endpoint": config.default_endpoint,
        "configured_endpoints": config.endpoint_names,
        "endpoint_status": status_info.get("status", "unknown"),
        "description": descriptions.get(config.execution_mode, "Unknown mode."),
        "status_note": (
            '"registered" means the manager process is running and will route '
            "Slurm/PBS submissions. It does not confirm workers are active. "
            "Call endpoint_status(probe=True) or validate_hpc_setup() to confirm "
            "a real worker responds."
        ),
    }

    return attach_provenance(
        result,
        tool="get_execution_mode",
        inputs={},
    )


def endpoint_status(
    endpoint: str | None = None,
    force: bool = False,
    probe: bool = False,
    probe_timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """Check the status of one or all configured HPC endpoints.

    By default this is a **fast, cached manager check** — it queries the Globus
    cloud about the endpoint manager process. Use ``probe=True`` to also submit
    a lightweight task that confirms a real worker responds.

    Status values
    -------------
    ``"registered"``
        Manager is running; Slurm/PBS will allocate workers on demand.
        This is the normal idle state between jobs.
    ``"active"``
        Manager is running **and** a probe task confirmed a worker responded.
        Only returned when ``probe=True``.
    ``"offline"``
        Manager is not running. SSH in and run
        ``globus-compute-endpoint start <name>``.
    ``"unreachable"``
        Cannot contact Globus Compute (auth or network error).
    ``"no_endpoint"``
        No endpoint UUID configured.

    Parameters
    ----------
    endpoint : str | None
        Named endpoint to check, or ``None`` to check all configured endpoints.
    force : bool, default False
        Bypass the in-process cache and re-query the SDK.
    probe : bool, default False
        After the manager check, submit a tiny task to confirm a worker
        responds. Raises the status from ``"registered"`` to ``"active"``
        if successful. Takes 15–90 s depending on scheduler queue depth.
    probe_timeout_seconds : int, default 60
        Timeout for the worker probe task (only used when ``probe=True``).

    Returns
    -------
    dict
        Keys ``endpoints`` (list of per-endpoint rows), ``mode``,
        ``default_endpoint``, and ``_provenance``.

    Examples
    --------
    >>> endpoint_status()
    {"endpoints": [{"name": "chrysalis", "status": "registered", ...}], ...}

    >>> endpoint_status(endpoint="chrysalis", probe=True, probe_timeout_seconds=90)
    {"endpoints": [{"name": "chrysalis", "status": "active",
                    "node": "chr-0497", "python": "3.13.13", ...}], ...}
    """
    from uxarray_mcp.remote.config import load_config
    from uxarray_mcp.remote.health import (
        check_all_endpoints_manager_status,
        check_endpoint_manager_status,
        probe_endpoint_worker,
    )

    base_config = load_config(_CONFIG_PATH)

    if endpoint is not None:
        scoped = base_config.for_endpoint(endpoint=endpoint)
        row = check_endpoint_manager_status(scoped, force=force)
        if probe and row.get("status") in ("registered", "active"):
            probe_row = probe_endpoint_worker(
                scoped, timeout_seconds=probe_timeout_seconds
            )
            row.update(probe_row)
        endpoints_payload = [{"name": scoped.endpoint_name or endpoint, **row}]
    else:
        endpoints_payload = check_all_endpoints_manager_status(base_config, force=force)
        if probe:
            for i, row in enumerate(endpoints_payload):
                if row.get("status") in ("registered", "active"):
                    name = row["name"]
                    scoped = base_config.for_endpoint(endpoint=name)
                    probe_row = probe_endpoint_worker(
                        scoped, timeout_seconds=probe_timeout_seconds
                    )
                    endpoints_payload[i] = {**row, **probe_row}

    result: Dict[str, Any] = {
        "endpoints": endpoints_payload,
        "mode": base_config.execution_mode,
        "default_endpoint": base_config.default_endpoint,
    }

    return attach_provenance(
        result,
        tool="endpoint_status",
        inputs={
            "endpoint": endpoint,
            "force": force,
            "probe": probe,
            "probe_timeout_seconds": probe_timeout_seconds if probe else None,
        },
    )


def set_execution_mode(mode: str) -> Dict[str, Any]:
    """Switch execution mode at runtime and persist it to config.yaml.

    Parameters
    ----------
    mode : str
        Execution mode to set. One of:
        - "local"  — always run on this machine
        - "hpc"    — always send to HPC endpoint (fails if endpoint is down)
        - "auto"   — use HPC when available, fall back to local otherwise

    Returns
    -------
    dict
        Dictionary containing:
        - mode: The new execution mode
        - previous_mode: The mode that was active before this call
        - endpoint_id: Configured endpoint UUID, or None
        - message: Confirmation message

    Raises
    ------
    ValueError
        If mode is not one of "local", "hpc", or "auto".

    Example:
        >>> set_execution_mode("local")
        {"mode": "local", "previous_mode": "auto", "message": "Switched to local mode."}

        >>> set_execution_mode("auto")
        {"mode": "auto", "previous_mode": "local", "message": "Switched to auto mode."}
    """
    try:
        normalized_mode = normalize_execution_mode(mode)
    except ValueError as exc:
        raise ValueError(
            f"Invalid mode {mode!r}. Must be one of: {', '.join(_VALID_MODES)}"
        ) from exc

    from uxarray_mcp.remote import agent as _agent_module
    from uxarray_mcp.remote.config import load_config

    config = load_config(_CONFIG_PATH)
    previous_mode = config.execution_mode

    # Read the current config file and update execution_mode in place
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    if "hpc" not in data or not isinstance(data.get("hpc"), dict):
        data["hpc"] = {}
    data["hpc"]["execution_mode"] = normalized_mode

    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    # Reset singleton agent so next call picks up the new config
    _agent_module._agent_instance = None
    _agent_module._agent_instances.clear()

    # Drop cached endpoint health so the next status check re-queries the SDK
    from uxarray_mcp.remote.health import invalidate_cache as _invalidate_health

    _invalidate_health()

    result: Dict[str, Any] = {
        "mode": normalized_mode,
        "previous_mode": previous_mode,
        "endpoint_id": config.endpoint_id,
        "message": (
            f"Switched to {normalized_mode!r} mode. "
            f"Config saved to {_CONFIG_PATH.name}."
        ),
    }

    return attach_provenance(
        result,
        tool="set_execution_mode",
        inputs={"mode": mode},
    )
