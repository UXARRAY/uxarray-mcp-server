"""Build the CONUS mean daily precipitation field from raw ERA5 files.

ERA5's fc.sfc.accumu products store forecast accumulations: each
forecast_initial_time (06Z or 18Z) accumulates from 0 at forecast_hour=1
through forecast_hour=12. forecast_hour=12 is therefore the full 12h total
for that run. Two runs per day (06Z + 18Z) sum to a 24h total. Units are m.
"""

import numpy as np
import paths
import xarray as xr

LAT_SLICE = slice(50, 20)  # descending, matches file's lat order (90 -> -90)
LON_SLICE = slice(230, 295)  # 0-360 convention; CONUS is -130..-65 E

lsp = xr.open_dataset(paths.require(paths.LSP_NC, "python scripts/00_download_era5.py"))
cp = xr.open_dataset(paths.require(paths.CP_NC, "python scripts/00_download_era5.py"))

lsp12 = lsp["LSP"].isel(forecast_hour=11).sel(latitude=LAT_SLICE, longitude=LON_SLICE)
cp12 = cp["CP"].isel(forecast_hour=11).sel(latitude=LAT_SLICE, longitude=LON_SLICE)

total_per_run = (lsp12 + cp12).load()  # (forecast_initial_time, lat, lon), meters
print("per-run total precip shape:", total_per_run.shape)
print("per-run min/max (m):", float(total_per_run.min()), float(total_per_run.max()))

n_runs = total_per_run.sizes["forecast_initial_time"]
assert n_runs % 2 == 0, "expected paired 06Z/18Z runs"
daily = total_per_run.values.reshape(n_runs // 2, 2, *total_per_run.shape[1:]).sum(
    axis=1
)
n_days = daily.shape[0]
print(f"reconstructed {n_days} daily totals from {n_runs} forecast runs")

mean_daily_m = daily.mean(axis=0)
mean_daily_mm = mean_daily_m * 1000.0

lat = total_per_run.latitude.values
lon = total_per_run.longitude.values
lon_180 = np.where(lon > 180, lon - 360, lon)

out = xr.Dataset(
    {
        "precip_mm_day": (
            ("latitude", "longitude"),
            mean_daily_mm.astype(np.float32),
        )
    },
    coords={
        "latitude": (
            "latitude",
            lat,
            {"standard_name": "latitude", "units": "degrees_north"},
        ),
        "longitude": (
            "longitude",
            lon_180,
            {"standard_name": "longitude", "units": "degrees_east"},
        ),
    },
)
out["precip_mm_day"].attrs = {
    "long_name": "Mean daily total precipitation (large-scale + convective)",
    "units": "mm/day",
    "source": "ERA5 e5.oper.fc.sfc.accumu, params 142 (lsp) + 143 (cp)",
    "period": "2020-01-01 to 2020-01-15 (15 days, 30 forecast runs)",
}
out.attrs["Conventions"] = "CF-1.8"
out.attrs["title"] = "ERA5 CONUS mean daily precipitation, Jan 1-15 2020"

paths.ensure_dirs()
out.to_netcdf(paths.SOURCE_NC)
print("wrote", paths.SOURCE_NC)
print("grid shape:", lat.shape, lon.shape)
print(
    "mean precip mm/day: min",
    float(mean_daily_mm.min()),
    "max",
    float(mean_daily_mm.max()),
    "mean",
    float(mean_daily_mm.mean()),
)
