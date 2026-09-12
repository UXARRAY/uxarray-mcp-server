"""Case-study plots: original ERA5 field, target mesh footprint, and
round-trip bias maps for each remap method."""

import json

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

OUT = "/tmp/era5_raw"

era5 = xr.open_dataset(f"{OUT}/era5_conus_mean_precip.nc")
lat = era5["latitude"].values
lon = era5["longitude"].values
field = era5["precip_mm_day"].values

fig, ax = plt.subplots(figsize=(9, 6))
pcm = ax.pcolormesh(lon, lat, field, cmap="Blues", shading="auto", vmin=0, vmax=field.max())
ax.set_title("ERA5 mean daily precip, native 0.25 deg grid, CONUS Jan 1-15 2020")
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
fig.colorbar(pcm, ax=ax, label="precip_mm_day")
fig.tight_layout()
fig.savefig(f"{OUT}/plot_era5_original.png", dpi=110)
plt.close(fig)

with open(f"{OUT}/remap_fidelity_results.json") as fh:
    results = json.load(fh)

methods = list(results["methods"].keys())
fig, axes = plt.subplots(1, len(methods), figsize=(6 * len(methods), 5), sharey=True)
for ax, method in zip(axes, methods):
    roundtrip = np.load(f"{OUT}/roundtrip_{method}.npy")
    diff = roundtrip - field
    vmax = np.nanmax(np.abs(diff))
    pcm = ax.pcolormesh(lon, lat, diff, cmap="RdBu_r", shading="auto", vmin=-vmax, vmax=vmax)
    m = results["methods"][method]
    ax.set_title(
        f"{method}\nbias={m['bias_mm_day']:.4f}  rmse={m['rmse_mm_day']:.4f}\ncorr={m['pattern_correlation']:.3f}"
    )
    ax.set_xlabel("Longitude")
    fig.colorbar(pcm, ax=ax, label="round-trip minus original (mm/day)", shrink=0.85)
axes[0].set_ylabel("Latitude")
fig.suptitle("Round-trip bias: ERA5 -> ne30pg3 CONUS mesh -> back to ERA5 grid")
fig.tight_layout()
fig.savefig(f"{OUT}/plot_roundtrip_bias.png", dpi=110)
plt.close(fig)

print("wrote plot_era5_original.png and plot_roundtrip_bias.png")
