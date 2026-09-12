# A structured-vs-unstructured mesh comparison: ERA5 through the RODA registry and UXarray's own remap engine

## The question

AWS's [Registry of Open Data (RODA)](https://registry.opendata.aws/) hosts ERA5,
a global reanalysis on a plain regular lat-lon grid — the textbook "structured
mesh." The uxarray MCP server exists to work with the opposite kind of grid —
cubed-sphere, MPAS, ICON, spectral-element meshes with irregular polygonal
cells. What actually happens, mechanically, when a real structured field has
to move onto a real unstructured mesh and back? Does it survive the round
trip, and does the answer depend on which remap method you pick?

This case study answers that with real ERA5 precipitation and a real ne30pg3
cubed-sphere mesh — no synthetic data anywhere.

## Summary of the result

Mean daily CONUS precipitation for 2020-01-01 through 2020-01-15, computed
from ERA5, was pushed onto a 1,867-cell cubed-sphere mesh subset and pulled
back onto ERA5's original 0.25° grid using three remap methods. All three
reproduce the original field closely:

| method | bias (mm/day) | RMSE (mm/day) | pattern correlation |
|---|---|---|---|
| nearest_neighbor | 0.0015 | 0.0861 | 0.941 |
| inverse_distance_weighted | 0.0015 | 0.0805 | 0.947 |
| bilinear | 0.0017 | 0.0824 | 0.945 |

(Original field: mean 0.176 mm/day, range 0–2.48 mm/day.) Bias is
essentially zero for all three — the mesh is coarser than ERA5's native grid
(1,867 cells vs. 31,581 grid points inside the same CONUS box), so the round
trip is fundamentally lossy in the same way any downsample-then-upsample is,
but it isn't systematically biased high or low. IDW edges out the other two on
both RMSE and correlation, consistent with it averaging over multiple nearby
source points instead of picking one (nearest neighbor) or interpolating
across a single element (bilinear). The error is not noise — it concentrates
exactly where the physics has sharp spatial gradients (Pacific Northwest
orographic bands, frontal precipitation streaks along the Ohio Valley and
Gulf Coast), and is near zero over smooth, low-gradient areas. See
[`images/roundtrip_bias_all_methods.png`](images/roundtrip_bias_all_methods.png).

## Step 1 — enabling and probing the RODA MCP server

[`awslabs.roda-mcp-server`](https://pypi.org/project/awslabs-roda-mcp-server/)
was installed into an isolated venv and driven directly over MCP stdio
(script: [`scripts/00_roda_exploration.py`](scripts/00_roda_exploration.py)):

```bash
python -m venv /tmp/roda-venv
/tmp/roda-venv/bin/pip install awslabs.roda-mcp-server
```

It exposes 10 tools (FastMCP 4.0.3) for *discovering* and *previewing*
Registry of Open Data listings — it does not do analysis. Two calls mattered
here:

- `get_dataset_details(slug="nsf-ncar-era5")` — returns the dataset's
  metadata: name ("NSF NCAR Curated ECMWF Reanalysis 5 (ERA5)"), the
  documentation DOI (`10.5065/BH6N-5N20`), contact, license, and tags.
- `preview_dataset(slug="nsf-ncar-era5")` — returns up to 10 sample S3 object
  keys and ready-to-run `aws s3 ls` / `aws s3 cp` commands.

First attempt used `identifier` as the argument name (a reasonable guess from
the tool description) and got a Pydantic validation error demanding `slug`
instead — the tool schemas use `slug`, not `identifier` or `dataset_id`. Fixed
by reading the raised error's own field list, not the docs.

**Limitation found and worth documenting**: `preview_dataset`'s 10-object cap
and shallow listing meant it could not by itself reveal the bucket's actual
structure (nine top-level prefixes, dozens of variable codes per prefix). For
that, anonymous direct S3 access was necessary — RODA is a *pointer and
metadata* service, not a data-exploration one. This is an honest limitation
of RODA, not a bug.

## Step 2 — finding the real ERA5 bucket layout

```python
import s3fs
fs = s3fs.S3FileSystem(anon=True)
fs.ls("nsf-ncar-era5")
```

gives 9 top-level prefixes:

```
e5.oper.an.pl            pressure-level analysis
e5.oper.an.sfc           surface analysis (e.g. 2m temperature)
e5.oper.an.vinteg        vertically-integrated analysis
e5.oper.fc.sfc.accumu    forecast-accumulated surface fields (precip lives here)
e5.oper.fc.sfc.instan
e5.oper.fc.sfc.meanflux
e5.oper.fc.sfc.minmax
e5.oper.invariant
index.html
```

There is no standalone total-precipitation (`tp`) file in this bucket's
layout — ERA5 on RODA stores its two additive components separately:

- `128_142_lsp` — large-scale precipitation
- `128_143_cp` — convective precipitation

Total precipitation = `lsp + cp`. This had to be discovered by listing every
file under `e5.oper.fc.sfc.accumu/202001` (76 files, spanning parameter codes
008, 009, 044, 045, 050, 057, 142–147, 169, 175–182, 195–197, 205, 208–213,
239, 240 under GRIB table 128, and 021/022/129/130/251 under table 228) and
recognizing the codes rather than assuming a `tp` file existed.

## Step 3 — the forecast-accumulation semantics

`e5.oper.fc.sfc.accumu` files are dimensioned
`(forecast_initial_time, forecast_hour, latitude, longitude)`.
`forecast_initial_time` alternates 06Z and 18Z each day; `forecast_hour`
runs 1–12 as a **cumulative** accumulation from the start of that 12-hour
forecast window. `forecast_hour=12` (index 11) is the full 12h total for that
run. A calendar day's total precipitation is therefore the sum of that day's
06Z-run total and 18Z-run total — not a naive sum over all `forecast_hour`
values, and not a single-run value.

This was reverse-engineered from the file's own coordinate values and
variable attributes (`.venv/bin/python` inspection of the downloaded files),
not assumed. Getting it wrong (e.g. treating each `forecast_hour` slice as an
independent hourly value) would silently overcount by roughly 12x.

Grid resolution: 721 × 1440 (0.25° global lat-lon), CF-1.6 NetCDF4.

## Step 4 — building the ERA5 CONUS mean-precip field

Downloaded the two half-month files directly (`fsspec`/`s3fs` `.get()`) rather
than reading them lazily over the network:

```
e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.2020010106_2020011606.nc  (269 MB)
e5.oper.fc.sfc.accumu.128_143_cp.ll025sc.2020010106_2020011606.nc   (245 MB)
```

**Performance finding worth keeping**: a partial/lazy read via
`s3fs.open()` + `xarray.open_dataset(engine="h5netcdf")` works fine for
metadata and single-timestep slices (~20–26 s per call, dominated by
per-request overhead, not payload size) but does not scale to a full-month
time-mean reduction over the network — that approach was tried first and hit
a 300 s internal timeout. Downloading the full files locally (30 s each) and
reducing them with local xarray was both simpler and faster overall. This is
the kind of thing that is easy to get backwards by assuming "lazy is always
better," and it wasn't checked by intuition — it was timed.

Processing script:
[`scripts/01_build_era5_conus_field.py`](scripts/01_build_era5_conus_field.py).
It selects `forecast_hour=12` from both `lsp` and `cp`, sums them per
forecast run, pairs 06Z+18Z runs into 15 daily totals, and averages those into
one mean-daily-precip field over a CONUS bounding box
(20–50°N, 130–65°W), producing
[`data/era5_conus_mean_precip.nc`](data/era5_conus_mean_precip.nc) — a
121×261 = 31,581-cell field, mean 0.176 mm/day, range 0–2.48 mm/day for
mid-January CONUS — physically sensible winter values.

Rendered directly (matplotlib `pcolormesh`, no mesh library involved) as
[`images/era5_original_conus.png`](images/era5_original_conus.png).

## Step 5 — making the structured field a real UXarray `Grid`

`uxarray.Grid.from_structured()` converts a CF-compliant rectilinear
`xarray.Dataset` into a genuine UXarray unstructured `Grid` — one quad face
per lat-lon cell. `ux.open_dataset()` auto-detects this path via
`_is_structured()` in `uxarray/io/utils.py`, but that detector specifically
requires the lat/lon coordinate variables to carry CF `standard_name`
attributes (`"latitude"` / `"longitude"`). The field built in Step 4
initially lacked those attributes and failed detection with

```
GridInvalidError: Failed to parse uxgrid information from xarray.Dataset.
```

Fix: add `standard_name` to both coordinate definitions in the processing
script. Rerunning produced identical numeric output (confirming the fix
didn't touch the science) and let `ux.open_dataset()` succeed, reporting
`Original Grid Type: Structured` with `n_face=31581` — exactly the 121×261
grid. This is the mechanism that makes "structured mesh" a literal fact
inside UXarray's own type system for this case study, not a metaphor.

## Step 6 — the target unstructured mesh

Used the real ne30pg3 cubed-sphere test fixture already present in this repo
tree (`outputs/papers/agu/uxarray-paper/artifacts/cza_paper/_tests_local/meshfiles/esmf/ne30/ne30pg3.grid.nc`,
ESMF format, global, n_face=48600), subset to the same CONUS bounding box via
`run_analysis(operation="subset_bbox", lon_bounds=[-130,-65], lat_bounds=[20,50])`,
giving 1,867 faces / 1,970 nodes / 3,836 edges — saved as
[`data/ne30pg3_conus.nc`](data/ne30pg3_conus.nc).

**API quirk found**: `subset_bbox`'s `output_path` argument was silently
ignored — no file appeared. Fix: use the returned `result_handle` with a
separate `run_analysis(operation="export", result_handle=..., output_format="netcdf")`
call, which did write the file correctly. Worth fixing in the MCP server, not
worked around by pretending it isn't there.

Mesh geometry (visibly a cubed-sphere panel, not a lat-lon grid — note the
diamond-shaped cell distortion near panel seams):
[`images/ne30pg3_conus_mesh_wireframe.png`](images/ne30pg3_conus_mesh_wireframe.png).

## Step 7 — the remap round trip, and a real UXarray bug found along the way

Attempted first via the MCP server's own wrapper:

```python
run_analysis(
    operation="remap_variable",
    grid_path="era5_conus_mean_precip.nc",
    data_path="era5_conus_mean_precip.nc",
    variable_name="precip_mm_day",
    target_grid_path="ne30pg3_conus.nc",
    method="nearest_neighbor",
)
```

This failed with:

```
ValueError: cannot set or update variable(s) 'latitude', 'longitude', which would
corrupt the following index built from coordinates 'n_face', 'latitude', 'longitude':
PandasIndex(MultiIndex(...), name='n_face', length=1867))
```

Bypassing the wrapper and calling UXarray's own `.remap.nearest_neighbor()`
accessor directly reproduced the *identical* error — so this is a UXarray
library issue, not an MCP-server-only bug. Root cause, traced into
`uxarray/remap/spatial_coords_remap.py` and `uxarray/remap/utils.py`:

- `Grid.from_structured()` keeps the original `(latitude, longitude)` pairs
  as a `pandas.MultiIndex` on the `n_face` dimension, so the structured shape
  can in principle be recovered later.
- UXarray's `nearest_neighbor` remap selects the nearest *source* point for
  each destination face, which naturally carries that MultiIndex along,
  reindexed to the destination's face count (1,867 source-side `(lat, lon)`
  pairs, one per destination face).
- `_construct_remapped_ds` / `SpatialCoordsRemapper.construct_output_coords()`
  then tries to overwrite `latitude`/`longitude` with the *destination
  grid's own* `face_lat`/`face_lon` values — and xarray correctly refuses,
  because those names are still index levels of the leftover MultiIndex, not
  plain coordinates.

**Workaround** (confirmed not to lose information needed downstream):
`data_array.reset_index("n_face")` before remapping. This drops the
`MultiIndex` but keeps `latitude`/`longitude` as ordinary (non-index)
coordinate arrays of the same values, and leaves `.uxgrid` untouched. After
that one line, all three remap methods ran cleanly. See
[`scripts/02_remap_roundtrip.py`](scripts/02_remap_roundtrip.py) for the
exact fix and full round-trip pipeline.

This looks like a genuine UXarray defect worth reporting upstream: any
dataset produced by `Grid.from_structured()` cannot be remapped via
`nearest_neighbor`, `inverse_distance_weighted`, or `bilinear` without this
manual `reset_index` step first, and the error message gives no hint that a
`Grid.from_structured` MultiIndex is the cause.

**Also confirmed unavailable in this environment**: the YAC backend
(`conservative`, `nnn`, `dnn`, `average` remap methods) — `import yac` raises
`ModuleNotFoundError`. Only the three native UXarray-engine methods
(`nearest_neighbor`, `inverse_distance_weighted`, `bilinear`) were used here;
conservative remapping (which would additionally guarantee the areal
integral is preserved) was not tested and is a natural follow-up once YAC is
installed.

## Step 8 — forward remap and round trip

For each of `nearest_neighbor`, `inverse_distance_weighted`, `bilinear`:

1. **Forward**: `era5_precip.remap.<method>(target_grid=ne30pg3_conus)` —
   ERA5's 31,581-face structured field onto the 1,867-face unstructured mesh.
   Saved as `data/forward_<method>.nc`.
2. **Backward**: `forward_field.remap.to_rectilinear(lon=era5_lon, lat=era5_lat)`
   — the unstructured-mesh field interpolated back onto ERA5's *exact*
   original 0.25° lat/lon points.
3. **Compare**: round-tripped field vs. the original ERA5 field, at every
   point (bias, RMSE, Pearson correlation) — numbers in the Summary table
   above, full detail in
   [`data/remap_fidelity_results.json`](data/remap_fidelity_results.json).

The forward-remapped field on the actual unstructured mesh (IDW shown; the
other two look visually similar at this resolution):
[`images/remap_idw_on_ne30pg3_mesh.png`](images/remap_idw_on_ne30pg3_mesh.png).

## Reproducing this

The two 500 MB raw ERA5 files are not stored in this repo (kept in `/tmp`
during this analysis); everything from Step 4 onward that fits comfortably
in git is under `data/`. To rerun from scratch:

```bash
# Step 4 inputs — download from s3://nsf-ncar-era5 (anonymous, us-west-2):
#   e5.oper.fc.sfc.accumu/202001/e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.2020010106_2020011606.nc
#   e5.oper.fc.sfc.accumu/202001/e5.oper.fc.sfc.accumu.128_143_cp.ll025sc.2020010106_2020011606.nc
python scripts/01_build_era5_conus_field.py   # -> data/era5_conus_mean_precip.nc
python scripts/02_remap_roundtrip.py          # -> data/forward_*.nc, data/remap_fidelity_results.json
python scripts/03_plots.py                    # -> images/*.png
```

(Paths inside the scripts point at `/tmp/era5_raw` as originally run — adjust
to wherever the raw files land before rerunning.)

## Honest limitations

- Only 15 days of data (2020-01-01 to 2020-01-15), not a full climatology —
  chosen to keep the round-trip experiment fast, not to cherry-pick a result.
- Conservative (YAC-backed) remapping was not tested — YAC isn't installed
  in this environment. Areal-integral preservation, which conservative remap
  specifically guarantees and the three tested methods don't, is therefore
  an open question here.
- "Round-trip fidelity" measures self-consistency (does the field survive an
  onto-mesh-and-back trip), not the physical accuracy of the mesh-based
  representation against any independent observation. No independent
  unstructured-mesh measurement of the same field exists to validate against.
- The remap-wrapper `MultiIndex` issue was traced to UXarray's own remap
  internals by reading the source, not by an upstream maintainer confirming
  it — worth filing as an issue for anyone who wants to remap
  `Grid.from_structured` output, but not yet reported upstream from this
  session.
