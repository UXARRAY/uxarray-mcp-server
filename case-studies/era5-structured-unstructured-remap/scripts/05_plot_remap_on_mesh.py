"""Choropleth of the YAC-conservative-remapped field directly on the
ne30pg3 CONUS mesh faces, with real coastlines/state borders.

The MCP server's own plot_dataset(plot_type="variable") tool has no
projection/Cartopy support (see src/uxarray_mcp/domain/plotting.py,
render_variable()) -- only plot_type="mesh_geo" (wireframe-only) does. To
get a geographic choropleth we call UXarray's own
`uxda.plot.polygons(projection=..., backend="matplotlib")` directly, then
reach into the holoviews matplotlib renderer to get the underlying
cartopy GeoAxes and add coastlines/borders to it by hand.

Run with the project's own .venv.
"""

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import holoviews as hv
import uxarray as ux

hv.extension("matplotlib")

OUT = "/tmp/era5_raw"

uxds = ux.open_dataset(
    f"{OUT}/ne30pg3_conus.nc",
    f"{OUT}/forward_yac_conservative.nc",
)
da = uxds["precip_mm_day"]

el = da.plot.polygons(
    backend="matplotlib",
    cmap="Blues",
    projection=ccrs.PlateCarree(),
    title="YAC conservative remap: ERA5 precip on ne30pg3 CONUS mesh",
)
renderer = hv.Store.renderers["matplotlib"]
plot = renderer.get_plot(el)
fig = plot.state
ax = fig.axes[0]
ax.set_extent([-130, -65, 20, 50], crs=ccrs.PlateCarree())
ax.coastlines(resolution="50m")
ax.add_feature(cfeature.BORDERS.with_scale("50m"), linestyle=":")
ax.add_feature(cfeature.STATES.with_scale("50m"), linewidth=0.3)
gl = ax.gridlines(draw_labels=True, linewidth=0.2, color="gray", alpha=0.5)
gl.top_labels = False
gl.right_labels = False
fig.savefig(f"{OUT}/plot_remap_on_mesh.png", dpi=110, bbox_inches="tight")
print(f"wrote {OUT}/plot_remap_on_mesh.png")
