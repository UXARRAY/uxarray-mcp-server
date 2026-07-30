#!/usr/bin/env python3
"""Run layered readiness and venue-consistency checks across HPC endpoints."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable


def _capture(call: Callable[[], Any]) -> dict[str, Any]:
    try:
        result = call()
        return {"ok": True, "result": result}
    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    from uxarray_mcp.tools import analyze_dataset, endpoint_status, probe_path_access
    from uxarray_mcp.tools.frontdoor import run_analysis

    report: dict[str, Any] = {"protocol": manifest.get("protocol", {}), "endpoints": {}}
    for endpoint, config in manifest["endpoints"].items():
        grid_path = config.get("grid_path")
        data_path = config.get("data_path")
        variable_name = config.get("variable_name")
        entry: dict[str, Any] = {
            "manager_worker": _capture(
                lambda endpoint=endpoint: endpoint_status(
                    endpoint=endpoint,
                    force=True,
                    probe=True,
                    probe_timeout_seconds=90,
                )
            ),
            "grid_path": None,
            "data_path": None,
            "portable_area": _capture(
                lambda endpoint=endpoint: run_analysis(
                    operation="calculate_area",
                    grid_path="healpix:8",
                    use_remote=True,
                    endpoint=endpoint,
                )
            ),
            "native_workflow": None,
        }
        if grid_path:
            entry["grid_path"] = _capture(
                lambda grid_path=grid_path, endpoint=endpoint: probe_path_access(
                    grid_path,
                    use_remote=True,
                    endpoint=endpoint,
                    inspect_netcdf=True,
                )
            )
        if data_path:
            entry["data_path"] = _capture(
                lambda data_path=data_path, endpoint=endpoint: probe_path_access(
                    data_path,
                    use_remote=True,
                    endpoint=endpoint,
                    inspect_netcdf=True,
                )
            )
        if grid_path:
            entry["native_workflow"] = _capture(
                lambda grid_path=grid_path,
                data_path=data_path,
                variable_name=variable_name,
                endpoint=endpoint: analyze_dataset(
                    grid_path=grid_path,
                    data_path=data_path,
                    variable_name=variable_name,
                    use_remote=True,
                    endpoint=endpoint,
                    include_plots=False,
                )
            )
        report["endpoints"][endpoint] = entry

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
