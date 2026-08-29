#!/usr/bin/env python3
"""Prove ``reduced_dims`` survives a real Globus Compute round trip.

The worker copies of the dim-classification logic are hand-inlined into each
function in ``uxarray_mcp.remote.compute_functions`` because ``AllCodeStrategies``
serializes one function body at a time and module-level helpers do not survive
the trip. The pytest suite calls those workers *in-process*, which never
exercises serialization -- the exact mechanism the inlined copies exist to
compensate for. This script closes that gap by submitting them for real.

It writes its own fixture so it does not depend on locating a model file with
both a time and a vertical axis. Values are ``1000*t + 100*(level+1)``, so the
magnitude alone identifies the slice: a wrong time is off by a thousand, a
wrong level by a hundred. With ``--time-index 2 --level-index 1`` every
returned field must be exactly 2200.0.

Manual live check, not a pytest module. The fixture directory must be visible
to the worker, so put it on a shared filesystem::

    uv run python scripts/remote_reduced_dims_check.py \
        --endpoint chrysalis \
        --work-dir /lcrc/group/e3sm/$USER/reduced_dims_check
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from uxarray_mcp.remote.compute_functions import (
    remote_calculate_curl,
    remote_calculate_divergence,
    remote_calculate_gradient,
    remote_calculate_zonal_mean,
    remote_plot_zonal_mean,
)
from uxarray_mcp.remote.config import load_config

N_TIME = 3
N_LEVEL = 4


def build_fixture(work_dir: Path) -> tuple[str, str]:
    """Write a mesh plus a time x level x face field the worker can open."""
    import numpy as np
    import uxarray as ux
    import xarray as xr

    work_dir.mkdir(parents=True, exist_ok=True)
    grid_file = work_dir / "time_level_grid.nc"
    data_file = work_dir / "time_level_data.nc"

    lon = np.arange(0, 360, 30.0)
    lat = np.arange(-75, 76, 30.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid.to_xarray().to_netcdf(grid_file)

    values = np.stack(
        [
            np.stack(
                [
                    np.full(grid.n_face, 1000.0 * t + 100.0 * (k + 1))
                    for k in range(N_LEVEL)
                ]
            )
            for t in range(N_TIME)
        ]
    )
    dims = ["time", "n_level", "n_face"]
    xr.Dataset(
        {
            "temperature": (dims, values),
            "u": (dims, values),
            "v": (dims, values),
        },
        coords={"time": np.arange(N_TIME), "n_level": np.arange(N_LEVEL)},
    ).to_netcdf(data_file)

    return str(grid_file), str(data_file)


def expected_reduced(time_index: int, level_index: int) -> dict[str, Any]:
    return {
        "time": {"kind": "time", "index": time_index, "size": N_TIME},
        "n_level": {"kind": "level", "index": level_index, "size": N_LEVEL},
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", default=None, help="Configured endpoint name.")
    p.add_argument(
        "--work-dir",
        type=Path,
        required=True,
        help="Directory visible to BOTH this host and the worker.",
    )
    p.add_argument("--time-index", type=int, default=2)
    p.add_argument("--level-index", type=int, default=1)
    p.add_argument("--timeout-seconds", type=int, default=600)
    args = p.parse_args()

    config = load_config().for_endpoint(endpoint=args.endpoint)
    if not config.endpoint_id:
        raise SystemExit(f"No endpoint_id resolved for {args.endpoint!r}")

    grid_path, data_path = build_fixture(args.work_dir)
    print(f"==> fixture written to {args.work_dir}")

    from globus_compute_sdk import Executor
    from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

    executor = Executor(
        endpoint_id=config.endpoint_id,
        serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
    )

    ti, li = args.time_index, args.level_index
    submissions = (
        (
            "calculate_zonal_mean",
            remote_calculate_zonal_mean,
            (grid_path, data_path, "temperature", None, False, ti, li),
        ),
        (
            "plot_zonal_mean",
            remote_plot_zonal_mean,
            (
                grid_path,
                data_path,
                "temperature",
                800,
                400,
                None,
                False,
                "#1f77b4",
                None,
                ti,
                li,
            ),
        ),
        (
            "calculate_gradient",
            remote_calculate_gradient,
            (grid_path, data_path, "temperature", True, ti, li),
        ),
        (
            "calculate_curl",
            remote_calculate_curl,
            (grid_path, data_path, "u", "v", True, ti, li),
        ),
        (
            "calculate_divergence",
            remote_calculate_divergence,
            (grid_path, data_path, "u", "v", True, ti, li),
        ),
    )

    futures = []
    with executor:
        for label, func, call_args in submissions:
            print(f"==> submitting {label}")
            futures.append((label, executor.submit(func, *call_args)))

        want = expected_reduced(ti, li)
        failures = []
        for label, future in futures:
            try:
                result = future.result(timeout=args.timeout_seconds)
            except Exception as exc:  # noqa: BLE001 - report, do not abort the rest
                failures.append(f"{label}: raised {type(exc).__name__}: {exc}")
                print(f"FAIL {label}: {type(exc).__name__}: {exc}")
                continue

            got = result.get("reduced_dims")
            if got is None:
                failures.append(f"{label}: no reduced_dims key in payload")
                print(f"FAIL {label}: payload has no reduced_dims")
                print(f"     keys: {sorted(result)}")
                continue
            if got != want:
                failures.append(f"{label}: reduced_dims {got} != {want}")
                print(f"FAIL {label}: reduced_dims mismatch")
                print(f"     got  {json.dumps(got, sort_keys=True)}")
                print(f"     want {json.dumps(want, sort_keys=True)}")
                continue
            print(f"ok   {label}: reduced_dims {json.dumps(got, sort_keys=True)}")

    if failures:
        print(f"\n{len(failures)} of {len(submissions)} failed:")
        for line in failures:
            print(f"  - {line}")
        return 1

    print(
        f"\nAll {len(submissions)} workers reported reduced_dims through serialization."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
