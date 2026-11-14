"""Print what the server costs a client: schema bytes per tool, result bytes per op.

Every reply is re-sent on each later turn, so size is paid repeatedly.
``tests/test_server.py`` ratchets the schema total; this prints the breakdown.

    uv run python scripts/measure_payload.py
"""

from __future__ import annotations

import json
import os
import tempfile
import warnings

from toolregistry_server.route_table import RouteTable

from uxarray_mcp.server.app import make_registry


def main() -> None:
    warnings.simplefilter("ignore")
    print("tool schemas (bytes on the wire)")
    total = 0
    for route in RouteTable(make_registry()).list_routes():
        size = len(
            json.dumps(
                {
                    "name": route.tool_name,
                    "description": route.description,
                    "parameters": route.parameters_schema,
                }
            )
        )
        total += size
        print(f"  {route.tool_name:16s} {size:6d}")
    print(f"  {'total':16s} {total:6d}\n")

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["UXARRAY_MCP_STATE_DIR"] = tmp
        from uxarray_mcp.server import tools

        calls = {
            "inspect_dataset": lambda: tools.inspect_dataset(grid_path="healpix:3"),
            "compute area": lambda: tools.compute(
                statistic="area", grid_path="healpix:3", sphere_radius=6371000.0
            ),
            "compute area (refused)": lambda: tools.compute(
                statistic="area", grid_path="healpix:3"
            ),
            "subset bbox": lambda: tools.subset(
                shape="bbox",
                grid_path="healpix:3",
                lon_bounds=[-30, 30],
                lat_bounds=[-30, 30],
            ),
            "plot mesh (metadata)": lambda: json.loads(
                tools.plot(kind="mesh", grid_path="healpix:3")[1]["text"]
            ),
        }
        print("results (bytes, and share that is _provenance)")
        for name, fn in calls.items():
            result = fn()
            size = len(json.dumps(result, default=str))
            prov = len(json.dumps(result.get("_provenance", {}), default=str))
            print(f"  {name:24s} {size:6d}  provenance {prov / size:4.0%}")


if __name__ == "__main__":
    main()
