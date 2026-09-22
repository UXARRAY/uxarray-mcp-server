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
back onto ERA5's original 0.25° grid using six remap methods — three native
to UXarray's own engine, and three routed through YAC (DKRZ's coupling
library) once it was built for this environment (see Step 7a). All six
reproduce the original field closely:

| method | backend | bias (mm/day) | RMSE (mm/day) | pattern correlation |
|---|---|---|---|---|
| nearest_neighbor | uxarray | 0.0015 | 0.0861 | 0.941 |
| inverse_distance_weighted | uxarray | 0.0015 | 0.0805 | 0.947 |
| bilinear | uxarray | 0.0017 | 0.0824 | 0.945 |
| conservative | YAC | 0.0008 | 0.0753 | 0.953 |
| nnn (nearest-neighbor) | YAC | 0.0015 | 0.0861 | 0.941 |
| average | YAC | 0.0016 | 0.0835 | 0.943 |

(Original field: mean 0.176 mm/day, range 0–2.48 mm/day.)

**The headline: conservative remapping measurably wins — on this kind of
field.** YAC's conservative method is the best of all six on every metric
here: 12.5% lower RMSE and 43% lower bias than nearest neighbour, and the
highest pattern correlation. It is also the only method that nearly halves
the drift in the field's own mean.

The qualifier is earned rather than defensive. A later sweep of all seven
methods on Chrysalis (HEALPix z4 -> z2) found conservative sitting *mid-pack*
on a smooth analytic field — `dnn` .062%, `average` .070%, IDW .075%,
bilinear .083%, conservative .095% — and winning decisively on a
discontinuity: conservative .416% against IDW's 1.49% and nearest
neighbour's 7.14%. Precipitation is the discontinuous case. It is patchy,
bounded below by zero, and organised into fronts and orographic bands, which
is exactly where smearing a flux across a cell boundary costs you. A smooth
test field would have ranked these methods differently and misled anyone who
took the ranking at face value:

| method | round-trip drift in CONUS mean precip |
|---|---:|
| **conservative** (YAC) | **+0.48%** |
| nearest_neighbor / nnn | +0.83% |
| inverse_distance_weighted | +0.87% |
| average (YAC) | +0.92% |
| bilinear | +0.97% |

That is the result to take away for anyone remapping a flux: precipitation is
an areal quantity, and only the conservative method is built to preserve its
integral rather than sample point values. The other five are not wrong, they
are answering a slightly different question, and the 2× difference in mean
drift is the size of the gap that opens between those two questions on a real
field. It is also a concrete argument for paying the Step 7a build cost —
that method is the one you cannot get without it.

Two supporting observations. UXarray's own IDW is the best of the three
non-conservative methods, since it averages over several nearby source points
rather than picking one (nearest neighbour) or interpolating within a single
element (bilinear). And YAC's `nnn` and UXarray's `nearest_neighbor` agree to
eight significant figures (RMSE 0.086061075 both ways) — two independent
implementations, one written in C and reached through MPI, the other in
Python, landing on the same answer. Nothing forced that agreement, so it is a
genuine cross-check on both.

Bias is small for all six: the mesh is coarser than ERA5's native grid (1,867
cells vs. 31,581 grid points in the same CONUS box), so the round trip is
lossy the way any downsample-then-upsample is, but not systematically high or
low. The residual error is not noise — it concentrates exactly where the
physics has sharp spatial gradients (Pacific Northwest orographic bands,
frontal precipitation streaks along the Ohio Valley and Gulf Coast), and is
near zero over smooth areas. See
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

## Step 7a — getting YAC working

**Why bother:** YAC's conservative remap turned out to be the most accurate
of the six methods tested — 12.5% lower RMSE and 43% lower bias than nearest
neighbour, and the only method that keeps the field's areal integral. It is
also the only one of the six that is not available out of the box. Getting it
built is what made that comparison possible at all, and the steps below are
now automated in
[`scripts/build_yac_local.sh`](../../scripts/build_yac_local.sh) so nobody
has to rediscover them.

`import yac` raised `ModuleNotFoundError` in this project's own `.venv`
(the one this whole case study otherwise runs in). YAC is not a
pip-installable wheel: its Python bindings are Cython-generated and built
from source against
[YAC's own DKRZ GitLab repo](https://gitlab.dkrz.de/dkrz-sw/yac), and YAC in
turn hard-depends on
[libyaxt](https://gitlab.dkrz.de/dkrz-sw/yaxt) ("Yet Another eXchange
Tool"), DKRZ's own MPI data-exchange library, which is itself a from-source
autotools build with no matching prebuilt wheel for an arbitrary local MPI.
Neither `yac` nor `yaxt` exists on conda-forge as an ARM-macOS build that
matches this machine's Homebrew Open MPI 5.0.10 exactly.

An initial attempt to build YAC directly in `.venv` (`uv pip install
git+https://gitlab.dkrz.de/dkrz-sw/yac.git`, after installing `cython` and
an `mpi4py` built against the same Homebrew Open MPI) got as far as YAC's
own CMake configure step — it correctly found and validated Open MPI — before
failing with:

```
CMake Error: Could NOT find yaxt (missing: YAXT_C_LIBRARY YAXT_C_INCLUDE_DIR)
```

So YAXT was built from source first:

```bash
git clone --depth 1 https://gitlab.dkrz.de/dkrz-sw/yaxt.git
cd yaxt && autoreconf -fi && mkdir build && cd build
../configure --prefix=/Users/mbook/opt/yaxt-local CC=mpicc FC=mpifort
make -j8 && make install
```

`make` failed on every shared-library link with `ld: unknown option:
-no_fixup_chains`. Root cause: Homebrew GCC 16.2's Fortran driver
unconditionally bakes `-Wl,-no_fixup_chains` into the generated `libtool`
script's `allow_undefined_flag` (a historical workaround for a Big Sur
ARM64 code-signing bug), but the Xcode `ld` on this machine no longer
recognizes that flag at all. Passing `LDFLAGS="-Wl,-ld_classic"` at
configure time does not fix this cleanly — it fixes the C-link case but
breaks Fortran's own configure-time link test with a different error
(`ld: library not found for -ld_classic`), since `mpifort`/`collect2`
handles that flag differently than `mpicc` does. The actual fix was to
patch the two `allow_undefined_flag` lines directly out of the *generated*
`libtool` script after configuring (removing the literal
`\$wl-no_fixup_chains` substring), then run `make` again — which then
built and installed cleanly to `/Users/mbook/opt/yaxt-local`.

With YAXT built, YAC's own CMake configure needed one more nudge: passing
`-DYAXT_ROOT=...` alone is silently ignored by CMake's `find_package`
unless policy `CMP0144` is set to `NEW` (CMake warns about this but still
fails the `find_package` under the old default). The working build:

```bash
CMAKE_ARGS="-DYAXT_ROOT=/Users/mbook/opt/yaxt-local -DCMAKE_POLICY_DEFAULT_CMP0144=NEW" \
    uv pip install --python .venv/bin/python "git+https://gitlab.dkrz.de/dkrz-sw/yac.git"
```

This installed YAC 3.21.0 straight into this project's own `.venv`.
`otool -L` on the compiled extension confirms it links against the
just-built `/Users/mbook/opt/yaxt-local/lib/libyaxt_c.1.dylib` and the
*same* Homebrew Open MPI (`/opt/homebrew/opt/open-mpi/lib/libmpi.40.dylib`)
that `mpi4py`/UXarray use in-process in this `.venv` — that MPI match is
what makes it usable at all; a YAC build against a different MPI than the
one `mpi4py` uses would not link correctly. All three YAC remap methods
(`conservative`, `nnn`, `average`) ran cleanly from this project's own
`.venv` interpreter (`dnn` was not tried). See
[`scripts/04_yac_conservative_remap.py`](scripts/04_yac_conservative_remap.py).

Net result: the MCP server's own `.venv` can now use the YAC backend
directly — no separate conda environment needed. A future YAC-backed
`run_analysis` call through the MCP tool has everything it needs already
installed in this project's environment.

Both fixes are now in `scripts/build_yac_local.sh` rather than only in this
write-up: the generated `libtool` is patched automatically, guarded so it is
a no-op on toolchains that never had the problem. The one-time cost of
working this out buys the conservative remap for everyone who runs that
script — which, on the evidence in Step 8, is the method worth having.

## Step 8 — forward remap and round trip

For each of `nearest_neighbor`, `inverse_distance_weighted`, `bilinear`
(UXarray-native) and `conservative`, `nnn`, `average` (YAC-backed):

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

The forward-remapped field on the actual unstructured mesh (YAC conservative
shown, since it's the best-scoring method; the other five look visually
similar at this resolution):
[`images/remap_yac_conservative_on_ne30pg3_mesh.png`](images/remap_yac_conservative_on_ne30pg3_mesh.png).

All map images in this case study carry real Cartopy coastlines and
US state/country borders (Natural Earth, 50 m resolution) — the mesh
wireframe via the MCP server's own `plot_type="mesh_geo"` tool, and the two
choropleths (original ERA5 field, remapped-on-mesh field) via UXarray's
`uxda.plot.polygons(projection=ccrs.PlateCarree())`, since the MCP server's
`plot_type="variable"` tool
(`src/uxarray_mcp/domain/plotting.py::render_variable()`) has no
projection/Cartopy support at all — a real gap in that tool, worked around
here by calling UXarray's plotting API directly and adding the coastlines to
the resulting `cartopy.mpl.geoaxes.GeoAxes` by hand. See
[`scripts/05_plot_remap_on_mesh.py`](scripts/05_plot_remap_on_mesh.py) for
the exact technique.

## Reproducing this

Every intermediate small enough for git is committed under `data/`, so the
interesting half runs from a fresh clone with no download and no AWS
account. Run from the `scripts/` directory, using the project `.venv`:

```bash
cd case-studies/era5-structured-unstructured-remap/scripts

python 02_remap_roundtrip.py   # -> data/forward_*.nc, data/remap_fidelity_results.json
python 03_plots.py             # -> images/era5_original_conus.png, images/roundtrip_bias_all_methods.png
python 05_plot_remap_on_mesh.py  # -> images/remap_yac_conservative_on_ne30pg3_mesh.png
```

Verified on 2026-09-19 from the committed inputs: `02` reproduced all three
uxarray methods' fidelity numbers **bit-identically** to the committed
`remap_fidelity_results.json`, and `03`/`05` reproduced
`era5_original_conus.png` and
`remap_yac_conservative_on_ne30pg3_mesh.png` **byte-identically** to the
committed PNGs.

To go further back, or to rebuild the source field yourself:

```bash
uv pip install s3fs
python 00_download_era5.py                # -> raw/*.nc, ~1 GB from s3://nsf-ncar-era5
python 01_build_era5_conus_field.py       # -> data/era5_conus_mean_precip.nc
python 04_yac_conservative_remap.py       # -> adds the three yac_* entries
```

`04` needs a from-source YAC+YAXT build in the project `.venv` — see Step 7a.
Without it, `03` prints which methods it is skipping and draws the
three-method figure instead of the six-method one, rather than failing.

Paths resolve relative to the case-study directory, so no editing is needed;
set `ERA5_CASE_STUDY_DIR` to run against a scratch directory instead. (The
scripts originally hardcoded `/tmp/era5_raw`, which is where the analysis
really ran and which reproduced nowhere else — `scripts/paths.py` is the fix.)

The mesh wireframe, `images/ne30pg3_conus_mesh_wireframe.png`, came from the
MCP tool `plot_dataset(plot_type="mesh_geo", grid_path=...,
lon_bounds=[-130,-65], lat_bounds=[20,50], show_mesh_boundary=true)`, not a
script.

## Honest limitations

- Only 15 days of data (2020-01-01 to 2020-01-15), not a full climatology —
  chosen to keep the round-trip experiment fast, not to cherry-pick a result.
- The YAC results here come from YAC 3.21.0 + YAXT 0.12.1, both built from
  source directly into this project's own `.venv` and linked against the
  same Homebrew Open MPI the rest of the case study uses — see Step 7a for
  the exact build steps (including the libtool/`-no_fixup_chains` linker
  patch this required on this machine's toolchain).
- `dnn` (YAC's fourth remap method) was not tried, only `conservative`, `nnn`,
  `average`.
- "Round-trip fidelity" measures self-consistency (does the field survive an
  onto-mesh-and-back trip), not the physical accuracy of the mesh-based
  representation against any independent observation. No independent
  unstructured-mesh measurement of the same field exists to validate against.
- The remap-wrapper `MultiIndex` issue was traced to UXarray's own remap
  internals by reading the source, not by an upstream maintainer confirming
  it — worth filing as an issue for anyone who wants to remap
  `Grid.from_structured` output, but not yet reported upstream from this
  session.
