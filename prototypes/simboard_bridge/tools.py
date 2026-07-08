"""Prototype MCP-shaped tools that bridge SimBoard → uxarray-mcp.

If/when graduated, these would live at ``src/uxarray_mcp/tools/simboard.py``.
For now they sit under ``prototypes/`` to keep them out of the supported
server surface until Tom Vo blesses the integration.

The two tools, in plain English:

- ``simboard_list_simulations`` — "find me runs matching X". Returns a
  ranked list of simulations with enough metadata for an AI to pick one.
- ``simboard_get_paths`` — "given this simulation id, where are its files
  and what machine do I run on?". Returns the data needed to hand off to
  ``uxarray-mcp.run_analysis``.

Filtering today is **client-side** because SimBoard's current list APIs
only take ``case_name``/``case_group``. As their API grows we'll push
filters down server-side and remove the post-filter pass below.
"""

from __future__ import annotations

from typing import Any

from prototypes.simboard_bridge.client import SimBoardClient


def simboard_list_simulations(
    grid_name: str | None = None,
    machine: str | None = None,
    hpc_username: str | None = None,
    compset: str | None = None,
    status: str | None = "completed",
    limit: int = 10,
    client: SimBoardClient | None = None,
) -> dict[str, Any]:
    """Find E3SM simulations in the SimBoard catalog matching the given filters.

    Use this when the user asks "find runs that...", "what simulations are
    available for...", or otherwise wants to *discover* a simulation before
    analyzing it. The returned ``simulations`` list contains enough metadata
    (grid_name, machine, status, execution_id) for the AI to pick one, then
    call ``simboard_get_paths`` to get file locations.

    Args:
        grid_name: substring match against the mesh/grid name
            (e.g. ``"oRRS18to6"``, ``"ne30pg2"``). Case-insensitive.
        machine: HPC machine name (e.g. ``"perlmutter"``, ``"chrysalis"``).
        hpc_username: HPC username that owns the run.
        compset: substring match against the E3SM compset (e.g. ``"F2010"``).
        status: filter by status (default ``"completed"``;
            pass ``None`` to include all).
        limit: max number of simulations to return.
        client: injected SimBoardClient for testing.

    Returns:
        A dict with ``count``, ``simulations`` (list of summary dicts), and
        ``_provenance`` (source URL + filter echoes).
    """
    client = client or SimBoardClient()
    cases = client.list_cases()

    out: list[dict[str, Any]] = []
    for case in cases:
        case_machines = [m.lower() for m in (case.get("machineNames") or [])]
        case_users = [u.lower() for u in (case.get("hpcUsernames") or [])]
        if machine and machine.lower() not in case_machines:
            continue
        if hpc_username and hpc_username.lower() not in case_users:
            continue
        for sim in case.get("simulations") or []:
            if status and (sim.get("status") or "").lower() != status.lower():
                continue
            row = {
                "sim_id": sim.get("id"),
                "execution_id": sim.get("executionId"),
                "case_name": case.get("name"),
                "machine_names": case.get("machineNames"),
                "hpc_usernames": case.get("hpcUsernames"),
                "status": sim.get("status"),
                "simulation_start_date": sim.get("simulationStartDate"),
                "simulation_end_date": sim.get("simulationEndDate"),
            }
            out.append(row)

    # grid_name and compset live on the sim-detail object, not on the case
    # list. Filter by enriching the top N candidates on demand to avoid
    # hammering the API.
    if grid_name or compset:
        enriched: list[dict[str, Any]] = []
        for row in out:
            sim = client.get_simulation(row["sim_id"])
            if (
                grid_name
                and grid_name.lower() not in (sim.get("gridName") or "").lower()
            ):
                continue
            if compset and compset.lower() not in (sim.get("compset") or "").lower():
                continue
            row["grid_name"] = sim.get("gridName")
            row["compset"] = sim.get("compset")
            enriched.append(row)
            if len(enriched) >= limit:
                break
        out = enriched
    else:
        out = out[:limit]

    return {
        "count": len(out),
        "simulations": out,
        "_provenance": {
            "tool": "simboard_list_simulations",
            "source_api": client.base_url,
            "filters": {
                "grid_name": grid_name,
                "machine": machine,
                "hpc_username": hpc_username,
                "compset": compset,
                "status": status,
                "limit": limit,
            },
        },
    }


def simboard_get_paths(
    sim_id: str,
    client: SimBoardClient | None = None,
) -> dict[str, Any]:
    """Resolve a SimBoard simulation id to its archive/output paths and host machine.

    Use this after ``simboard_list_simulations`` (or any time you have a
    simulation id) to get the file locations and machine identity needed
    to hand off to ``uxarray-mcp.run_analysis(use_remote=True, endpoint=...)``.

    The returned ``machine_hint`` is the SimBoard machine name; the caller
    is responsible for mapping it to a Globus Compute endpoint configured
    in uxarray-mcp (e.g. ``"perlmutter"`` → ``"nersc"`` if registered).

    Args:
        sim_id: simulation UUID (from ``simboard_list_simulations``).
        client: injected SimBoardClient for testing.

    Returns:
        Dict with keys ``execution_id``, ``case_name``, ``grid_name``,
        ``compset``, ``machine_hint``, ``machine_site``, ``artifacts``
        (mapped by kind: ``output``, ``archive``, ``run_script``, ...),
        ``links``, and ``_provenance``.
    """
    client = client or SimBoardClient()
    sim = client.get_simulation(sim_id)

    grouped = sim.get("groupedArtifacts") or {}
    artifacts_by_kind: dict[str, list[str]] = {}
    for kind, items in grouped.items():
        artifacts_by_kind[kind] = [a.get("uri") for a in (items or []) if a.get("uri")]

    machine = sim.get("machine") or {}
    return {
        "sim_id": sim_id,
        "execution_id": sim.get("executionId"),
        "case_name": sim.get("caseName"),
        "grid_name": sim.get("gridName"),
        "grid_resolution": sim.get("gridResolution"),
        "compset": sim.get("compset"),
        "machine_hint": machine.get("name"),
        "machine_site": machine.get("site"),
        "machine_scheduler": machine.get("scheduler"),
        "artifacts": artifacts_by_kind,
        "links": sim.get("links") or [],
        "_provenance": {
            "tool": "simboard_get_paths",
            "source_api": client.base_url,
            "sim_id": sim_id,
        },
    }
