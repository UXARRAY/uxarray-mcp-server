"""Round-trip a real ERA5 field through a real unstructured mesh.

Source: ERA5 CONUS mean daily precipitation, on its native 0.25-degree
regular lat-lon grid, read as a UXarray "Structured" Grid (31581 faces).

Target: the real ne30pg3 spectral-element cubed-sphere mesh, subset to the
same CONUS bounding box (1867 faces) -- real geometry from the uxarray-paper
test fixtures, not synthetic.

For each of three UXarray-native remap methods (nearest_neighbor,
inverse_distance_weighted, bilinear):
  1. Forward remap: ERA5 (structured, 31581 faces) -> ne30pg3_conus
     (unstructured, 1867 faces).
  2. Backward remap: that unstructured field -> back onto ERA5's original
     0.25-degree lat/lon points, via var.remap.to_rectilinear.
  3. Compare the round-tripped field against the original ERA5 field at
     every point the unstructured mesh actually covers (points outside the
     mesh's footprint come back NaN and are excluded, not zero-filled).

This measures how much each remap method distorts a real reanalysis field
when it is moved onto a coarser, differently-shaped unstructured mesh and
back -- not a comparison against an independent "truth," since no
independent unstructured-mesh observation of the same field exists.
"""

import json

import numpy as np
import uxarray as ux

SOURCE_NC = "/tmp/era5_raw/era5_conus_mean_precip.nc"
TARGET_MESH_NC = "/tmp/era5_raw/ne30pg3_conus.nc"
OUT_DIR = "/tmp/era5_raw"

METHODS = ["nearest_neighbor", "inverse_distance_weighted", "bilinear"]


def bias_rmse_corr(a: np.ndarray, b: np.ndarray) -> dict:
    """a = original, b = round-tripped. Both same shape, may contain NaN."""
    mask = np.isfinite(a) & np.isfinite(b)
    n = int(mask.sum())
    if n == 0:
        return {"n_points": 0, "bias": None, "rmse": None, "pattern_correlation": None}
    diff = b[mask] - a[mask]
    bias = float(diff.mean())
    rmse = float(np.sqrt((diff**2).mean()))
    if n > 1 and a[mask].std() > 0 and b[mask].std() > 0:
        corr = float(np.corrcoef(a[mask], b[mask])[0, 1])
    else:
        corr = None
    return {
        "n_points": n,
        "bias_mm_day": bias,
        "rmse_mm_day": rmse,
        "pattern_correlation": corr,
        "original_mean_mm_day": float(a[mask].mean()),
        "roundtrip_mean_mm_day": float(b[mask].mean()),
    }


def main():
    src = ux.open_dataset(SOURCE_NC, SOURCE_NC)
    # Grid.from_structured retains the original (latitude, longitude) as a
    # MultiIndex on n_face so the structured shape can be recovered later.
    # UXarray's remap internals build a fresh (lat, lon) index of their own
    # on the output and collide with this leftover MultiIndex -- see
    # uxarray/remap/spatial_coords_remap.py:construct_output_coords, which
    # tries to overwrite 'latitude'/'longitude' that xarray still treats as
    # index levels. Dropping the index (keeping the coord values themselves)
    # avoids the collision without touching uxarray itself.
    src_var = src["precip_mm_day"].reset_index("n_face")

    target_grid = ux.open_grid(TARGET_MESH_NC)

    era5_lon_1d = src.uxgrid.to_xarray().attrs  # placeholder, unused
    import xarray as xr

    era5_native = xr.open_dataset(SOURCE_NC)
    orig_lat = era5_native["latitude"].values
    orig_lon = era5_native["longitude"].values
    orig_field = era5_native["precip_mm_day"].values  # (lat, lon)

    results = {}
    forward_fields = {}

    for method in METHODS:
        remap_fn = getattr(src_var.remap, method)
        forward = remap_fn(target_grid)
        forward_fields[method] = forward

        # Round trip back onto ERA5's native 1-D lat/lon axes.
        roundtrip_da = forward.remap.to_rectilinear(lon=orig_lon, lat=orig_lat)
        roundtrip = np.asarray(roundtrip_da.transpose("lat", "lon").values)

        metrics = bias_rmse_corr(orig_field, roundtrip)
        results[method] = metrics

        np.save(f"{OUT_DIR}/roundtrip_{method}.npy", roundtrip)
        forward.to_dataset().to_netcdf(f"{OUT_DIR}/forward_{method}.nc")

        print(f"=== {method} ===")
        print(json.dumps(metrics, indent=2))

    with open(f"{OUT_DIR}/remap_fidelity_results.json", "w") as fh:
        json.dump(
            {
                "source": "ERA5 e5.oper.fc.sfc.accumu (params 142+143), NSF NCAR ERA5 AWS Open Data",
                "period": "2020-01-01 to 2020-01-15",
                "variable": "precip_mm_day",
                "source_grid": {"format": "Structured (0.25 deg regular lat-lon)", "n_face": int(src.uxgrid.n_face)},
                "target_mesh": {"format": "ESMF (ne30pg3 cubed-sphere, CONUS subset)", "n_face": int(target_grid.n_face)},
                "methods": results,
            },
            fh,
            indent=2,
        )
    print("wrote remap_fidelity_results.json")


if __name__ == "__main__":
    main()
