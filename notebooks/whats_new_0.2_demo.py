# %% [markdown]
# # uxarray-mcp 0.1.2 — What's New (Visual Demo)
#
# A single, self-contained, **plot-rich** tour of everything in the two recent
# changes:
#
# - **PR #64 (Peng / toolregistry-server 0.4.0)** — the new `App` /
#   `ServerIdentity` foundation and the brand-new **OpenAPI / REST** surface
#   (`uxarray-mcp openapi`). `server.py` is gone; `make_registry` and
#   `make_mcp_server` now live in `uxarray_mcp.app`.
# - **PR #65 (post-toolregistry follow-ups)** — UXarray **2026.6.0** plus a
#   batch of new `run_analysis` operations (vector calculus, model
#   verification, climatology/anomaly, rectilinear remap, zonal anomaly) and
#   four new guided **science-workflow prompts**.
#
# This notebook is **deterministic** — it drives the same functions an MCP/AI
# client calls, directly from Python. No LLM, no gateway, no MCP transport
# required. Every scientific result below is also **plotted inline**.

# %%
import base64
import io
import json
import os
import tempfile

import matplotlib

matplotlib.use("Agg")  # render figures to PNG bytes; we display them explicitly
import matplotlib.pyplot as plt
import numpy as np
import uxarray as ux
import xarray as xr
from IPython.display import Image, display

import uxarray_mcp

plt.rcParams["figure.dpi"] = 110
print("uxarray-mcp :", uxarray_mcp.__version__)
print("uxarray     :", ux.__version__)


def show(title, result, drop=("_provenance",)):
    """Compact JSON view of a tool result, hiding noisy keys."""
    print(f"=== {title} ===")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in drop}, indent=2, default=str
        )
    )
    print()


def show_png(items, caption=None):
    """Decode + display the base64 PNG returned by a plotting tool."""
    png = base64.b64decode(items[0].data)
    if caption:
        print(f"{caption}  ({len(png):,} bytes)")
    display(Image(data=png))


def show_fig(fig):
    """Render a matplotlib figure to PNG and display it inline (deterministic)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    display(Image(data=buf.getvalue()))


# %% [markdown]
# ## 0. Synthesize a realistic mesh + data
#
# No sample data ships with the repo, so we build a global structured→
# unstructured UGRID mesh (5° resolution) and put a **physically-suggestive**
# field on it: a warm tropics that cools toward the poles, with a zonal wave —
# so the science plots below actually look like atmospheric fields. We also
# create a model/obs pair and a 24-step time series.

# %%
work = tempfile.mkdtemp(prefix="uxmcp_demo_")
GRID = os.path.join(work, "grid.nc")
DATA = os.path.join(work, "data.nc")
MODEL = os.path.join(work, "model.nc")
OBS = os.path.join(work, "obs.nc")
TS = os.path.join(work, "timeseries.nc")

lon = np.arange(0, 360, 5.0)
lat = np.arange(-87.5, 88, 5.0)
grid = ux.Grid.from_structured(lon=lon, lat=lat)
grid.to_xarray().to_netcdf(GRID)
n = grid.n_face

flon = np.asarray(grid.face_lon)
flat = np.asarray(grid.face_lat)

# Temperature: warm equator, cool poles, + a zonal wave-3 pattern
temperature = (
    300 - 40 * np.sin(np.radians(flat)) ** 2 + 5 * np.cos(np.radians(3 * flon))
)
# Wind: westerlies that vary with latitude + a meridional wave
u_wind = 20 * np.cos(np.radians(flat)) + 5 * np.sin(np.radians(2 * flon))
v_wind = 8 * np.sin(np.radians(2 * flat)) * np.cos(np.radians(flon))

xr.Dataset(
    {
        "temperature": (["n_face"], temperature),
        "u": (["n_face"], u_wind),
        "v": (["n_face"], v_wind),
    }
).to_netcdf(DATA)

rng = np.random.default_rng(0)
# Model = truth + small noise; Obs = truth (so metrics are meaningful)
xr.Dataset({"temperature": (["n_face"], temperature + rng.normal(0, 2, n))}).to_netcdf(
    MODEL
)
xr.Dataset({"temperature": (["n_face"], temperature)}).to_netcdf(OBS)

nt = 24
t = np.arange(nt)
series = (
    temperature[None, :]
    + 10 * np.sin(2 * np.pi * t / 12)[:, None]
    + rng.normal(0, 1, (nt, n))
)
xr.Dataset({"temperature": (["time", "n_face"], series)}, coords={"time": t}).to_netcdf(
    TS
)

print(f"mesh: {n} faces @ 5deg | model/obs pair | {nt}-step time series")

# %% [markdown]
# ---
# # Part 1 — PR #64: the `App` / `ServerIdentity` foundation
#
# Peng's 0.4.0 refactor consolidated all server wiring into `uxarray_mcp.app`.
# One `ServerIdentity` drives the MCP server name, the OpenAPI title, and the
# CLI banner. The same tool surface can now be served over **MCP *or*
# OpenAPI/REST** — that REST surface is the headline new capability.

# %%
from uxarray_mcp.app import UXARRAY_IDENTITY, UXarrayApp, make_mcp_server, make_registry

print("identity   :", UXARRAY_IDENTITY.name, "v" + UXARRAY_IDENTITY.version)
print("description:", UXARRAY_IDENTITY.description)

reg = make_registry(profile="core")
print(f"\ncore profile exposes {len(reg.list_tools())} tools")

server = make_mcp_server(profile="core")
print("MCP server name:", server.name)

app = UXarrayApp()
print("App serve methods:", [m for m in dir(app) if m.startswith("serve")])
print(
    "\nDeployment (these block, so not called here):\n"
    "  uxarray-mcp serve   --transport stdio          # MCP (Claude Desktop)\n"
    "  uxarray-mcp serve   --transport streamable-http # remote MCP\n"
    "  uxarray-mcp openapi --port 8000                # NEW: REST / OpenAPI"
)

# %% [markdown]
# ## 1.1 The tool surface, visualized
#
# A quick bar chart of how the `core` and `deferred-full` profiles break down.

# %%
core_tools = make_registry(profile="core").list_tools()
full = make_registry(profile="deferred-full")
full_tools = full.list_tools()

# group core tools by namespace prefix
groups: dict[str, int] = {}
for tname in core_tools:
    ns = (
        tname.split("-")[0].split("/")[0]
        if any(s in tname for s in ("-", "/"))
        else "front-door"
    )
    ns = ns if ns in ("session", "hpc", "io", "prompt") else "front-door"
    groups[ns] = groups.get(ns, 0) + 1

fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.4))
a1.bar(list(groups), list(groups.values()), color="#4c78a8")
a1.set_title(f"core profile = {len(core_tools)} visible tools")
a1.tick_params(axis="x", rotation=20)
a2.bar(
    ["core\n(visible)", "deferred-full\n(loaded)"],
    [len(core_tools), len(full_tools)],
    color=["#4c78a8", "#f58518"],
)
a2.set_title("profiles: small surface, big toolbox")
for i, vv in enumerate([len(core_tools), len(full_tools)]):
    a2.text(i, vv + 0.5, str(vv), ha="center")
fig.tight_layout()
show_fig(fig)

# %% [markdown]
# ## 1.2 Simulating a REST request — no AI, no HTTP server
#
# The OpenAPI front end receives JSON, looks up the tool, calls it. Here is
# that exact flow — swap `incoming` for an HTTP body and you have the
# `uxarray-mcp openapi` surface.

# %%
incoming = {
    "tool": "run_analysis",
    "args": {"operation": "calculate_area", "grid_path": GRID},
}
response = reg.get_callable(incoming["tool"])(**incoming["args"])
show("REST-style run_analysis(calculate_area)", response)

# %% [markdown]
# ---
# # Part 2 — PR #65: new `run_analysis` operations, plotted
#
# Every new computation is reachable through the single front-door
# `run_analysis(operation=..., ...)` dispatcher. Below, each result is shown
# *and* visualized. For mesh maps of derived fields we render through the
# package's own `plot_dataset` tool (the same base64-PNG path MCP/REST use).

# %%
run_analysis = reg.get_callable("run_analysis")
plot_dataset = reg.get_callable("plot_dataset")
uxds = ux.open_dataset(GRID, DATA)  # for extracting derived fields to map


def map_field(values, name, cmap="viridis", caption=None):
    """Write a face-centered field to disk and render it via plot_dataset."""
    path = os.path.join(work, f"{name}.nc")
    xr.Dataset({name: (["n_face"], np.asarray(values))}).to_netcdf(path)
    items = plot_dataset(
        plot_type="variable",
        grid_path=GRID,
        data_path=path,
        variable_name=name,
        cmap=cmap,
    )
    show_png(items, caption or name)


# %% [markdown]
# ### The input field — temperature on the unstructured mesh

# %%
show_png(
    plot_dataset(
        plot_type="variable",
        grid_path=GRID,
        data_path=DATA,
        variable_name="temperature",
        cmap="RdYlBu_r",
    ),
    "temperature (input field)",
)

# %% [markdown]
# ## 2.1 Vector calculus — gradient magnitude
#
# Green-Gauss finite-volume gradient. We map the **magnitude** of the gradient
# (where the field changes fastest — fronts and edges light up).

# %%
g = run_analysis(
    operation="gradient", grid_path=GRID, data_path=DATA, variable_name="temperature"
)
show("gradient(temperature) — stats", g)

gfield = uxds["temperature"].gradient()
grad_mag = np.hypot(
    np.asarray(gfield["zonal_gradient"].values),
    np.asarray(gfield["meridional_gradient"].values),
)
map_field(
    grad_mag,
    "gradient_magnitude",
    cmap="magma",
    caption="|∇ temperature| — sharp gradients highlighted",
)

# %% [markdown]
# ## 2.2 Curl — relative vorticity of the wind
#
# ζ = ∂v/∂x − ∂u/∂y. Red = cyclonic, blue = anticyclonic.

# %%
c = run_analysis(
    operation="curl", grid_path=GRID, data_path=DATA, u_variable="u", v_variable="v"
)
show("curl / relative vorticity — stats", c)

vort = uxds["u"].curl(uxds["v"])
map_field(
    vort.values,
    "vorticity",
    cmap="RdBu_r",
    caption="relative vorticity ζ = ∂v/∂x − ∂u/∂y",
)

# %% [markdown]
# ## 2.3 Divergence of the wind field
#
# ∂u/∂x + ∂v/∂y — convergence (blue) vs divergence (red).

# %%
d = run_analysis(
    operation="divergence",
    grid_path=GRID,
    data_path=DATA,
    u_variable="u",
    v_variable="v",
)
show("divergence — stats", d)

div = uxds["u"].divergence(uxds["v"]) if hasattr(uxds["u"], "divergence") else None
if div is not None:
    map_field(
        div.values, "divergence", cmap="PuOr_r", caption="wind divergence ∂u/∂x + ∂v/∂y"
    )

# %% [markdown]
# ## 2.4 Azimuthal mean — radial profile about a point
#
# Great-circle-distance rings about `(center_lon, center_lat)` — the heart of
# the cyclone-structure workflow (radius of max wind, etc).

# %%
az = run_analysis(
    operation="azimuthal_mean",
    grid_path=GRID,
    data_path=DATA,
    variable_name="temperature",
    center_lon=0.0,
    center_lat=0.0,
    outer_radius=60.0,
    radius_step=2.0,
)

fig, ax = plt.subplots(figsize=(7, 3.6))
ax.plot(az["radii_deg"], az["azimuthal_mean_values"], "-o", ms=3, color="#e45756")
ax.set_xlabel("radius from center (deg)")
ax.set_ylabel("temperature (K)")
ax.set_title("Azimuthal mean profile about (0°, 0°)")
ax.grid(alpha=0.3)
fig.tight_layout()
show_fig(fig)

# %% [markdown]
# ## 2.5 Zonal anomaly — departure from the latitude-band mean
#
# Per-face value minus the zonal mean of its latitude band — the eddy / wave
# field used in storm-track diagnostics.

# %%
za = run_analysis(
    operation="zonal_anomaly",
    grid_path=GRID,
    data_path=DATA,
    variable_name="temperature",
)
show("zonal_anomaly — stats", za)

anom_field = uxds["temperature"].zonal_anomaly()
map_field(
    anom_field.values,
    "zonal_anomaly",
    cmap="coolwarm",
    caption="temperature − zonal mean (wave structure)",
)

# %% [markdown]
# ## 2.6 Model verification — bias, RMSE, pattern correlation
#
# Compare two fields on the same grid (model vs observations).

# %%
metrics = {}
for op in ("bias", "rmse", "pattern_correlation"):
    r = run_analysis(
        operation=op,
        grid_path=GRID,
        data_path_a=MODEL,
        data_path_b=OBS,
        variable_name="temperature",
    )
    metrics[op] = r[op]
print(json.dumps(metrics, indent=2))

fig, ax = plt.subplots(figsize=(6, 3.4))
bars = ax.bar(
    list(metrics), list(metrics.values()), color=["#d62728", "#ff7f0e", "#2ca02c"]
)
ax.set_title("Model vs Obs verification")
ax.axhline(0, color="k", lw=0.6)
for b, v in zip(bars, metrics.values()):
    ax.text(
        b.get_x() + b.get_width() / 2,
        v,
        f"{v:.3f}",
        ha="center",
        va="bottom" if v >= 0 else "top",
    )
fig.tight_layout()
show_fig(fig)

# %% [markdown]
# ## 2.7 Climatology + anomaly — needs a time dimension
#
# `temporal_mean` collapses the time axis; `anomaly` subtracts that
# climatology. We plot the domain-mean time series with the climatology line.

# %%
tm = run_analysis(operation="temporal_mean", data_path=TS, variable_name="temperature")
an = run_analysis(operation="anomaly", data_path=TS, variable_name="temperature")
print("temporal_mean summary:", json.dumps(tm["summary"], indent=2, default=str))

ts_da = xr.open_dataset(TS)["temperature"]
domain_mean = ts_da.mean("n_face").values
clim = float(np.mean(domain_mean))

fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.4))
a1.plot(t, domain_mean, "-o", ms=3, label="domain-mean T")
a1.axhline(clim, color="#d62728", ls="--", label=f"climatology = {clim:.1f} K")
a1.set_title("temporal_mean: time series vs climatology")
a1.set_xlabel("time step")
a1.set_ylabel("K")
a1.legend()
a1.grid(alpha=0.3)

a2.bar(
    t, domain_mean - clim, color=np.where(domain_mean - clim >= 0, "#d62728", "#1f77b4")
)
a2.axhline(0, color="k", lw=0.6)
a2.set_title("anomaly: departure from climatology")
a2.set_xlabel("time step")
a2.set_ylabel("K")
fig.tight_layout()
show_fig(fig)

# %% [markdown]
# ## 2.8 Remap to a rectilinear lon/lat grid
#
# Resample the unstructured field onto a regular grid (handy for tools that
# expect structured data). We show the result as a clean heatmap.

# %%
target_lon = np.arange(0, 360, 5.0)
target_lat = np.arange(-90, 91, 5.0)
rr = run_analysis(
    operation="remap_to_rectilinear",
    grid_path=GRID,
    data_path=DATA,
    variable_name="temperature",
    target_lon=list(target_lon),
    target_lat=list(target_lat),
)
show("remap_to_rectilinear — stats", rr)

# Reproduce the regular grid for display
da = ux.open_dataset(GRID, DATA)["temperature"]
rect = da.remap.to_rectilinear(lon=target_lon, lat=target_lat)
fig, ax = plt.subplots(figsize=(8, 3.6))
im = ax.pcolormesh(
    target_lon, target_lat, np.asarray(rect.values), cmap="RdYlBu_r", shading="auto"
)
ax.set_title(f"remapped to rectilinear {rr['target_shape']}")
ax.set_xlabel("lon")
ax.set_ylabel("lat")
fig.colorbar(im, ax=ax, label="K")
fig.tight_layout()
show_fig(fig)

# %% [markdown]
# ## 2.9 Zonal mean profile — through the plotting tool
#
# The package renders this directly as a base64 PNG.

# %%
show_png(
    plot_dataset(
        plot_type="zonal_mean",
        grid_path=GRID,
        data_path=DATA,
        variable_name="temperature",
    ),
    "zonal-mean temperature profile",
)

# %% [markdown]
# ---
# # Part 3 — PR #65: guided science-workflow prompts
#
# These *prompt-as-tool* helpers under the `prompt/` namespace don't compute —
# they return ready-to-run instruction text that chains the operations above
# into a full analysis. An AI agent reads the text and executes the steps.

# %%
from uxarray_mcp.registry import (
    climatology_anomaly,
    cyclone_structure,
    eddy_activity,
    model_evaluation,
)

print(
    cyclone_structure(
        GRID, DATA, "temperature", center_lon=0.0, center_lat=0.0, u_var="u", v_var="v"
    )
)

# %%
print(eddy_activity(GRID, DATA, "temperature"))

# %%
print(model_evaluation(GRID, MODEL, OBS, "temperature"))

# %%
print(climatology_anomaly(DATA, "temperature", grid_path=GRID))

# %% [markdown]
# ---
# # Part 4 — Discovery + policy tags
#
# The `deferred-full` profile loads ~64 tools but exposes only the core set
# (~31 visible); the rest are found via BM25 `discover_tools`. The new ops are
# discoverable.

# %%
discover = full.get_callable("discover_tools")
for q in [
    "compute vorticity wind curl",
    "zonal anomaly eddy departure",
    "compare model and observations bias rmse",
    "remap to a regular lon lat grid",
    "climatology time mean anomaly",
]:
    print(f"\n'{q}'")
    for r in discover(query=q, top_k=3):
        tag = "[deferred]" if r.get("deferred") else "[core]    "
        print(f"  {tag} {r['name']}")

# %%
from toolregistry import ToolTag

safe = make_registry(profile="deferred-full")
safe.disable_by_tags([ToolTag.NETWORK, ToolTag.FILE_SYSTEM])
fig, ax = plt.subplots(figsize=(5.5, 3))
ax.bar(
    ["full", "read-only\nsafe"],
    [len(full.list_tools()), len(safe.list_tools())],
    color=["#54a24b", "#9d755d"],
)
ax.set_title("Policy-tag filtering (network + FS writes off)")
for i, vv in enumerate([len(full.list_tools()), len(safe.list_tools())]):
    ax.text(i, vv + 0.5, str(vv), ha="center")
fig.tight_layout()
show_fig(fig)

# %% [markdown]
# ---
# # Part 5 — Native mesh wireframe
#
# `plot_dataset(plot_type="mesh")` renders the unstructured grid itself.

# %%
show_png(
    plot_dataset(plot_type="mesh", grid_path=GRID, width=720, height=360),
    "mesh wireframe",
)

# %% [markdown]
# ---
# # Part 6 — Running on HPC: Chrysalis (Argonne LCRC)
#
# The same `run_analysis` calls work on a remote HPC cluster — just add
# `use_remote=True, endpoint="chrysalis"`. The data stays on the cluster
# filesystem; only the JSON result comes back. This section runs live against
# the Chrysalis Globus Compute endpoint using real MPAS meshes.

# %%
from uxarray_mcp.tools.frontdoor import diagnose_endpoint

ep = diagnose_endpoint(action="status", endpoint="chrysalis")
ep_info = ep["endpoints"][0]
print(f"endpoint : {ep_info['endpoint_name']}")
print(f"status   : {ep_info['status']}")
print(f"node     : {ep_info['node']}")
print(f"python   : {ep_info['python']}")
print(f"slurm job: {ep_info['slurm_job_id']}")

# %% [markdown]
# ## 6.1 Remote inspect + area on MPAS QU 480km

# %%
import time as _time

MPAS_GRID = "/home/jain/uxarray/test/meshfiles/mpas/QU/480/grid.nc"
MPAS_DATA = "/home/jain/uxarray/test/meshfiles/mpas/QU/480/data.nc"

t0 = _time.time()
mesh = run_analysis(
    operation="inspect_mesh", grid_path=MPAS_GRID, use_remote=True, endpoint="chrysalis"
)
show(f"remote inspect_mesh ({_time.time() - t0:.1f}s)", mesh)

t0 = _time.time()
area = run_analysis(
    operation="calculate_area",
    grid_path=MPAS_GRID,
    use_remote=True,
    endpoint="chrysalis",
)
show(f"remote calculate_area ({_time.time() - t0:.1f}s)", area)

# %% [markdown]
# ## 6.2 Remote vector calculus on MPAS dyamond-30km

# %%
DYA_GRID = "/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_grid_subset.nc"
DYA_DATA = "/home/jain/uxarray/test/meshfiles/mpas/dyamond-30km/gradient_data_subset.nc"

t0 = _time.time()
grad = run_analysis(
    operation="gradient",
    grid_path=DYA_GRID,
    data_path=DYA_DATA,
    variable_name="gaussian",
    use_remote=True,
    endpoint="chrysalis",
)
show(f"remote gradient ({_time.time() - t0:.1f}s)", grad)

t0 = _time.time()
curl = run_analysis(
    operation="curl",
    grid_path=DYA_GRID,
    data_path=DYA_DATA,
    u_variable="gaussian",
    v_variable="inverse_gaussian",
    use_remote=True,
    endpoint="chrysalis",
)
show(f"remote curl / vorticity ({_time.time() - t0:.1f}s)", curl)

t0 = _time.time()
div = run_analysis(
    operation="divergence",
    grid_path=DYA_GRID,
    data_path=DYA_DATA,
    u_variable="gaussian",
    v_variable="inverse_gaussian",
    use_remote=True,
    endpoint="chrysalis",
)
show(f"remote divergence ({_time.time() - t0:.1f}s)", div)

# %% [markdown]
# ## 6.3 Remote zonal mean on QU 480km

# %%
t0 = _time.time()
zm = run_analysis(
    operation="calculate_zonal_mean",
    grid_path=MPAS_GRID,
    data_path=MPAS_DATA,
    variable_name="bottomDepth",
    use_remote=True,
    endpoint="chrysalis",
)
show(f"remote zonal mean ({_time.time() - t0:.1f}s)", zm)

# %% [markdown]
# ## 6.4 Timing summary
#
# Warm round-trips (worker already running) are typically 0.5–5s for these
# mesh sizes. Cold start (PBS scheduler spins up a new worker) can take 3–4
# minutes. The `diagnose_endpoint(action="status")` call above confirms the
# worker is live before submitting work.

# %% [markdown]
# ---
# ## Summary
#
# | What's new | How to reach it |
# |---|---|
# | **PR #64** App foundation | `from uxarray_mcp.app import make_registry, make_mcp_server, UXarrayApp` |
# | **PR #64** REST/OpenAPI | `uxarray-mcp openapi --port 8000` · `app.serve_openapi(...)` |
# | **PR #65** vector calculus | `run_analysis(operation="gradient"\|"curl"\|"divergence", ...)` |
# | **PR #65** azimuthal mean | `run_analysis(operation="azimuthal_mean", center_lon=, center_lat=, ...)` |
# | **PR #65** zonal anomaly | `run_analysis(operation="zonal_anomaly", ...)` |
# | **PR #65** verification | `run_analysis(operation="bias"\|"rmse"\|"pattern_correlation", ...)` |
# | **PR #65** climatology | `run_analysis(operation="temporal_mean"\|"anomaly", ...)` |
# | **PR #65** rectilinear remap | `run_analysis(operation="remap_to_rectilinear", target_lon=, target_lat=)` |
# | **PR #65** science prompts | `prompt/cyclone_structure`, `eddy_activity`, `model_evaluation`, `climatology_anomaly` |
# | **HPC** Chrysalis remote | Same calls + `use_remote=True, endpoint="chrysalis"` |
#
# Everything above is the *same* code path an MCP/AI client or the OpenAPI
# server uses — only the transport differs.
