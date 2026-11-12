"""Exercise one configured endpoint end to end with the real tools.

    uv run --with globus-compute-sdk python scripts/live_check.py --endpoint ucar-uxarray-yac \
        --path /glade/p/cesmdata/cseg/inputdata/share/scripgrids/ne120np4_pentagons_100310.nc

Runs: worker probe, a remote area on healpix:3, an auto-routed inspect of a
cluster file, a deliberately short timeout followed by get_operation.
"""

from __future__ import annotations

import argparse
import json
import time
import warnings

from uxarray_mcp.server import tools


def main() -> int:
    warnings.simplefilter("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--path", default=None, help="A file on the cluster to inspect.")
    args = ap.parse_args()
    ep = args.endpoint

    t0 = time.time()
    status = tools.endpoint(action="status", endpoint=ep, probe_timeout_seconds=150)
    w = status.get("worker", {})
    print(
        f"probe      {w.get('status')} node={w.get('hostname')} py={w.get('python_version')} "
        f"ux={w.get('uxarray_version')} mcp={w.get('server_version')} core={w.get('core_importable')} "
        f"yac={w.get('yac_available')} {time.time() - t0:.1f}s"
    )

    t0 = time.time()
    r = tools.compute(
        statistic="area",
        grid_path="healpix:3",
        sphere_radius=6371000.0,
        use_remote=True,
        endpoint=ep,
    )
    print(
        f"area       {r.get('status') or r.get('error_code')} total={r.get('total_area')} "
        f"venue={r.get('_provenance', {}).get('venue')} warnings={r.get('warnings')} {time.time() - t0:.1f}s"
    )
    if r.get("error_code"):
        print("           ", r.get("message"))

    if args.path:
        t0 = time.time()
        r = tools.inspect_dataset(grid_path=args.path, endpoint=ep)
        print(
            f"inspect    {r.get('status') or r.get('error_code')} n_face={r.get('n_face')} "
            f"format={r.get('format')} size={r.get('size_class')} hint={r.get('plot_hint')} "
            f"{time.time() - t0:.1f}s"
        )
        if r.get("error_code"):
            print("           ", r.get("message"))

    t0 = time.time()
    from uxarray_mcp.remote import executor

    r = executor.submit(
        "area",
        {"grid_path": "healpix:5", "sphere_radius": 6371000.0},
        endpoint=ep,
        timeout_seconds=1,
    )
    print(
        f"timeout    status={r.get('status')} op={r.get('operation_id')} {time.time() - t0:.1f}s"
    )
    if r.get("status") == "running":
        t0 = time.time()
        got = tools.get_operation(operation_id=r["operation_id"], wait_seconds=120)
        print(
            f"redeem     {got.get('status')} total={got.get('total_area')} "
            f"n_face={got.get('n_face')} {time.time() - t0:.1f}s"
        )

    yac = tools.endpoint(action="check_yac", endpoint=ep, probe_timeout_seconds=150)
    print(
        f"check_yac  {json.dumps(yac.get('yac'))} available={yac.get('conservative_remap_available')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
