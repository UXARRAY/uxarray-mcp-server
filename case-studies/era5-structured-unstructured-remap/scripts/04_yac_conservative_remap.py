"""Repeat the forward remap through YAC's own interpolation methods
(conservative, nnn, average), for comparison against the three
UXarray-native methods computed by 02_remap_roundtrip.py.

YAC is not pip-installable as a prebuilt wheel: its Python bindings are
built from source (https://gitlab.dkrz.de/dkrz-sw/yac) against libyaxt
(https://gitlab.dkrz.de/dkrz-sw/yaxt), an MPI exchange library that is
itself a from-source autotools build with no PyPI or conda-forge wheel that
matches an arbitrary local MPI. Both are now built from source directly
into this project's own .venv (YAXT 0.12.1 at ~/opt/yaxt-local, YAC 3.21.0
via `uv pip install`), linked against the same Homebrew Open MPI the rest
of this case study uses -- confirmed via `otool -L` on yac's compiled
extension, which links directly against
/opt/homebrew/opt/open-mpi/lib/libmpi.40.dylib and
~/opt/yaxt-local/lib/libyaxt_c.1.dylib. See the README's Step 7a for the
exact build steps (including a libtool patch this machine's toolchain
required). Run this script with the project's own .venv, same as every
other script here:

    python scripts/04_yac_conservative_remap.py

It reads the same source/target files 02_remap_roundtrip.py used and merges
its results into the same remap_fidelity_results.json.
"""

import json

import numpy as np
import uxarray as ux
import xarray as xr

SOURCE_NC = "/tmp/era5_raw/era5_conus_mean_precip.nc"
TARGET_MESH_NC = "/tmp/era5_raw/ne30pg3_conus.nc"
OUT_DIR = "/tmp/era5_raw"
RESULTS_JSON = f"{OUT_DIR}/remap_fidelity_results.json"

YAC_METHODS = ["conservative", "nnn", "average"]


def main():
    src = ux.open_dataset(SOURCE_NC, SOURCE_NC)
    # Same MultiIndex workaround as 02_remap_roundtrip.py -- required
    # regardless of remap backend, since it happens before backend dispatch.
    src_var = src["precip_mm_day"].reset_index("n_face")
    target_grid = ux.open_grid(TARGET_MESH_NC)

    era5_native = xr.open_dataset(SOURCE_NC)
    orig_lat = era5_native["latitude"].values
    orig_lon = era5_native["longitude"].values
    orig_field = era5_native["precip_mm_day"].values

    with open(RESULTS_JSON) as fh:
        results = json.load(fh)

    for method in YAC_METHODS:
        forward = src_var.remap(target_grid, backend="yac", yac_method=method)
        roundtrip_da = forward.remap.to_rectilinear(lon=orig_lon, lat=orig_lat)
        roundtrip = np.asarray(roundtrip_da.transpose("lat", "lon").values)

        mask = np.isfinite(orig_field) & np.isfinite(roundtrip)
        diff = roundtrip[mask] - orig_field[mask]
        metrics = {
            "n_points": int(mask.sum()),
            "bias_mm_day": float(diff.mean()),
            "rmse_mm_day": float(np.sqrt((diff**2).mean())),
            "pattern_correlation": float(np.corrcoef(orig_field[mask], roundtrip[mask])[0, 1]),
            "original_mean_mm_day": float(orig_field[mask].mean()),
            "roundtrip_mean_mm_day": float(roundtrip[mask].mean()),
            "backend": "yac",
            "yac_method": method,
        }
        results["methods"][f"yac_{method}"] = metrics

        np.save(f"{OUT_DIR}/roundtrip_yac_{method}.npy", roundtrip)
        forward.to_dataset().to_netcdf(f"{OUT_DIR}/forward_yac_{method}.nc")

        print(f"=== yac_{method} ===")
        print(json.dumps(metrics, indent=2))

    with open(RESULTS_JSON, "w") as fh:
        json.dump(results, fh, indent=2)
    print("updated remap_fidelity_results.json with YAC methods:", YAC_METHODS)


if __name__ == "__main__":
    main()
