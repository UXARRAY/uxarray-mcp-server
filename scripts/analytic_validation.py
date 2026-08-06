#!/usr/bin/env python3
"""Validate UXarray vector calculus through the MCP front-door path.

This is a bounded operator-regression evaluation, not a proof of convergence
on arbitrary unstructured meshes.  It runs a manufactured scalar field over a
nested structured spherical-grid family and records L-infinity and
area-weighted L2 residuals for the identities exposed by the MCP server.

The chained curl(gradient(phi)) check is intentionally local-only.  Its
intermediate gradient file is constructed on the submitter filesystem; passing
``--use-remote`` would therefore be a false remote claim.  Facility execution
is exercised by :mod:`scripts.facility_matrix`, which creates all fixtures on
the endpoint-visible filesystem before dispatch.

Usage
-----
    uv run python scripts/analytic_validation.py
    uv run python scripts/analytic_validation.py --resolutions 8 4 2 1
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any


def _build_fixture(resolution_deg: float, tmp_dir: Path) -> tuple[str, str, str]:
    """Build a structured spherical grid and constant/Gaussian data files."""
    import numpy as np
    import uxarray as ux
    import xarray as xr

    n_lon = max(int(360 / resolution_deg), 8)
    n_lat = max(int(160 / resolution_deg), 6)
    lon = np.linspace(-180, 180, n_lon)
    lat = np.linspace(-80, 80, n_lat)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid._ds.attrs["sphere_radius"] = 6.371e6

    grid_path = str(tmp_dir / f"grid_{resolution_deg:g}deg.nc")
    grid.to_xarray().to_netcdf(grid_path)
    grid = ux.open_grid(grid_path)

    face_lon = np.asarray(grid.face_lon.values)
    face_lat = np.asarray(grid.face_lat.values)
    lon0, lat0, sigma = 30.0, 20.0, 25.0
    dlon = (face_lon - lon0 + 180) % 360 - 180
    phi = np.exp(-((dlon**2 + (face_lat - lat0) ** 2) / (2 * sigma**2)))
    ds = xr.Dataset(
        {
            "phi": ("n_face", phi, {"units": "K"}),
            "const1": ("n_face", np.full(grid.n_face, 5.0), {"units": "m s-1"}),
            "const2": ("n_face", np.full(grid.n_face, 7.0), {"units": "m s-1"}),
        }
    )
    data_path = tmp_dir / f"data_{resolution_deg:g}deg.nc"
    ds.to_netcdf(data_path)
    return grid_path, str(data_path), str(tmp_dir / f"grad_{resolution_deg:g}deg.nc")


def _norms(values: Any, weights: Any | None = None) -> dict[str, float]:
    import numpy as np

    values = np.asarray(values, dtype=float).ravel()
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {"linf": math.nan, "l2_area_weighted": math.nan}
    output = {"linf": float(np.max(np.abs(finite)))}
    if weights is None:
        output["l2_area_weighted"] = float(np.sqrt(np.mean(finite**2)))
        return output
    weights = np.asarray(weights, dtype=float).ravel()
    mask = np.isfinite(values) & np.isfinite(weights) & (weights >= 0)
    output["l2_area_weighted"] = float(
        np.sqrt(np.sum(weights[mask] * values[mask] ** 2) / np.sum(weights[mask]))
    )
    return output


def _run_analysis(
    operation: str, grid_path: str, data_path: str, **kwargs: Any
) -> dict:
    from uxarray_mcp.tools import run_analysis

    t0 = time.perf_counter()
    result = run_analysis(
        operation=operation,
        grid_path=grid_path,
        data_path=data_path,
        **kwargs,
    )
    return {"result": result, "elapsed_seconds": time.perf_counter() - t0}


def _gradient_file(grid_path: str, data_path: str, output_path: str) -> None:
    """Persist gradient components for the chained identity locally."""
    import xarray as xr

    from uxarray_mcp.domain.mesh import load_dataset

    uxds = load_dataset(grid_path, data_path)
    grad = uxds["phi"].gradient(scale_by_radius=True)
    names = list(grad.data_vars)
    xr.Dataset(
        {
            "grad_u": ("n_face", grad[names[0]].values, {"units": "K m-1"}),
            "grad_v": ("n_face", grad[names[1]].values, {"units": "K m-1"}),
        }
    ).to_netcdf(output_path)


def _curl_values(grid_path: str, data_path: str) -> tuple[Any, Any]:
    """Read the same curl implementation for norm computation after MCP call."""
    from uxarray_mcp.domain.mesh import load_dataset

    uxds = load_dataset(grid_path, data_path)
    curl = uxds["grad_u"].curl(uxds["grad_v"], scale_by_radius=True)
    return curl.values, uxds.uxgrid.face_areas.values


def run_resolution(resolution_deg: float, work_dir: Path) -> dict[str, Any]:
    grid_path, data_path, gradient_path = _build_fixture(resolution_deg, work_dir)
    import uxarray as ux

    grid = ux.open_grid(grid_path)
    cases: list[dict[str, Any]] = []
    for label, operation, kwargs in (
        (
            "grad(const)=0",
            "gradient",
            {"variable_name": "const1", "scale_by_radius": True},
        ),
        (
            "curl(const,const)=0",
            "curl",
            {"u_variable": "const1", "v_variable": "const2", "scale_by_radius": True},
        ),
        (
            "div(const,const)=0",
            "divergence",
            {"u_variable": "const1", "v_variable": "const2"},
        ),
    ):
        run = _run_analysis(operation, grid_path, data_path, **kwargs)
        stats = run["result"].get("stats") or run["result"].get("component_stats")
        if operation == "gradient":
            residual = max(
                abs(v)
                for component in stats.values()
                for v in (component["min"], component["max"])
            )
        else:
            residual = max(abs(stats["min"]), abs(stats["max"]))
        cases.append(
            {
                "identity": label,
                "norms": {"linf": float(residual), "l2_area_weighted": float(residual)},
                "elapsed_seconds": run["elapsed_seconds"],
                "provenance": run["result"]["_provenance"],
            }
        )

    # The front-door curl call is exercised first; direct re-read below only
    # obtains every face value needed for an L2 metric, which summaries omit.
    _gradient_file(grid_path, data_path, gradient_path)
    run = _run_analysis(
        "curl",
        grid_path,
        gradient_path,
        u_variable="grad_u",
        v_variable="grad_v",
        scale_by_radius=True,
    )
    values, weights = _curl_values(grid_path, gradient_path)
    cases.append(
        {
            "identity": "curl(grad(phi))=0 (Gaussian)",
            "norms": _norms(values, weights),
            "elapsed_seconds": run["elapsed_seconds"],
            "provenance": run["result"]["_provenance"],
        }
    )
    return {
        "resolution_deg": resolution_deg,
        "n_face": int(grid.n_face),
        "cases": cases,
    }


def _observed_rates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report ratios; do not call them convergence rates without a study design."""
    target = [r for r in rows if r["identity"].startswith("curl(grad")]
    target.sort(key=lambda r: r["resolution_deg"], reverse=True)
    rates = []
    for coarse, fine in zip(target, target[1:]):
        coarse_error = coarse["norms"]["linf"]
        fine_error = fine["norms"]["linf"]
        rates.append(
            {
                "coarse_resolution_deg": coarse["resolution_deg"],
                "fine_resolution_deg": fine["resolution_deg"],
                "linf_ratio": coarse_error / fine_error if fine_error else None,
            }
        )
    return rates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolutions", type=float, nargs="+", default=[8.0, 4.0, 2.0, 1.0]
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="analytic_validation_") as td:
        work_dir = Path(td)
        for resolution in args.resolutions:
            report = run_resolution(resolution, work_dir)
            for case in report.pop("cases"):
                rows.append({**report, **case})

    payload = {
        "scope": "local structured-grid operator regression; not a general unstructured convergence proof",
        "resolutions_deg": args.resolutions,
        "rows": rows,
        "curl_grad_linf_ratios": _observed_rates(rows),
    }
    output = args.output or (
        Path(__file__).resolve().parent.parent
        / "evals"
        / "results"
        / "analytic_refinement.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2))
    print(
        f"{'resolution':>10} {'faces':>8} {'identity':38s} {'Linf':>12} {'L2(area)':>12}"
    )
    print("-" * 92)
    for row in rows:
        print(
            f"{row['resolution_deg']:10g} {row['n_face']:8d} {row['identity']:38s} {row['norms']['linf']:12.3e} {row['norms']['l2_area_weighted']:12.3e}"
        )
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
