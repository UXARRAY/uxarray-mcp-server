"""End-to-end validation of analyze_dataset and run_scientific_agent (#28).

Exercises both the deterministic (analyze_dataset) and autonomous
(run_scientific_agent) orchestrators against:

1. Local healpix:2 mesh (no data)
2. Local synthetic UGRID grid + data file
3. Each configured HPC endpoint (Improv, UCAR) with healpix:2 + use_remote=True

Reports pass/fail per scenario and dumps a summary at the end. The script
forces the project's config.yaml so both endpoints are discoverable.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import xarray as xr

os.environ.setdefault(
    "UXARRAY_MCP_CONFIG",
    str(Path(__file__).resolve().parent.parent / "config.yaml"),
)

from uxarray_mcp.remote.config import load_config  # noqa: E402
from uxarray_mcp.tools import analyze_dataset, run_scientific_agent  # noqa: E402


def banner(title: str) -> None:
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


def make_synthetic(tmp: Path) -> tuple[str, str]:
    """One-triangle UGRID grid + matching face-centered data file."""
    grid_path = tmp / "grid.nc"
    data_path = tmp / "data.nc"

    xr.Dataset(
        {
            "Mesh2": (
                [],
                0,
                {
                    "cf_role": "mesh_topology",
                    "topology_dimension": 2,
                    "node_coordinates": "Mesh2_node_x Mesh2_node_y",
                    "face_node_connectivity": "Mesh2_face_nodes",
                },
            ),
            "Mesh2_node_x": (["nMesh2_node"], [0.0, 1.0, 0.5]),
            "Mesh2_node_y": (["nMesh2_node"], [0.0, 0.0, 1.0]),
            "Mesh2_face_nodes": (
                ["nMesh2_face", "nMaxMesh2_face_nodes"],
                [[0, 1, 2]],
                {"cf_role": "face_node_connectivity", "start_index": 0},
            ),
        }
    ).to_netcdf(grid_path)

    xr.Dataset(
        {
            "temperature": (
                ["nMesh2_face"],
                [288.15],
                {"units": "K", "long_name": "Temperature"},
            ),
            "pressure": (
                ["nMesh2_face"],
                [101325.0],
                {"units": "Pa", "long_name": "Pressure"},
            ),
        }
    ).to_netcdf(data_path)

    return str(grid_path), str(data_path)


def expect(label: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    line = f"  [{mark}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return ok


def validate_analyze_local_healpix(results: dict) -> None:
    banner("analyze_dataset — local healpix:2 (no data)")
    r = analyze_dataset("healpix:2", include_plots=True)
    ok = True
    ok &= expect(
        "mesh stage ran",
        r["mesh"] is not None,
        f"n_face={r['mesh']['n_face'] if r['mesh'] else None}",
    )
    ok &= expect("area stage ran", r["area"] is not None)
    ok &= expect(
        "plot stage ran",
        r["mesh_plot"] is not None,
        f"{r['mesh_plot']['image_size_bytes']} bytes" if r["mesh_plot"] else "",
    )
    ok &= expect("no warnings", r["warnings"] == [], str(r["warnings"]))
    ok &= expect(
        "recommends data_path",
        any("data_path" in s for s in r["recommended_next_steps"]),
    )
    results["analyze_local_healpix"] = ok


def validate_analyze_local_with_data(
    results: dict, grid_file: str, data_file: str
) -> None:
    banner("analyze_dataset — local synthetic UGRID + data")
    r = analyze_dataset(grid_file, data_file, include_plots=True)
    ok = True
    ok &= expect(
        "validation passed", r["validation"] is not None and r["validation"]["passed"]
    )
    ok &= expect(
        "variable selected",
        r["selected_variable"] in {"temperature", "pressure"},
        r["selected_variable"],
    )
    ok &= expect("zonal_mean computed", r["zonal_mean"] is not None)
    ok &= expect("variable plot rendered", r["variable_plot"] is not None)
    ok &= expect("no warnings", r["warnings"] == [], str(r["warnings"]))
    results["analyze_local_with_data"] = ok


def validate_agent_local_healpix(results: dict) -> None:
    banner("run_scientific_agent — local healpix:3")
    r = run_scientific_agent("healpix:3")
    ok = True
    ok &= expect(
        "mesh_summary present",
        r["mesh_summary"] is not None,
        f"n_face={r['mesh_summary']['n_face'] if r['mesh_summary'] else None}",
    )
    ok &= expect("area_results present", r["area_results"] is not None)
    ok &= expect(
        "verification.passed",
        r["verification"]["passed"],
        str(r["verification"]["warnings"]),
    )
    stages = {step.get("stage") for step in r["reasoning_trace"]}
    ok &= expect(
        "all 4 stages in trace",
        stages >= {"analyze", "plan", "execute", "verify"},
        sorted(stages),
    )
    results["agent_local_healpix"] = ok


def validate_agent_local_with_data(
    results: dict, grid_file: str, data_file: str
) -> None:
    banner("run_scientific_agent — local synthetic UGRID + data")
    r = run_scientific_agent(grid_file, data_file)
    ok = True
    ok &= expect("variable_results present", r["variable_results"] is not None)
    ok &= expect("validation_summary present", r["validation_summary"] is not None)
    ok &= expect(
        "zonal_mean attempted",
        r["zonal_mean_results"] is not None,
        "(only if a face-centered variable was found)",
    )
    ok &= expect(
        "verification.passed",
        r["verification"]["passed"],
        str(r["verification"]["warnings"]),
    )
    results["agent_local_with_data"] = ok


def validate_remote_endpoint(results: dict, endpoint_name: str) -> None:
    banner(f"analyze_dataset — REMOTE healpix:2 on '{endpoint_name}'")
    try:
        r = analyze_dataset(
            "healpix:2",
            use_remote=True,
            endpoint=endpoint_name,
            include_plots=True,
        )
    except Exception as exc:
        results[f"analyze_remote_{endpoint_name}"] = False
        print(f"  [FAIL] dispatcher raised: {type(exc).__name__}: {exc}")
        return

    ok = True
    top_venue = r["_provenance"]["execution_venue"]
    ok &= expect("top-level venue == 'hpc'", top_venue == "hpc", top_venue)
    inner_venue = (r["mesh"] or {}).get("_provenance", {}).get("execution_venue", "")
    ok &= expect(
        "inner mesh stage ran on endpoint",
        inner_venue.startswith("hpc:"),
        inner_venue or "(no inner provenance)",
    )
    ok &= expect("mesh stage ran", r["mesh"] is not None)
    ok &= expect("area stage ran", r["area"] is not None)
    ok &= expect("plot stage ran", r["mesh_plot"] is not None)
    if r["warnings"]:
        for w in r["warnings"]:
            print(f"     warning: {w}")
    results[f"analyze_remote_{endpoint_name}"] = ok


def main() -> int:
    cfg = load_config()
    print(f"Loaded {len(cfg.endpoints)} endpoint(s): {sorted(cfg.endpoints)}")

    tmp = Path(tempfile.mkdtemp(prefix="uxmcp-validate-"))
    grid_file, data_file = make_synthetic(tmp)

    results: dict[str, bool] = {}

    # Local scenarios
    validate_analyze_local_healpix(results)
    validate_analyze_local_with_data(results, grid_file, data_file)
    validate_agent_local_healpix(results)
    validate_agent_local_with_data(results, grid_file, data_file)

    # Remote scenarios — one per configured endpoint
    for endpoint_name in sorted(cfg.endpoints):
        validate_remote_endpoint(results, endpoint_name)

    # Summary
    banner("SUMMARY")
    width = max((len(k) for k in results), default=0)
    n_pass = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        print(f"  {name.ljust(width)}  {'PASS' if ok else 'FAIL'}")
    print(f"\n{n_pass}/{len(results)} scenarios passed.")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
