#!/usr/bin/env python3
"""Validate gradient/curl/divergence against analytic vector-calculus identities.

Runs four identities through the same `run_analysis` tool path used by the
MCP server (not raw UXarray calls), so the numbers reported here are exactly
what an agent would see:

  1. grad(const)            == 0
  2. curl(const, const)     == 0
  3. div(const, const)      == 0
  4. curl(grad(phi))        == 0   (Gaussian phi; the stringent, double-
                                    differentiation identity)

Identity 4 requires `scale_by_radius=True` to hold near machine precision —
`gradient()`/`curl()` are independently-computed, per-face first-order
finite-volume operators, so on the unit sphere (`scale_by_radius=False`,
the MCP server's own hardcoded default for other calls) they do not
discretely cancel and the residual is O(1)-O(1e2), not O(1e-10). This
script always passes `scale_by_radius=True` explicitly for identity 4 to
get the correct, reproducible comparison.

Uses a self-contained synthetic structured grid (no external mesh file
needed) so this script runs anywhere with no data dependencies.

Usage
-----
    uv run python scripts/analytic_validation.py
    uv run python scripts/analytic_validation.py --resolution-deg 2.0
    uv run python scripts/analytic_validation.py --use-remote --endpoint chrysalis
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any


def _build_fixture(resolution_deg: float, tmp_dir: Path) -> tuple[str, str, str]:
    """Build a synthetic structured grid + a data file with const/Gaussian fields.

    Returns (grid_path, data_path, grad_of_phi_data_path). A structured
    lon/lat grid is used (rather than HEALPix) because it can carry a
    `sphere_radius` grid attribute that survives a real file round-trip via
    `ux.open_grid`/`ux.open_dataset` — required for identity 4
    (curl-of-gradient) to hold near machine precision, since
    `scale_by_radius=True` silently falls back to unit-sphere behavior on
    any grid lacking `sphere_radius` (e.g. HEALPix, which does not define
    one). The third path is filled in by the caller after computing the
    gradient of phi (needed to chain gradient -> curl for identity 4).
    """
    import numpy as np
    import uxarray as ux
    import xarray as xr

    n_lon = max(int(360 / resolution_deg), 8)
    n_lat = max(int(160 / resolution_deg), 6)
    lon = np.linspace(-180, 180, n_lon)
    lat = np.linspace(-80, 80, n_lat)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid._ds.attrs["sphere_radius"] = 6.371e6

    grid_path = str(tmp_dir / "grid.nc")
    grid.to_xarray().to_netcdf(grid_path)
    grid = ux.open_grid(grid_path)  # reload so downstream calls see sphere_radius

    lon = np.asarray(grid.face_lon.values)
    lat = np.asarray(grid.face_lat.values)
    lon0, lat0, sigma = 30.0, 20.0, 25.0
    dlon = (lon - lon0 + 180) % 360 - 180
    phi = np.exp(-((dlon**2 + (lat - lat0) ** 2) / (2 * sigma**2)))

    ds = xr.Dataset(
        {
            "phi": (["n_face"], phi, {"units": "K"}),
            "const1": (["n_face"], np.full(grid.n_face, 5.0), {"units": "m s-1"}),
            "const2": (["n_face"], np.full(grid.n_face, 7.0), {"units": "m s-1"}),
        }
    )
    data_path = tmp_dir / "data.nc"
    ds.to_netcdf(data_path)

    return grid_path, str(data_path), str(tmp_dir / "grad_of_phi.nc")


def _write_gradient_components(
    grid_path: str,
    data_path: str,
    out_path: str,
    use_remote: bool,
    endpoint: str | None,
) -> dict:
    """Compute grad(phi) via run_analysis, write components for the curl step."""
    import xarray as xr

    from uxarray_mcp.tools import run_analysis

    result = run_analysis(
        operation="gradient",
        grid_path=grid_path,
        data_path=data_path,
        variable_name="phi",
        scale_by_radius=True,
        use_remote=use_remote,
        endpoint=endpoint,
    )
    # run_analysis only returns summary stats, not the raw per-face arrays,
    # so recompute the same call directly against UXarray to get the field
    # (identical code path: UxDataArray.gradient, same scale_by_radius).
    from uxarray_mcp.domain.mesh import load_dataset

    uxds = load_dataset(grid_path, data_path)
    grad = uxds["phi"].gradient(scale_by_radius=True)
    comp_names = list(grad.data_vars)
    xr.Dataset(
        {
            "grad_u": (["n_face"], grad[comp_names[0]].values, {"units": "K m-1"}),
            "grad_v": (["n_face"], grad[comp_names[1]].values, {"units": "K m-1"}),
        }
    ).to_netcdf(out_path)
    return result


def run_identity(
    label: str,
    operation: str,
    grid_path: str,
    data_path: str,
    kwargs: dict[str, Any],
    use_remote: bool,
    endpoint: str | None,
) -> dict:
    from uxarray_mcp.tools import run_analysis

    t0 = time.perf_counter()
    result = run_analysis(
        operation=operation,
        grid_path=grid_path,
        data_path=data_path,
        use_remote=use_remote,
        endpoint=endpoint,
        **kwargs,
    )
    elapsed = time.perf_counter() - t0

    stats = result.get("stats") or result.get("component_stats")
    if operation == "gradient":
        max_abs = max(
            abs(v) for comp in stats.values() for v in (comp["min"], comp["max"])
        )
    else:
        max_abs = max(abs(stats["min"]), abs(stats["max"]))

    return {
        "label": label,
        "operation": operation,
        "elapsed_seconds": round(elapsed, 4),
        "max_abs_residual": max_abs,
        "execution_venue": result["_provenance"]["execution_venue"],
        "warnings": result["_provenance"]["warnings"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resolution-deg",
        type=float,
        default=4.0,
        help="Synthetic grid spacing in degrees",
    )
    parser.add_argument("--use-remote", action="store_true")
    parser.add_argument("--endpoint", default=None)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="analytic_validation_") as td:
        tmp_dir = Path(td)
        grid_path, data_path, grad_of_phi_path = _build_fixture(
            args.resolution_deg, tmp_dir
        )

        results = []
        results.append(
            run_identity(
                "grad(const) == 0",
                "gradient",
                grid_path,
                data_path,
                {"variable_name": "const1", "scale_by_radius": True},
                args.use_remote,
                args.endpoint,
            )
        )
        results.append(
            run_identity(
                "curl(const, const) == 0",
                "curl",
                grid_path,
                data_path,
                {
                    "u_variable": "const1",
                    "v_variable": "const2",
                    "scale_by_radius": True,
                },
                args.use_remote,
                args.endpoint,
            )
        )
        results.append(
            run_identity(
                "div(const, const) == 0",
                "divergence",
                grid_path,
                data_path,
                {"u_variable": "const1", "v_variable": "const2"},
                args.use_remote,
                args.endpoint,
            )
        )

        # Identity 4: curl(grad(phi)) == 0 — chain gradient output into curl.
        _write_gradient_components(
            grid_path, data_path, grad_of_phi_path, args.use_remote, args.endpoint
        )
        results.append(
            run_identity(
                "curl(grad(phi)) == 0 (Gaussian field)",
                "curl",
                grid_path,
                grad_of_phi_path,
                {
                    "u_variable": "grad_u",
                    "v_variable": "grad_v",
                    "scale_by_radius": True,
                },
                args.use_remote,
                args.endpoint,
            )
        )

        print(f"{'identity':40s} {'max|residual|':>16s} {'venue':>14s}")
        print("-" * 74)
        for r in results:
            print(
                f"{r['label']:40s} {r['max_abs_residual']:16.3e} {r['execution_venue']:>14s}"
            )
            for w in r["warnings"]:
                print(f"    warning: {w}")

        out_dir = Path(__file__).resolve().parent.parent / "evals" / "results"
        out_dir.mkdir(exist_ok=True, parents=True)
        out_path = out_dir / f"analytic_validation_{args.resolution_deg}deg.json"
        out_path.write_text(
            json.dumps(
                {"resolution_deg": args.resolution_deg, "results": results}, indent=2
            )
        )
        print(f"\nWrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
