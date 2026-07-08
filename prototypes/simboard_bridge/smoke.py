"""End-to-end smoke test for the SimBoard bridge prototype.

Runs against the live dev deployment. Walks the conversational chain:

    list_simulations()           → pick the newest Perlmutter completed run
    get_paths(sim_id)            → resolve archive/output paths + machine
    (would hand off to uxarray-mcp.run_analysis here)

Prints a compact transcript suitable for pasting into Slack / a slide.
"""

from __future__ import annotations

import json
import sys

from prototypes.simboard_bridge.client import SimBoardClient
from prototypes.simboard_bridge.tools import (
    simboard_get_paths,
    simboard_list_simulations,
)


def main() -> int:
    client = SimBoardClient()
    print(f"# SimBoard bridge smoke — {client.base_url}\n")

    # ---- 1. Health ----
    print("[1] health check")
    h = client.health()
    print(f"    -> {h}\n")

    # ---- 2. List Perlmutter, completed ----
    print(
        "[2] simboard_list_simulations(machine='perlmutter', status='completed', limit=3)"
    )
    lst = simboard_list_simulations(
        machine="perlmutter", status="completed", limit=3, client=client
    )
    print(f"    -> {lst['count']} simulations")
    for s in lst["simulations"]:
        print(
            f"       {s['execution_id']}  user={s['hpc_usernames']}  "
            f"case={s['case_name'][:60]}"
        )

    if not lst["simulations"]:
        print("\nFAIL — no simulations returned. Aborting.")
        return 1
    pick = lst["simulations"][0]
    print(f"\n    Picking the first one: sim_id={pick['sim_id']}\n")

    # ---- 3. Get paths ----
    print(f"[3] simboard_get_paths(sim_id='{pick['sim_id']}')")
    paths = simboard_get_paths(pick["sim_id"], client=client)
    print(
        "    -> machine_hint={machine_hint!r} site={machine_site!r} "
        "grid={grid_name!r} compset={compset!r}".format(**paths)
    )
    print("    -> artifacts by kind:")
    for kind, uris in (paths.get("artifacts") or {}).items():
        print(f"         [{kind}] {len(uris)} uri(s)")
        for u in uris[:2]:
            print(f"            {u}")

    # ---- 4. What we'd hand off to uxarray-mcp ----
    print("\n[4] Hand-off plan to uxarray-mcp.run_analysis:")
    output_paths = (paths.get("artifacts") or {}).get("output") or []
    if output_paths:
        print("    Would call (pseudo):")
        print(
            f"      run_analysis(operation='inspect_mesh',\n"
            f"                   grid_path='<auto-discovered under {output_paths[0]}>',\n"
            f"                   use_remote=True, endpoint='nersc')"
        )
        print(
            "    Path-prefix routing on the uxarray-mcp side handles the\n"
            "    /pscratch/sd/... → NERSC endpoint mapping; no new code needed."
        )
    else:
        print("    (no output artifact for this sim — would need a different one)")

    print("\nPASS")
    print("\nFull get_paths response (for reference):")
    print(json.dumps(paths, indent=2, default=str)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
