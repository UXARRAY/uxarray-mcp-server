# %% [markdown]
# # uxarray-mcp without an AI client
#
# This notebook drives the exact same tools that an MCP/AI client would call,
# but **directly from Python** — no Claude, no LLM, no MCP transport.
#
# Three layers are shown, simplest first:
#
# 1. **Plain function imports** — `from uxarray_mcp.tools import inspect_mesh`.
#    The tools are ordinary Python functions returning JSON-able dicts.
# 2. **Registry `get_callable`** — call tools *by name* through the same
#    `make_registry()` object the MCP server uses. This is the bridge for
#    REST/OpenAPI or any non-AI dispatcher.
# 3. **Plotting** — tools return base64-encoded PNGs; we decode and display
#    them inline (and the same bytes go over REST).
#
# No sample data ships with the repo, so we first synthesize a small UGRID
# mesh + a data variable on disk.

# %%
import base64
import json
import os
import tempfile

import xarray as xr

print("Building a synthetic UGRID mesh + data file...")
work = tempfile.mkdtemp(prefix="uxmcp_demo_")
grid_path = os.path.join(work, "grid.nc")
data_path = os.path.join(work, "data.nc")

# Two quad faces over a 6-node lon/lat patch (CF UGRID conventions).
grid = xr.Dataset(
    {
        "Mesh2": (
            [],
            0,
            {
                "cf_role": "mesh_topology",
                "topology_dimension": 2,
                "node_coordinates": "Mesh2_node_x Mesh2_node_y",
                "face_node_connectivity": "Mesh2_face_nodes",
            },
        ),
        "Mesh2_node_x": (["nMesh2_node"], [0.0, 10.0, 20.0, 0.0, 10.0, 20.0]),
        "Mesh2_node_y": (["nMesh2_node"], [0.0, 0.0, 0.0, 10.0, 10.0, 10.0]),
        "Mesh2_face_nodes": (
            ["nMesh2_face", "nMaxMesh2_face_nodes"],
            [[0, 1, 4, 3], [1, 2, 5, 4]],
            {"cf_role": "face_node_connectivity", "start_index": 0},
        ),
    }
)
grid.to_netcdf(grid_path)

data = xr.Dataset(
    {
        "temperature": (
            ["nMesh2_face"],
            [280.0, 295.0],
            {"units": "K", "long_name": "air_temperature"},
        )
    }
)
data.to_netcdf(data_path)

print("grid_path:", grid_path)
print("data_path:", data_path)

# %% [markdown]
# ## Layer 1 — call tools as plain Python functions
#
# Every tool returns a JSON-serializable dict (plus a `_provenance` block).
# This is all you need for scripts, pipelines, or a Fortran/C post-processor
# that shells out to a Python helper.

# %%
from uxarray_mcp.tools import calculate_area, inspect_mesh, inspect_variable


def show(title, result):
    """Pretty-print a tool result, hiding the verbose provenance block."""
    print(f"=== {title} ===")
    clean = {k: v for k, v in result.items() if k != "_provenance"}
    print(json.dumps(clean, indent=2, default=str))
    print()


show("inspect_mesh", inspect_mesh(file_path=grid_path))
show("calculate_area", calculate_area(file_path=grid_path))
show(
    "inspect_variable",
    inspect_variable(
        grid_path=grid_path, data_path=data_path, variable_name="temperature"
    ),
)

# %% [markdown]
# ### Provenance is always attached
#
# Every result carries a `_provenance` record — where it ran, tool version,
# inputs. This is what makes results reproducible and auditable, independent
# of any AI client.

# %%
prov = inspect_mesh(file_path=grid_path)["_provenance"]
print(json.dumps(prov, indent=2, default=str))

# %% [markdown]
# ## Layer 2 — call tools *by name* through the registry
#
# `make_registry()` returns the very same `ToolRegistry` the MCP server wires
# up. `get_callable(name)` hands you the function for any registered tool, so
# a REST/OpenAPI front end (or your own dispatcher) can route
# `{"tool": "...", "args": {...}}` requests with no AI in the loop.

# %%
from uxarray_mcp.app import make_registry

reg = make_registry(profile="core")
tools = reg.list_tools()
print(f"core profile exposes {len(tools)} tools:\n")
for t in sorted(tools):
    print(" ", t)

# %% [markdown]
# The front-door `run_analysis` dispatcher takes an `operation` string and
# routes to the right computation — this is the single entry point a thin
# REST handler would expose.

# %%
run_analysis = reg.get_callable("run_analysis")

for op in ("inspect_mesh", "calculate_area"):
    res = run_analysis(operation=op, grid_path=grid_path)
    show(f"run_analysis(operation={op!r})", res)

# zonal mean needs a variable
res = run_analysis(
    operation="inspect_variable",
    grid_path=grid_path,
    data_path=data_path,
    variable_name="temperature",
)
show("run_analysis(operation='inspect_variable')", res)

# %% [markdown]
# ### Simulating a REST request without a server
#
# A REST handler receives JSON, looks up the tool, and calls it. Here is that
# exact flow in three lines — swap `incoming` for an HTTP body and you have
# the OpenAPI surface, no AI client required.

# %%
incoming = {
    "tool": "run_analysis",
    "args": {"operation": "calculate_area", "grid_path": grid_path},
}

fn = reg.get_callable(incoming["tool"])
response = fn(**incoming["args"])
print(
    json.dumps(
        {k: v for k, v in response.items() if k != "_provenance"}, indent=2, default=str
    )
)

# %% [markdown]
# ## Layer 3 — plots come back as base64 PNGs
#
# Plotting tools return a list of MCP content objects; the image is a
# base64-encoded PNG string in `items[0].data`. No file is written to disk —
# the same bytes travel over REST/MCP. We decode and display it inline.

# %%
from IPython.display import Image, display

from uxarray_mcp.tools import plot_mesh

items = plot_mesh(grid_path, width=640, height=320)
print("returned:", [type(i).__name__ for i in items])

png_bytes = base64.b64decode(items[0].data)
print("decoded PNG size:", len(png_bytes), "bytes")

# Save a copy and show it
out_png = os.path.join(work, "mesh.png")
with open(out_png, "wb") as fh:
    fh.write(png_bytes)
print("wrote:", out_png)

display(Image(data=png_bytes))

# %% [markdown]
# ### The text item carries provenance
#
# The second content item is the provenance JSON, so even an image response
# is fully traceable.

# %%
print(items[1].text)

# %% [markdown]
# ## No file at all: HEALPix pseudo-path
#
# For mesh-only tools you can pass `"healpix:<zoom>"` instead of a file path
# and a HEALPix grid is generated on the fly — handy for quick checks with no
# data on disk.

# %%
show("inspect_mesh on healpix:2", inspect_mesh(file_path="healpix:2"))

# %% [markdown]
# ## Summary
#
# | Need | No-AI-client call |
# |---|---|
# | One specific computation | `from uxarray_mcp.tools import inspect_mesh; inspect_mesh(...)` |
# | Call by name / build a REST router | `reg = make_registry(); reg.get_callable(name)(**args)` |
# | List available tools | `reg.list_tools()` |
# | Plots | tool returns base64 PNG -> `base64.b64decode(items[0].data)` |
# | Reproducibility | every result has `_provenance` |
#
# The MCP server and any AI client call these *same* functions. Dropping the
# AI client changes nothing about the computation, the results, or provenance.
