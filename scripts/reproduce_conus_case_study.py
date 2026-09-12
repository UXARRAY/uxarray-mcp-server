#!/usr/bin/env python3
"""Reproduce all results in case-studies/conus-precipitation-gdex/README.md.

Runs remote HPC operations against Casper at NSF NCAR via Globus Compute
endpoint `ucar-uxarray-yac`.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

GRID_PATH = (
    "/glade/p/cesmdata/cseg/inputdata/share/scripgrids/ne120np4_pentagons_100310.nc"
)
DATA_BASE_DIR = (
    "/gdex/data/d651007/b.e13.BHISTC5.ne120_t12.cesm-ihesp-hires1.0.30-1920-2005.002"
    "/atm/proc/tseries/hour_6/"
)
DATA_PREFIX = (
    "b.e13.BHISTC5.ne120_t12.cesm-ihesp-hires1.0.30-1920-2005.002.cam.h2.PRECT."
)
ENDPOINT = "ucar-uxarray-yac"

LON_BOUNDS = [-125.0, -67.0]
LAT_BOUNDS = [24.0, 50.0]
SCALE_FACTOR = 86400000.0  # m/s -> mm/day
UNITS_LABEL = "mm/day"
REGION_NAME = "CONUS"
CMAP = "YlGnBu"
WIDTH = 1000
HEIGHT = 560


def get_data_paths(start_year: int = 1979, end_year: int = 1988) -> list[str]:
    paths = []
    for y in range(start_year, end_year + 1):
        filename = f"{DATA_PREFIX}{y}010100-{y + 1}010100.nc"
        paths.append(f"{DATA_BASE_DIR}{filename}")
    return paths


def run_act1() -> Dict[str, Any]:
    """Act I: Remote capabilities query."""
    print("=" * 70)
    print("ACT I: Remote Capabilities Query")
    print(f"Grid: {GRID_PATH}")
    print(f"Endpoint: {ENDPOINT}")
    print("=" * 70)

    from uxarray_mcp.tools.capabilities import get_capabilities

    t0 = time.time()
    res = get_capabilities(
        grid_path=GRID_PATH,
        use_remote=True,
        endpoint=ENDPOINT,
    )
    elapsed = time.time() - t0

    grid_summary = res.get("grid_summary") or {}
    prov = res.get("_provenance") or {}

    print(f"ELAPSED           {elapsed:.1f} s")
    print(f"format            {grid_summary.get('format')}")
    print(f"n_face            {grid_summary.get('n_face')}")
    print(f"n_node            {grid_summary.get('n_node')}")
    print(f"n_edge            {grid_summary.get('n_edge')}")
    print(f"execution_venue   {prov.get('execution_venue')}")
    print(f"applicable_tools  {len(res.get('mcp_server_tools') or [])} tools")
    print("-" * 70)

    assert grid_summary.get("n_face") == 777602, (
        f"Expected 777602 faces, got {grid_summary.get('n_face')}"
    )
    assert grid_summary.get("n_node") == 780456, (
        f"Expected 780456 nodes, got {grid_summary.get('n_node')}"
    )
    assert grid_summary.get("n_edge") == 2329471, (
        f"Expected 2329471 edges, got {grid_summary.get('n_edge')}"
    )
    print("✓ Act I checks passed successfully!")
    return res


def extract_plot_result(mcp_contents: list[Any]) -> tuple[Dict[str, Any], bytes | None]:
    meta: Dict[str, Any] = {}
    png_bytes: bytes | None = None

    for block in mcp_contents:
        if isinstance(block, dict):
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "{}")
                try:
                    meta = json.loads(text)
                except Exception:
                    meta = {"raw_text": text}
            elif btype == "image":
                src = block.get("source") or {}
                data = src.get("data")
                if data:
                    png_bytes = base64.b64decode(data)
        else:
            btype = getattr(block, "type", None)
            if btype == "text":
                text = getattr(block, "text", "{}")
                try:
                    meta = json.loads(text)
                except Exception:
                    meta = {"raw_text": text}
            elif btype == "image":
                src = getattr(block, "source", None)
                if isinstance(src, dict) and "data" in src:
                    png_bytes = base64.b64decode(src["data"])
                elif src is not None and hasattr(src, "data"):
                    png_bytes = base64.b64decode(src.data)
                elif hasattr(block, "data"):
                    png_bytes = base64.b64decode(block.data)

    if not png_bytes and "png_b64" in meta:
        png_bytes = base64.b64decode(meta["png_b64"])

    return meta, png_bytes


def run_act2(output_dir: Path) -> Dict[str, Any]:
    """Act II: 1-Year Remote Precipitation Mean (1979)."""
    print("\n" + "=" * 70)
    print("ACT II: 1-Year Remote Precipitation Mean (1979)")
    paths = get_data_paths(1979, 1979)
    print(f"Grid: {GRID_PATH}")
    print(f"Data: {paths[0]}")
    print(f"Endpoint: {ENDPOINT}")
    print("=" * 70)

    from uxarray_mcp.tools.frontdoor import plot_dataset

    t0 = time.time()
    res = plot_dataset(
        plot_type="temporal_mean",
        grid_path=GRID_PATH,
        data_paths=paths,
        variable_name="PRECT",
        lon_bounds=LON_BOUNDS,
        lat_bounds=LAT_BOUNDS,
        scale_factor=SCALE_FACTOR,
        units_label=UNITS_LABEL,
        region_name=REGION_NAME,
        cmap=CMAP,
        width=WIDTH,
        height=HEIGHT,
        coastlines=True,
        use_remote=True,
        endpoint=ENDPOINT,
    )
    elapsed = time.time() - t0

    meta, png_bytes = extract_plot_result(res)
    prov = meta.get("_provenance") or {}
    worker = (meta.get("_worker_runtime") or {}).get("hostname") or prov.get(
        "remote_hostname"
    )
    vstats = meta.get("value_stats") or {}

    print(f"ELAPSED           {elapsed:.1f} s")
    print(f"n_files           {meta.get('n_files')}")
    print(f"n_time_steps      {meta.get('n_time_steps')}")
    print(f"time span         {meta.get('time_start')}  →  {meta.get('time_end')}")
    n_sub = meta.get("n_face_subset")
    n_tot = meta.get("n_face_total")
    frac = (n_sub / n_tot * 100.0) if n_sub and n_tot else 0.0
    print(f"n_face_subset     {n_sub}  of {n_tot}   ({frac:.2f}% of the mesh)")
    print(
        f"value_stats       min {vstats.get('min'):.3f}   "
        f"mean {vstats.get('mean'):.3f}   "
        f"max {vstats.get('max'):.3f} {UNITS_LABEL}   "
        f"n_nonfinite {vstats.get('n_nonfinite')}"
    )
    print(f"execution_venue   {meta.get('execution_venue')}")
    print(f"worker            {worker}")
    print(f"provenance.tool   {prov.get('tool')}")
    print(f"provenance.op_id  {prov.get('operation_id')}")

    if png_bytes:
        out_png = output_dir / "conus-precip-1yr-1979.png"
        out_png.write_bytes(png_bytes)
        print(f"Saved plot: {out_png} ({len(png_bytes)} bytes)")

    out_json = output_dir / "conus-precip-1yr-1979.json"
    out_json.write_text(json.dumps(meta, indent=2))
    print(f"Saved metadata: {out_json}")

    print("-" * 70)
    assert meta.get("n_time_steps") == 1460, (
        f"Expected 1460 time steps, got {meta.get('n_time_steps')}"
    )
    assert meta.get("n_face_subset") == 23510, (
        f"Expected 23510 subset faces, got {meta.get('n_face_subset')}"
    )
    assert meta.get("n_face_total") == 777602, (
        f"Expected 777602 total faces, got {meta.get('n_face_total')}"
    )
    print("✓ Act II checks passed successfully!")
    return meta


def run_act3(output_dir: Path) -> Dict[str, Any]:
    """Act III: 10-Year Remote Precipitation Mean (1979-1988)."""
    print("\n" + "=" * 70)
    print("ACT III: 10-Year Remote Precipitation Mean (1979-1988)")
    paths = get_data_paths(1979, 1988)
    print(f"Grid: {GRID_PATH}")
    print(f"Data files: {len(paths)} annual files")
    print(f"Endpoint: {ENDPOINT}")
    print("=" * 70)

    from uxarray_mcp.tools.frontdoor import plot_dataset

    t0 = time.time()
    res = plot_dataset(
        plot_type="temporal_mean",
        grid_path=GRID_PATH,
        data_paths=paths,
        variable_name="PRECT",
        lon_bounds=LON_BOUNDS,
        lat_bounds=LAT_BOUNDS,
        scale_factor=SCALE_FACTOR,
        units_label=UNITS_LABEL,
        region_name=REGION_NAME,
        cmap=CMAP,
        width=WIDTH,
        height=HEIGHT,
        coastlines=True,
        use_remote=True,
        endpoint=ENDPOINT,
    )
    elapsed = time.time() - t0

    meta, png_bytes = extract_plot_result(res)
    prov = meta.get("_provenance") or {}
    worker = (meta.get("_worker_runtime") or {}).get("hostname") or prov.get(
        "remote_hostname"
    )
    vstats = meta.get("value_stats") or {}

    print(f"ELAPSED           {elapsed:.1f} s")
    print(f"n_files           {meta.get('n_files')}")
    print(f"n_time_steps      {meta.get('n_time_steps')}")
    print(f"time span         {meta.get('time_start')}  →  {meta.get('time_end')}")
    n_sub = meta.get("n_face_subset")
    n_tot = meta.get("n_face_total")
    frac = (n_sub / n_tot * 100.0) if n_sub and n_tot else 0.0
    print(f"n_face_subset     {n_sub}  of {n_tot}   ({frac:.2f}% of the mesh)")
    print(
        f"value_stats       min {vstats.get('min'):.3f}   "
        f"mean {vstats.get('mean'):.3f}   "
        f"max {vstats.get('max'):.3f} {UNITS_LABEL}   "
        f"n_nonfinite {vstats.get('n_nonfinite')}"
    )
    print(f"execution_venue   {meta.get('execution_venue')}")
    print(f"worker            {worker}")
    print(f"provenance.tool   {prov.get('tool')}")
    print(f"provenance.op_id  {prov.get('operation_id')}")

    if png_bytes:
        out_png = output_dir / "conus-precip-10yr-reproduced.png"
        out_png.write_bytes(png_bytes)
        print(f"Saved plot: {out_png} ({len(png_bytes)} bytes)")

    out_json = output_dir / "conus-precip-10yr-reproduced.json"
    out_json.write_text(json.dumps(meta, indent=2))
    print(f"Saved metadata: {out_json}")

    print("-" * 70)
    assert meta.get("n_files") == 10, f"Expected 10 files, got {meta.get('n_files')}"
    assert meta.get("n_time_steps") == 14600, (
        f"Expected 14600 time steps, got {meta.get('n_time_steps')}"
    )
    assert meta.get("n_face_subset") == 23510, (
        f"Expected 23510 subset faces, got {meta.get('n_face_subset')}"
    )
    assert meta.get("n_face_total") == 777602, (
        f"Expected 777602 total faces, got {meta.get('n_face_total')}"
    )
    assert vstats.get("n_nonfinite") == 0, (
        f"Expected 0 non-finite values, got {vstats.get('n_nonfinite')}"
    )
    # Verify value stats match published case study within rounding tolerance.
    # The type is asserted first so a missing field fails as a missing field
    # rather than as a TypeError inside abs().
    mean_val = vstats.get("mean")
    assert isinstance(mean_val, (int, float)), (
        f"Expected a numeric mean in value_stats, got {mean_val!r}"
    )
    assert abs(mean_val - 2.232) < 0.05, f"Expected mean ~2.232, got {mean_val}"
    print("✓ Act III checks passed successfully!")
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--act", choices=["1", "2", "3"], help="Run specific act")
    parser.add_argument(
        "--all", action="store_true", help="Run Act I, Act II, and Act III"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent
        / "case-studies"
        / "conus-precipitation-gdex",
        help="Directory to save generated artifacts",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.act == "1":
        run_act1()
    elif args.act == "2":
        run_act2(args.output_dir)
    elif args.act == "3":
        run_act3(args.output_dir)
    elif args.all or not args.act:
        run_act1()
        run_act2(args.output_dir)
        run_act3(args.output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
