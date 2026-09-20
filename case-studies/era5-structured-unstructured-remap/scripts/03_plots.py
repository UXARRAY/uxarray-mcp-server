"""Case-study plots: original ERA5 field and round-trip bias maps for every
remap method (three UXarray-native, three YAC), all with real coastlines
and US state/country borders (Cartopy, Natural Earth 50m).

Run with the project's own .venv -- no YAC or MPI dependency here, since
this only reads the already-computed .nc/.npy/.json outputs of
02_remap_roundtrip.py and 04_yac_conservative_remap.py.
"""

import json
import pathlib

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
import paths
import xarray as xr

OUT = str(paths.DATA)
IMG = str(paths.IMAGES)
paths.ensure_dirs()

era5 = xr.open_dataset(f"{OUT}/era5_conus_mean_precip.nc")
lat = era5["latitude"].values
lon = era5["longitude"].values
field = era5["precip_mm_day"].values

# --- Plot 1: original ERA5 field ---
fig = plt.figure(figsize=(9, 6))
ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
ax.set_extent([lon.min(), lon.max(), lat.min(), lat.max()], crs=ccrs.PlateCarree())
pcm = ax.pcolormesh(
    lon,
    lat,
    field,
    cmap="Blues",
    shading="auto",
    vmin=0,
    vmax=field.max(),
    transform=ccrs.PlateCarree(),
)
ax.coastlines(resolution="50m")
ax.add_feature(cfeature.BORDERS.with_scale("50m"), linestyle=":")
ax.add_feature(cfeature.STATES.with_scale("50m"), linewidth=0.3)
gl = ax.gridlines(draw_labels=True, linewidth=0.2, color="gray", alpha=0.5)
gl.top_labels = False
gl.right_labels = False
ax.set_title("ERA5 mean daily precip, native 0.25 deg grid, CONUS Jan 1-15 2020")
fig.colorbar(pcm, ax=ax, label="precip_mm_day", shrink=0.8)
fig.tight_layout()
fig.savefig(f"{IMG}/era5_original_conus.png", dpi=110)
plt.close(fig)
print("wrote era5_original_conus.png")

# --- Plot 2: round-trip bias for all six methods (native + YAC) ---
with open(f"{OUT}/remap_fidelity_results.json") as fh:
    results = json.load(fh)

# Plot only the methods whose round-trip field is actually on disk. The YAC
# ones come from 04, which needs a from-source YAC+YAXT build (Step 7a), so
# running 02 -> 03 without it should produce the three-method figure rather
# than a FileNotFoundError three frames into numpy.
methods = [
    m for m in results["methods"] if (pathlib.Path(OUT) / f"roundtrip_{m}.npy").exists()
]
missing = [m for m in results["methods"] if m not in methods]
if missing:
    print(f"skipping (no roundtrip_*.npy, run 04 first): {', '.join(missing)}")
if not methods:
    raise SystemExit("no round-trip fields found; run 02_remap_roundtrip.py first")

fig, axes = plt.subplots(
    1,
    len(methods),
    figsize=(5.2 * len(methods), 5),
    subplot_kw={"projection": ccrs.PlateCarree()},
)
for ax, method in zip(axes, methods):
    roundtrip = np.load(f"{OUT}/roundtrip_{method}.npy")
    diff = roundtrip - field
    vmax = np.nanmax(np.abs(diff))
    ax.set_extent([lon.min(), lon.max(), lat.min(), lat.max()], crs=ccrs.PlateCarree())
    pcm = ax.pcolormesh(
        lon,
        lat,
        diff,
        cmap="RdBu_r",
        shading="auto",
        vmin=-vmax,
        vmax=vmax,
        transform=ccrs.PlateCarree(),
    )
    ax.coastlines(resolution="50m")
    ax.add_feature(cfeature.BORDERS.with_scale("50m"), linestyle=":")
    ax.add_feature(cfeature.STATES.with_scale("50m"), linewidth=0.3)
    m = results["methods"][method]
    ax.set_title(
        f"{method}\nbias={m['bias_mm_day']:.4f}  rmse={m['rmse_mm_day']:.4f}\ncorr={m['pattern_correlation']:.3f}",
        fontsize=9,
    )
    fig.colorbar(pcm, ax=ax, label="round-trip minus original (mm/day)", shrink=0.7)
fig.suptitle("Round-trip bias: ERA5 -> ne30pg3 CONUS mesh -> back to ERA5 grid")
fig.tight_layout()
fig.savefig(f"{IMG}/roundtrip_bias_all_methods.png", dpi=110)
plt.close(fig)
print("wrote roundtrip_bias_all_methods.png with", len(methods), "methods:", methods)
