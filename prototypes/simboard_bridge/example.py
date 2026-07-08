"""Offline, runnable example: SimBoard discovery → uxarray-mcp analysis.

This showcases the full "find a run, then analyze it" workflow that the
SimBoard bridge enables, using the SimBoard REST API contract documented in
E3SM-Project/simboard#246 (the ``-api`` subdomain + ``/api/v1`` prefix).

Unlike ``smoke.py`` (which hits the live dev deployment and would hand off to
an HPC endpoint), this example is **fully self-contained**:

* SimBoard responses are mocked with a tiny in-process fake client, so no
  network access is required and the documented JSON shapes are visible inline.
* The final analysis runs **locally** on a synthetic HEALPix grid
  (``healpix:2``), so no data files and no Globus Compute endpoint are needed.

The point is to demonstrate the conversational chain and the exact handoff
into ``uxarray-mcp.run_analysis`` without any external dependencies.

Run it::

    uv run python -m prototypes.simboard_bridge.example
"""

from __future__ import annotations

import json
from typing import Any

from prototypes.simboard_bridge.tools import (
    simboard_get_paths,
    simboard_list_simulations,
)

# ---------------------------------------------------------------------------
# A minimal fake SimBoard client.
#
# It returns the same JSON shapes the real REST API returns (see the OpenAPI
# schema at https://simboard-dev-api.e3sm.org/openapi.json). Only the two
# endpoints the bridge uses are implemented: ``/cases`` and
# ``/simulations/{id}``.
# ---------------------------------------------------------------------------

_FAKE_CASES: list[dict[str, Any]] = [
    {
        "name": "v3.LR.piControl",
        "machineNames": ["chrysalis"],
        "hpcUsernames": ["golaz"],
        "simulations": [
            {
                "id": "bae7fd01-0000-4000-8000-000000000001",
                "executionId": "10011002.260610-072848",
                "status": "completed",
                "simulationStartDate": "0001-01-01",
                "simulationEndDate": "0050-12-31",
            }
        ],
    },
    {
        "name": "v3.HR.historical",
        "machineNames": ["perlmutter"],
        "hpcUsernames": ["whannah"],
        "simulations": [
            {
                "id": "bae7fd01-0000-4000-8000-000000000002",
                "executionId": "54258454.260101-000000",
                "status": "running",
                "simulationStartDate": "1850-01-01",
                "simulationEndDate": "2014-12-31",
            }
        ],
    },
]

_FAKE_SIM_DETAILS: dict[str, dict[str, Any]] = {
    "bae7fd01-0000-4000-8000-000000000001": {
        "executionId": "10011002.260610-072848",
        "caseName": "v3.LR.piControl",
        "gridName": "ne30pg2_r05_IcoswISC30E3r5",
        "gridResolution": "ne30",
        "compset": "WCYCL1850",
        "machine": {
            "name": "chrysalis",
            "site": "ANL-LCRC",
            "scheduler": "slurm",
        },
        "groupedArtifacts": {
            "output": [
                {"uri": "/lcrc/group/e3sm/ac.golaz/v3.LR.piControl/run"},
            ],
            "archive": [
                {"uri": "/lcrc/group/e3sm/ac.golaz/v3.LR.piControl/archive/atm"},
            ],
            "run_script": [
                {"uri": "/home/ac.golaz/E3SM/v3.LR.piControl.run"},
            ],
        },
        "links": [
            {"label": "diagnostics", "url": "https://web.lcrc.anl.gov/.../e3sm_diags"},
        ],
    }
}


class FakeSimBoardClient:
    """In-process stand-in for ``SimBoardClient`` — returns canned JSON."""

    base_url = "https://simboard-dev-api.e3sm.org/api/v1 (mocked)"

    def list_cases(self) -> list[dict[str, Any]]:
        return _FAKE_CASES

    def get_simulation(self, sim_id: str) -> dict[str, Any]:
        return _FAKE_SIM_DETAILS[sim_id]


# ---------------------------------------------------------------------------
# The workflow.
# ---------------------------------------------------------------------------


def main() -> int:
    client = FakeSimBoardClient()

    print("=" * 70)
    print("SimBoard -> uxarray-mcp  (offline example)")
    print("=" * 70)
    print(f"SimBoard REST API: {client.base_url}\n")
    print(
        'User: "Find the latest completed Chrysalis run and check its\n'
        '       mesh + face areas."\n'
    )

    # ---- Step 1: discover a simulation -----------------------------------
    print("[1] simboard_list_simulations(machine='chrysalis', status='completed')")
    listing = simboard_list_simulations(
        machine="chrysalis",
        status="completed",
        limit=5,
        client=client,  # type: ignore[arg-type]
    )
    print(f"    -> {listing['count']} match(es)")
    for sim in listing["simulations"]:
        print(
            f"       {sim['execution_id']}  "
            f"case={sim['case_name']}  status={sim['status']}"
        )

    pick = listing["simulations"][0]
    print(f"\n    Agent picks: sim_id={pick['sim_id']}\n")

    # ---- Step 2: resolve paths + machine ---------------------------------
    print(f"[2] simboard_get_paths(sim_id='{pick['sim_id']}')")
    paths = simboard_get_paths(pick["sim_id"], client=client)  # type: ignore[arg-type]
    print(
        "    -> grid={grid_name!r}  compset={compset!r}\n"
        "       machine={machine_hint!r}  site={machine_site!r}  "
        "scheduler={machine_scheduler!r}".format(**paths)
    )
    for kind, uris in (paths.get("artifacts") or {}).items():
        for uri in uris:
            print(f"       [{kind}] {uri}")

    machine = paths["machine_hint"]
    print(
        f"\n    In production the agent maps machine {machine!r} -> the "
        "Globus Compute\n    endpoint registered as 'chrysalis' and calls "
        "run_analysis(use_remote=True).\n    Path-prefix routing handles "
        "/lcrc/group/... automatically.\n"
    )

    # ---- Step 3: run the analysis ----------------------------------------
    # For this offline demo we analyze a synthetic HEALPix grid locally
    # instead of the (unreachable) Chrysalis path, so the example runs anywhere.
    from uxarray_mcp.tools.frontdoor import run_analysis

    demo_grid = "healpix:2"
    print(f"[3] run_analysis(operation='inspect_mesh', grid_path={demo_grid!r})")
    print("    (offline demo grid; production would use the resolved Chrysalis path)")
    mesh = run_analysis(operation="inspect_mesh", grid_path=demo_grid)
    print(
        f"    -> format={mesh['format']}  n_face={mesh['n_face']}  "
        f"n_node={mesh['n_node']}"
    )

    print(f"\n[4] run_analysis(operation='calculate_area', grid_path={demo_grid!r})")
    area = run_analysis(operation="calculate_area", grid_path=demo_grid)
    print(
        f"    -> total_area={area['total_area']:.4e} {area['area_units']}  "
        f"mean_area={area['mean_area']:.4e}"
    )

    print("\n" + "=" * 70)
    print("Done. Two providers (SimBoard + uxarray-mcp), one conversation.")
    print("=" * 70)
    print("\nProvenance from the final area result:")
    print(json.dumps(area.get("_provenance", {}), indent=2, default=str)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
