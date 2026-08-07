"""Multi-operation DYAMOND workflow across the resolution ladder.

Answers the question the paper actually needs: when an agent is asked
"subset this region and give me the zonal mean", what does each step cost,
and how does that cost scale with mesh resolution and with field location
(face-centred vs node-centred)?

Runs on the NCAR Globus Compute endpoint because the 3.75 km grid alone is
19.8 GB. Data are DYAMOND-1 (Judt et al.), the same archive UXarray's ASV
suite uses, so the axis is comparable with prior work.
"""

from __future__ import annotations

import json
import sys
import time
import warnings

warnings.filterwarnings("ignore")

GRID = "/glade/campaign/cisl/vast/uxarray/data/dyamond/{res}/grid.nc"
DATA = (
    "/glade/campaign/mmm/wmr/fjudt/projects/dyamond_1/{res}/diag.2016-08-01_00.00.00.nc"
)
RES = ["30km", "15km", "7.5km", "3.75km"]
EP = "ucar-uxarray-yac"


def remote_workflow(res: str) -> dict:
    """Self-contained: runs on the worker, no uxarray_mcp import."""
    import os
    import platform
    import socket
    import time

    import numpy as np
    import uxarray as ux

    grid = "/glade/campaign/cisl/vast/uxarray/data/dyamond/%s/grid.nc" % res
    data = (
        "/glade/campaign/mmm/wmr/fjudt/projects/dyamond_1/%s/"
        "diag.2016-08-01_00.00.00.nc" % res
    )

    out = {
        "resolution": res,
        "grid_bytes": os.path.getsize(grid),
        "data_bytes": os.path.getsize(data),
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "uxarray": ux.__version__,
        "ops": {},
    }

    def timed(key, fn):
        t0 = time.perf_counter()
        r = fn()
        out["ops"][key] = time.perf_counter() - t0
        return r

    # 1. open grid + data together (what a user request actually triggers)
    uxds = timed("open", lambda: ux.open_dataset(grid, data))
    g = uxds.uxgrid
    out["n_face"] = int(g.n_face)
    out["n_node"] = int(g.n_node)

    # 2. face-centred field: load values into memory
    t2m = uxds["t2m"].isel(time=0)
    timed("load_face", lambda: t2m.values)
    out["n_values_face"] = int(t2m.size)

    # 3. global mean of the face field (cheap reduction over all values)
    out["mean_t2m"] = float(timed("mean_face", lambda: t2m.values.mean()))

    # 4. one-time structural cost: spherical bounding box per face.
    #    The first zonal mean pays for this; every later one does not.
    #    Isolating it is the difference between a 60 s and a 0.8 s answer.

    timed("bounds_cold", lambda: g.bounds)

    # 5. zonal mean with bounds already built -- the true per-request cost.
    zm = timed("zonal_1deg", lambda: t2m.zonal_mean(lat=(-90, 90, 1)))
    zmv = np.asarray(zm.values)
    out["zonal_bins"] = int(zmv.size)
    out["zonal_min"] = float(np.nanmin(zmv))
    out["zonal_max"] = float(np.nanmax(zmv))
    reps = []
    for _ in range(3):
        t0 = time.perf_counter()
        t2m.zonal_mean(lat=(-90, 90, 1))
        reps.append(time.perf_counter() - t0)
    out["ops"]["zonal_1deg_warm"] = float(np.median(reps))

    zm5 = timed("zonal_5deg", lambda: t2m.zonal_mean(lat=(-90, 90, 5)))
    out["zonal5_bins"] = int(np.asarray(zm5.values).size)
    reps5 = []
    for _ in range(3):
        t0 = time.perf_counter()
        t2m.zonal_mean(lat=(-90, 90, 5))
        reps5.append(time.perf_counter() - t0)
    out["ops"]["zonal_5deg_warm"] = float(np.median(reps5))

    # 6. regional subset: a tropical-cyclone-sized box in the W Pacific
    sub = timed("subset_bbox", lambda: t2m.subset.bounding_box((120, 160), (0, 30)))
    out["subset_faces"] = int(sub.uxgrid.n_face)

    # 7. zonal mean on the subset -- cost after data reduction
    timed("zonal_on_subset", lambda: sub.zonal_mean(lat=(0, 30, 1)))

    # 8. node-centred field: vorticity lives on vertices, not cells
    vort = uxds["vorticity_200hPa"].isel(time=0)
    timed("load_node", lambda: vort.values)
    out["n_values_node"] = int(vort.size)
    out["mean_vort"] = float(np.asarray(vort.values).mean())

    uxds.close()
    return out


def main() -> int:
    which = sys.argv[1:] or RES
    import asyncio

    from uxarray_mcp.remote.agent import UXarrayComputeAgent
    from uxarray_mcp.remote.config import load_config

    cfg = load_config()
    outfile = "benchmarks/dyamond/data_ladder_results.json"
    try:
        results = json.load(open(outfile))
    except Exception:
        results = []
    results = [r for r in results if r.get("resolution") not in which]

    for res in which:
        print("=== %s ===" % res, flush=True)
        t0 = time.time()
        try:
            prof = cfg.for_endpoint(EP)
            prof.timeout_seconds = 3000  # big rungs need it
            agent = UXarrayComputeAgent(prof)
            r = asyncio.run(agent._run_on_hpc(remote_workflow, res))
            r["_wall_s"] = time.time() - t0
            results.append(r)
            print(json.dumps(r.get("ops", {}), indent=2), flush=True)
            print("faces=%s wall=%.1fs" % (r.get("n_face"), r["_wall_s"]), flush=True)
        except Exception as e:
            print(
                "%s FAILED after %.1fs: %s: %s"
                % (res, time.time() - t0, type(e).__name__, str(e)[:400]),
                flush=True,
            )
            results.append(
                {
                    "resolution": res,
                    "error": "%s: %s" % (type(e).__name__, str(e)[:400]),
                }
            )
        with open(outfile, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print("-> wrote %s" % outfile, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
