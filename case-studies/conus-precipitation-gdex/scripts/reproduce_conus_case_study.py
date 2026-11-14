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
from typing import Any

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

# How long each get_operation() call blocks while a remote task that outlived
# the endpoint timeout keeps running.
POLL_WAIT_SECONDS = 60.0


def get_data_paths(start_year: int = 1979, end_year: int = 1988) -> list[str]:
    paths = []
    for y in range(start_year, end_year + 1):
        filename = f"{DATA_PREFIX}{y}010100-{y + 1}010100.nc"
        paths.append(f"{DATA_BASE_DIR}{filename}")
    return paths


def wait_for_operation(result: dict[str, Any]) -> dict[str, Any]:
    """Poll get_operation until a `status: running` result finishes."""
    from uxarray_mcp.server import tools

    while isinstance(result, dict) and result.get("status") == "running":
        op_id = result.get("operation_id")
        if not op_id:
            break
        print(f"... still running on the worker (operation {op_id}); waiting")
        result = tools.get_operation(operation_id=op_id, wait_seconds=POLL_WAIT_SECONDS)
    return result


def run_act1() -> dict[str, Any]:
    """Act I: Remote mesh inspection."""
    print("=" * 70)
    print("ACT I: Remote Mesh Inspection")
    print(f"Grid: {GRID_PATH}")
    print(f"Endpoint: {ENDPOINT}")
    print("=" * 70)

    from uxarray_mcp.server import tools

    t0 = time.time()
    res = tools.inspect_dataset(
        grid_path=GRID_PATH,
        use_remote=True,
        endpoint=ENDPOINT,
    )
    res = wait_for_operation(res)
    elapsed = time.time() - t0

    prov = res.get("_provenance") or {}
    remote = prov.get("remote") or {}

    print(f"ELAPSED           {elapsed:.1f} s")
    print(f"format            {res.get('format')}")
    print(f"n_face            {res.get('n_face')}")
    print(f"n_node            {res.get('n_node')}")
    print(f"n_edge            {res.get('n_edge')}")
    print(f"size_class        {res.get('size_class')}")
    print(f"plot_hint         {res.get('plot_hint')}")
    print(f"venue             {prov.get('venue')}")
    print(f"worker            {remote.get('hostname')}")
    print(
        f"worker versions   python {remote.get('python_version')}   "
        f"uxarray {remote.get('uxarray_version')}"
    )
    print("-" * 70)

    assert res.get("n_face") == 777602, (
        f"Expected 777602 faces, got {res.get('n_face')}"
    )
    assert res.get("n_node") == 780456, (
        f"Expected 780456 nodes, got {res.get('n_node')}"
    )
    assert res.get("n_edge") == 2329471, (
        f"Expected 2329471 edges, got {res.get('n_edge')}"
    )
    print("✓ Act I checks passed successfully!")
    return res


def _decode_png(data: Any) -> bytes | None:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str) and data:
        return base64.b64decode(data)
    return None


def extract_plot_result(mcp_contents: Any) -> tuple[dict[str, Any], bytes | None]:
    """Split a `plot` reply into its JSON metadata and PNG bytes.

    `plot` returns `[image | resource_link, text]`. The image block carries
    inline base64 under 256 kB; above that the first block is a
    `resource_link` whose `uri` is a `file://` path to the stored PNG and the
    text block's `image_path` points at the same file. A result collected
    through `get_operation` is a single dict carrying `png` directly.
    """
    meta: dict[str, Any] = {}
    png_bytes: bytes | None = None

    if isinstance(mcp_contents, dict):
        meta = dict(mcp_contents)
        png_bytes = _decode_png(meta.pop("png", None))
        return meta, png_bytes

    def _get(block: Any, name: str, default: Any = None) -> Any:
        if isinstance(block, dict):
            return block.get(name, default)
        return getattr(block, name, default)

    for block in mcp_contents:
        btype = _get(block, "type")
        if btype == "text":
            text = _get(block, "text", "{}")
            try:
                meta = json.loads(text)
            except json.JSONDecodeError:
                meta = {"raw_text": text}
        elif btype == "image":
            src = _get(block, "source") or {}
            png_bytes = _decode_png(_get(src, "data")) or _decode_png(
                _get(block, "data")
            )
        elif btype == "resource_link":
            uri = _get(block, "uri") or ""
            if uri.startswith("file://"):
                stored = Path(uri[len("file://") :])
                if stored.is_file():
                    png_bytes = stored.read_bytes()

    if not png_bytes and meta.get("image_path"):
        stored = Path(str(meta["image_path"]))
        if stored.is_file():
            png_bytes = stored.read_bytes()

    return meta, png_bytes


def _plot_temporal_mean(paths: list[str]) -> tuple[dict[str, Any], bytes | None]:
    from uxarray_mcp.server import tools

    res = tools.plot(
        kind="temporal_mean",
        grid_path=GRID_PATH,
        data_paths=paths,
        variable_name="PRECT",
        lon_bounds=LON_BOUNDS,
        lat_bounds=LAT_BOUNDS,
        scale_factor=SCALE_FACTOR,
        units_label=UNITS_LABEL,
        title=REGION_NAME,
        cmap=CMAP,
        width=WIDTH,
        height=HEIGHT,
        use_remote=True,
        endpoint=ENDPOINT,
    )
    meta, png_bytes = extract_plot_result(res)
    if meta.get("status") == "running":
        meta, png_bytes = extract_plot_result(wait_for_operation(meta))
    if meta.get("status") == "error":
        raise RuntimeError(
            f"remote plot failed: {meta.get('error_code')}: {meta.get('message')}"
        )
    return meta, png_bytes


def _print_plot_report(elapsed: float, meta: dict[str, Any]) -> None:
    prov = meta.get("_provenance") or {}
    remote = prov.get("remote") or {}
    vstats = meta.get("value_stats") or {}

    print(f"ELAPSED           {elapsed:.1f} s")
    print(f"n_files           {meta.get('n_files')}")
    print(f"n_time_steps      {meta.get('n_time_steps')}")
    print(f"time span         {meta.get('time_min')}  →  {meta.get('time_max')}")
    n_sub = meta.get("n_faces_in_region")
    n_tot = meta.get("n_faces_total")
    frac = (n_sub / n_tot * 100.0) if n_sub and n_tot else 0.0
    print(f"n_faces_in_region {n_sub}  of {n_tot}   ({frac:.2f}% of the mesh)")
    print(
        f"value_stats       min {vstats.get('min'):.3f}   "
        f"mean {vstats.get('mean'):.3f}   "
        f"max {vstats.get('max'):.3f} {UNITS_LABEL}"
    )
    print(f"render_mode       {meta.get('render_mode')}")
    print(f"venue             {prov.get('venue')}")
    print(f"worker            {remote.get('hostname')}")
    print(f"provenance.tool   {prov.get('tool')}")
    print(f"provenance.op_id  {remote.get('operation_id')}")
    print(f"worker elapsed    {remote.get('worker_elapsed_seconds')} s")


def run_act2(output_dir: Path) -> dict[str, Any]:
    """Act II: 1-Year Remote Precipitation Mean (1979)."""
    print("\n" + "=" * 70)
    print("ACT II: 1-Year Remote Precipitation Mean (1979)")
    paths = get_data_paths(1979, 1979)
    print(f"Grid: {GRID_PATH}")
    print(f"Data: {paths[0]}")
    print(f"Endpoint: {ENDPOINT}")
    print("=" * 70)

    t0 = time.time()
    meta, png_bytes = _plot_temporal_mean(paths)
    elapsed = time.time() - t0

    _print_plot_report(elapsed, meta)

    if png_bytes:
        out_png = output_dir / "conus-precip-1yr-1979.png"
        out_png.write_bytes(png_bytes)
        print(f"Saved plot: {out_png} ({len(png_bytes)} bytes)")

    out_json = output_dir / "conus-precip-1yr-1979.json"
    out_json.write_text(json.dumps(meta, indent=2, default=str))
    print(f"Saved metadata: {out_json}")

    print("-" * 70)
    assert meta.get("n_time_steps") == 1460, (
        f"Expected 1460 time steps, got {meta.get('n_time_steps')}"
    )
    assert meta.get("n_faces_in_region") == 23510, (
        f"Expected 23510 faces in region, got {meta.get('n_faces_in_region')}"
    )
    assert meta.get("n_faces_total") == 777602, (
        f"Expected 777602 total faces, got {meta.get('n_faces_total')}"
    )
    print("✓ Act II checks passed successfully!")
    return meta


def run_act3(output_dir: Path) -> dict[str, Any]:
    """Act III: 10-Year Remote Precipitation Mean (1979-1988)."""
    print("\n" + "=" * 70)
    print("ACT III: 10-Year Remote Precipitation Mean (1979-1988)")
    paths = get_data_paths(1979, 1988)
    print(f"Grid: {GRID_PATH}")
    print(f"Data files: {len(paths)} annual files")
    print(f"Endpoint: {ENDPOINT}")
    print("=" * 70)

    t0 = time.time()
    meta, png_bytes = _plot_temporal_mean(paths)
    elapsed = time.time() - t0

    _print_plot_report(elapsed, meta)
    vstats = meta.get("value_stats") or {}

    if png_bytes:
        out_png = output_dir / "conus-precip-10yr-reproduced.png"
        out_png.write_bytes(png_bytes)
        print(f"Saved plot: {out_png} ({len(png_bytes)} bytes)")

    out_json = output_dir / "conus-precip-10yr-reproduced.json"
    out_json.write_text(json.dumps(meta, indent=2, default=str))
    print(f"Saved metadata: {out_json}")

    print("-" * 70)
    assert meta.get("n_files") == 10, f"Expected 10 files, got {meta.get('n_files')}"
    assert meta.get("n_time_steps") == 14600, (
        f"Expected 14600 time steps, got {meta.get('n_time_steps')}"
    )
    assert meta.get("n_faces_in_region") == 23510, (
        f"Expected 23510 faces in region, got {meta.get('n_faces_in_region')}"
    )
    assert meta.get("n_faces_total") == 777602, (
        f"Expected 777602 total faces, got {meta.get('n_faces_total')}"
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
        default=Path(__file__).resolve().parent.parent,
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
