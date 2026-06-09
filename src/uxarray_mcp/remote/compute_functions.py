"""Globus Compute functions for remote execution.

These functions are serialized and sent to HPC endpoints via AllCodeStrategies.
They must be FULLY SELF-CONTAINED — only import packages available on the HPC
environment (uxarray, numpy, etc.). Never import from uxarray_mcp here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# NOTE on the inline branching below: Globus Compute serializes each remote_*
# function body and ships it to the worker. Closures over module-level helpers
# such as _remote_load_grid don't survive serialization reliably across SDK
# versions, so each function inlines the same ~6 lines of extension dispatch
# (HEALPix spec, .shp / .geojson via geopandas, else default open_grid /
# open_dataset). If you change one, change them all.


def remote_runtime_probe() -> Dict[str, Any]:
    """Return lightweight runtime diagnostics from the remote worker."""
    import getpass
    import importlib.util
    import os
    import platform
    import shutil
    import socket
    import sys

    modules: Dict[str, Any] = {}
    for name in ("uxarray", "xarray", "numpy"):
        spec = importlib.util.find_spec(name)
        info: Dict[str, Any] = {"available": spec is not None}
        if spec is not None:
            try:
                module = __import__(name)
                info["version"] = getattr(module, "__version__", None)
                info["file"] = getattr(module, "__file__", None)
            except Exception as exc:
                info["import_error"] = f"{type(exc).__name__}: {exc}"
        modules[name] = info

    yac_info: Dict[str, Any] = {}
    try:
        yac_spec = importlib.util.find_spec("yac")
        yac_info["package_available"] = yac_spec is not None
        if yac_spec is not None:
            yac_info["package_origin"] = yac_spec.origin
    except Exception as exc:
        yac_info["package_available"] = False
        yac_info["package_error"] = f"{type(exc).__name__}: {exc}"

    yac_info["core_importable"] = None
    yac_info["uxarray_helper_ok"] = None
    yac_info["native_import_check"] = (
        "skipped in remote_runtime_probe; use remote_yac_remap_smoke so "
        "YAC/MPI imports run under srun and cannot kill the Globus worker"
    )
    modules["yac"] = yac_info

    return {
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "cwd": os.getcwd(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "qsub_path": shutil.which("qsub"),
        "path_head": os.environ.get("PATH", "").split(":")[:5],
        "modules": modules,
    }


def remote_probe_path(file_path: str, inspect_netcdf: bool = True) -> Dict[str, Any]:
    """Return remote path accessibility details.

    This is intentionally simpler than UXarray inspection. The goal is to prove
    that a remote worker can reach and read the exact target path before
    debugging mesh parsing or scheduler fan-out.
    """
    import os
    import socket
    from pathlib import Path

    path = Path(file_path)
    exists = path.exists()
    is_file = path.is_file()
    readable = os.access(path, os.R_OK) if exists else False

    result: Dict[str, Any] = {
        "path": str(path),
        "hostname": socket.gethostname(),
        "exists": exists,
        "is_file": is_file,
        "readable": readable,
    }

    if exists:
        stat = path.stat()
        result["size_bytes"] = int(stat.st_size)
        result["mtime_epoch"] = float(stat.st_mtime)

        try:
            with path.open("rb") as handle:
                result["header_hex"] = handle.read(8).hex()
        except Exception as exc:
            result["header_error"] = f"{type(exc).__name__}: {exc}"

    if inspect_netcdf and exists and readable and is_file:
        try:
            import xarray as xr

            with xr.open_dataset(file_path, decode_cf=False) as ds:
                result["netcdf"] = {
                    "opened": True,
                    "dims": {name: int(size) for name, size in ds.sizes.items()},
                    "data_vars": list(ds.data_vars)[:20],
                    "coords": list(ds.coords)[:20],
                    "attrs_keys": sorted(list(ds.attrs.keys()))[:20],
                }
        except Exception as exc:
            result["netcdf"] = {
                "opened": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    return result


def remote_inspect_mesh(file_path: str) -> Dict[str, Any]:
    """Inspect mesh topology on remote HPC node.

    Parameters
    ----------
    file_path : str
        Path to mesh file on HPC filesystem

    Returns
    -------
    dict
        Mesh topology including n_face, n_node, n_edge, source

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    All imports must be within function scope for serialization.
    """
    import os

    import uxarray as ux

    if file_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(file_path.split(":")[1]))
    elif os.path.splitext(file_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(file_path, backend="geopandas")
    else:
        grid = ux.open_grid(file_path)

    return {
        "n_face": int(grid.n_face),
        "n_node": int(grid.n_node),
        "n_edge": int(grid.n_edge),
        "source": file_path,
    }


def remote_calculate_area(file_path: str) -> Dict[str, Any]:
    """Calculate face areas on remote HPC node.

    Parameters
    ----------
    file_path : str
        Path to mesh file on HPC filesystem

    Returns
    -------
    dict
        Area statistics including total_area, mean_area, min_area, max_area

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    All imports must be within function scope for serialization.
    """
    import os

    import numpy as np
    import uxarray as ux

    if file_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(file_path.split(":")[1]))
    elif os.path.splitext(file_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(file_path, backend="geopandas")
    else:
        grid = ux.open_grid(file_path)

    areas = grid.face_areas
    units = getattr(areas, "units", "m^2") if hasattr(areas, "units") else "m^2"
    values = areas.values if hasattr(areas, "values") else np.asarray(areas)

    return {
        "total_area": float(np.sum(values)),
        "mean_area": float(np.mean(values)),
        "min_area": float(np.min(values)),
        "max_area": float(np.max(values)),
        "area_units": str(units),
        "n_face": int(grid.n_face),
    }


def remote_inspect_variable(
    grid_path: str, data_path: str, variable_name: Optional[str] = None
) -> Dict[str, Any]:
    """Inspect data variables on remote HPC node.

    Parameters
    ----------
    grid_path : str
        Path to grid file on HPC filesystem
    data_path : str
        Path to data file on HPC filesystem
    variable_name : str | None
        Specific variable to inspect, or None for all variables

    Returns
    -------
    dict
        Variable metadata including dimensions, shapes, statistics

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    """
    import os

    import numpy as np
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    else:
        uxds = ux.open_dataset(grid_path, data_path)

    face_dims = {"n_face", "nCells"}
    node_dims = {"n_node", "nVertices"}
    edge_dims = {"n_edge", "nEdges"}

    var_names = [variable_name] if variable_name else list(uxds.keys())

    if variable_name and variable_name not in uxds:
        raise ValueError(f"Variable '{variable_name}' not found in dataset")

    variables = []

    for name in var_names:
        if name not in uxds:
            continue
        var = uxds[name]
        dims = var.dims

        location = "other"
        if any(d in face_dims for d in dims):
            location = "faces"
        elif any(d in node_dims for d in dims):
            location = "nodes"
        elif any(d in edge_dims for d in dims):
            location = "edges"

        stats = None
        try:
            values = var.values
            finite = values[np.isfinite(values)]
            if len(finite) > 0:
                stats = {
                    "min": float(np.min(finite)),
                    "max": float(np.max(finite)),
                    "mean": float(np.mean(finite)),
                }
        except Exception:
            pass

        variables.append(
            {
                "name": name,
                "dims": list(dims),
                "shape": list(var.shape),
                "dtype": str(var.dtype),
                "location": location,
                "attrs": dict(var.attrs),
                "statistics": stats,
            }
        )

    return {
        "variables": variables,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }


def remote_plot_mesh(
    grid_path: str,
    width: int = 800,
    height: int = 400,
) -> Dict[str, Any]:
    """Render a mesh wireframe on the remote HPC node and return base64 PNG.

    Parameters
    ----------
    grid_path : str
        Path to mesh file on HPC filesystem, or "healpix:<zoom>".
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.

    Returns
    -------
    dict
        - png_b64: base64-encoded PNG string
        - image_size_bytes: size of the PNG
        - grid_info: n_face, n_node, n_edge
    """
    import base64
    import io

    import matplotlib

    matplotlib.use("Agg")
    import os

    import matplotlib.pyplot as plt
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
    else:
        grid = ux.open_grid(grid_path)

    import holoviews as hv

    hv.extension("matplotlib")

    dpi = 100
    element = grid.plot.mesh(backend="matplotlib")
    renderer = hv.Store.renderers["matplotlib"]
    plot = renderer.get_plot(element)
    fig = plot.state
    fig.set_size_inches(width / dpi, height / dpi)
    fig.set_dpi(dpi)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError("Rendered mesh plot is empty.")

    return {
        "png_b64": base64.b64encode(png_bytes).decode("utf-8"),
        "image_size_bytes": len(png_bytes),
        "grid_info": {
            "n_face": int(grid.n_face),
            "n_node": int(grid.n_node),
            "n_edge": int(grid.n_edge),
        },
    }


def remote_plot_variable(
    grid_path: str,
    data_path: str,
    variable_name: Optional[str] = None,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    title: Optional[str] = None,
    time_index: int = 0,
) -> Dict[str, Any]:
    """Render a face-centered variable plot on the remote HPC node and return base64 PNG.

    Parameters
    ----------
    grid_path : str
        Path to mesh grid file on HPC filesystem.
    data_path : str
        Path to data file on HPC filesystem.
    variable_name : str | None
        Variable to plot. If None, first face-centered variable is used.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    cmap : str
        Matplotlib colormap name.
    vmin : float | None
        Colormap minimum.
    vmax : float | None
        Colormap maximum.
    title : str | None
        Plot title.

    Returns
    -------
    dict
        - png_b64: base64-encoded PNG string
        - image_size_bytes: size of the PNG
        - variable_name: plotted variable name
        - grid_info: n_face, n_node, n_edge
    """
    import base64
    import io

    import matplotlib

    matplotlib.use("Agg")
    import os

    import matplotlib.pyplot as plt
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    else:
        uxds = ux.open_dataset(grid_path, data_path)

    face_dims = {"n_face", "nCells"}

    if variable_name is None:
        for var in uxds.data_vars:
            if any(d in face_dims for d in uxds[var].dims):
                variable_name = var
                break
        if variable_name is None:
            raise ValueError(
                f"No face-centered variable found. Available: {list(uxds.data_vars.keys())}"
            )

    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. Available: {list(uxds.data_vars.keys())}"
        )

    uxda = uxds[variable_name]
    if not any(d in face_dims for d in uxda.dims):
        raise ValueError(f"Variable '{variable_name}' is not face-centered.")

    extra_dims = [d for d in uxda.dims if d not in face_dims]
    if extra_dims:
        uxda = uxda.isel(
            **{d: 0 if uxda.sizes[d] == 1 else time_index for d in extra_dims}
        )

    import holoviews as hv

    hv.extension("matplotlib")

    dpi = 100
    kwargs: Dict[str, Any] = {"backend": "matplotlib", "cmap": cmap}
    if vmin is not None:
        import numpy as np

        kwargs["clim"] = (
            vmin,
            vmax if vmax is not None else float(np.nanmax(uxda.values)),
        )
    elif vmax is not None:
        import numpy as np

        kwargs["clim"] = (float(np.nanmin(uxda.values)), vmax)

    element = uxda.plot.polygons(**kwargs)
    renderer = hv.Store.renderers["matplotlib"]
    plot = renderer.get_plot(element)
    fig = plot.state
    fig.set_size_inches(width / dpi, height / dpi)
    fig.set_dpi(dpi)
    if title is not None:
        fig.axes[0].set_title(title)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError("Rendered variable plot is empty.")

    return {
        "png_b64": base64.b64encode(png_bytes).decode("utf-8"),
        "image_size_bytes": len(png_bytes),
        "variable_name": variable_name,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }


def remote_plot_zonal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    width: int = 800,
    height: int = 400,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
    line_color: str = "#1f77b4",
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Render a zonal mean profile on the remote HPC node and return base64 PNG.

    Parameters
    ----------
    grid_path : str
        Path to mesh grid file on HPC filesystem.
    data_path : str
        Path to data file on HPC filesystem.
    variable_name : str
        Variable to compute zonal mean for (must be face-centered).
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    lat_spec : tuple | float | list | None
        Latitude specification. None uses default 10-degree bands.
    conservative : bool
        Use area-weighted averaging.
    line_color : str
        Matplotlib color string for the profile line.
    title : str | None
        Plot title.

    Returns
    -------
    dict
        - png_b64: base64-encoded PNG string
        - image_size_bytes: size of the PNG
        - variable_name: plotted variable name
        - latitudes: list of latitude values
        - zonal_mean_values: list of zonal mean values
    """
    import base64
    import io

    import matplotlib

    matplotlib.use("Agg")
    import os

    import matplotlib.pyplot as plt
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    else:
        uxds = ux.open_dataset(grid_path, data_path)

    if variable_name not in uxds:
        raise ValueError(f"Variable '{variable_name}' not found")

    var = uxds[variable_name]
    face_dims = {"n_face", "nCells"}
    if not any(d in face_dims for d in var.dims):
        raise ValueError(f"Variable '{variable_name}' is not face-centered")

    if lat_spec is None:
        lat_spec = (-90, 90, 10)

    if conservative:
        result = var.zonal_mean(lat=lat_spec, conservative=True)
    else:
        result = var.zonal_mean(lat=lat_spec)

    latitudes = result.coords[result.dims[0]].values.tolist()
    values = result.values.tolist()

    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax.plot(latitudes, values, linewidth=1.5, color=line_color)
    ax.set_xlabel("Latitude (°)")
    ax.set_ylabel(variable_name)
    ax.set_title(title if title is not None else f"Zonal Mean — {variable_name}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError("Rendered zonal mean plot is empty.")

    return {
        "png_b64": base64.b64encode(png_bytes).decode("utf-8"),
        "image_size_bytes": len(png_bytes),
        "variable_name": variable_name,
        "latitudes": latitudes,
        "zonal_mean_values": values,
    }


def remote_calculate_zonal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
) -> Dict[str, Any]:
    """Calculate zonal mean on remote HPC node.

    Parameters
    ----------
    grid_path : str
        Path to grid file on HPC filesystem
    data_path : str
        Path to data file on HPC filesystem
    variable_name : str
        Variable to compute zonal mean for
    lat_spec : tuple | float | list | None
        Latitude specification
    conservative : bool
        Whether to use conservative averaging

    Returns
    -------
    dict
        Zonal mean results including latitudes and values

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    """
    import os

    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    else:
        uxds = ux.open_dataset(grid_path, data_path)

    if variable_name not in uxds:
        raise ValueError(f"Variable '{variable_name}' not found")

    var = uxds[variable_name]
    face_dims = {"n_face", "nCells"}
    if not any(d in face_dims for d in var.dims):
        raise ValueError(f"Variable '{variable_name}' is not face-centered")

    if lat_spec is None:
        lat_spec = (-90, 90, 10)

    if conservative:
        result = var.zonal_mean(lat=lat_spec, conservative=True)
    else:
        result = var.zonal_mean(lat=lat_spec)

    return {
        "variable_name": variable_name,
        "latitudes": result.coords[result.dims[0]].values.tolist(),
        "zonal_mean_values": result.values.tolist(),
        "conservative": conservative,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }


def remote_subset_bbox_plot(
    grid_path: str,
    lon_bounds: list,
    lat_bounds: list,
    region_name: str = "",
    width: int = 800,
    height: int = 450,
    edgecolor: str = "steelblue",
    facecolor: str = "lightcyan",
    linewidth: float = 0.3,
) -> Dict[str, Any]:
    """Subset a mesh by bounding box and return stats + a wireframe PNG.

    Runs entirely on the HPC worker so multi-GB files never leave the
    facility filesystem.  All rendering parameters are echoed back in the
    return dict so the caller has a complete provenance record: to reproduce
    or modify the plot, change any field and resubmit.

    Parameters
    ----------
    grid_path : str
        Path to mesh file on HPC filesystem.
    lon_bounds : list
        [lon_min, lon_max] in degrees.
    lat_bounds : list
        [lat_min, lat_max] in degrees.
    region_name : str
        Human-readable label for the plot title.
    width, height : int
        PNG dimensions in pixels.
    edgecolor : str
        Matplotlib color for cell edges.
    facecolor : str
        Matplotlib color for cell fill.
    linewidth : float
        Edge line width in points.

    Returns
    -------
    dict
        - region_name, lon_bounds, lat_bounds: inputs echoed for provenance
        - plot_params: all rendering parameters (edgecolor, facecolor,
          linewidth, width, height, dpi) — change any field and resubmit
          to modify the plot without re-running the analysis
        - n_face_total, n_face_subset, fraction_of_mesh: coverage statistics
        - mean_area_full_sr, mean_area_subset_sr: face-area statistics (sr)
        - resolution_ratio: mean_area_full / mean_area_subset  (>1 = finer)
        - uxarray_version: library version on the HPC worker
        - png_b64: base64 PNG of the subset wireframe
        - image_size_bytes: PNG size in bytes
    """
    import base64
    import importlib.metadata
    import io
    import math

    import matplotlib

    matplotlib.use("Agg")
    import os

    import matplotlib.pyplot as plt
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
    else:
        grid = ux.open_grid(grid_path)
    n_face_total = int(grid.n_face)

    # full-mesh mean area
    full_areas = grid.face_areas
    mean_area_full = float(full_areas.values.mean())

    # subset by bounding box
    subset = grid.subset.bounding_box(
        lon_bounds=lon_bounds,
        lat_bounds=lat_bounds,
    )
    n_face_subset = int(subset.n_face)

    subset_areas = subset.face_areas
    mean_area_subset = (
        float(subset_areas.values.mean()) if n_face_subset > 0 else float("nan")
    )

    resolution_ratio = (
        mean_area_full / mean_area_subset
        if mean_area_subset and not math.isnan(mean_area_subset)
        else None
    )

    # plot subset: draw face-edge polygons using node coordinates
    dpi = 100
    fig, ax = plt.subplots(figsize=(width / dpi, height / dpi), dpi=dpi)
    title = region_name if region_name else f"lon{lon_bounds} lat{lat_bounds}"
    subtitle = (
        f"{n_face_subset:,} faces  |  res_ratio={resolution_ratio:.2f}x"
        if resolution_ratio
        else f"{n_face_subset:,} faces"
    )

    from matplotlib.collections import PolyCollection

    # Build polygon vertices from face-node connectivity
    try:
        face_lon = subset.node_lon.values  # (n_node,)
        face_lat = subset.node_lat.values  # (n_node,)
        conn = subset.face_node_connectivity.values  # (n_face, max_nodes)
        fill_val = getattr(subset.face_node_connectivity, "_FillValue", -1)
        polys = []
        for row in conn:
            idx = row[row != fill_val]
            if len(idx) >= 3:
                polys.append(list(zip(face_lon[idx], face_lat[idx])))
        if polys:
            col = PolyCollection(
                polys, edgecolors=edgecolor, facecolors=facecolor, linewidths=linewidth
            )
            ax.add_collection(col)
            ax.set_xlim(lon_bounds)
            ax.set_ylim(lat_bounds)
        else:
            raise ValueError("no valid polygons")
    except Exception:
        # fallback: scatter face centres
        lons = subset.face_lon.values
        lats = subset.face_lat.values
        ax.scatter(lons, lats, s=2, color=edgecolor, alpha=0.6)
        ax.set_xlim(lon_bounds)
        ax.set_ylim(lat_bounds)

    ax.set_title(f"{title}\n{subtitle}", fontsize=10)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()

    try:
        ux_version = importlib.metadata.version("uxarray")
    except Exception:
        ux_version = "unknown"

    return {
        "region_name": region_name,
        "lon_bounds": lon_bounds,
        "lat_bounds": lat_bounds,
        "plot_params": {
            "edgecolor": edgecolor,
            "facecolor": facecolor,
            "linewidth": linewidth,
            "width_px": width,
            "height_px": height,
            "dpi": dpi,
        },
        "n_face_total": n_face_total,
        "n_face_subset": n_face_subset,
        "fraction_of_mesh": n_face_subset / n_face_total if n_face_total else None,
        "mean_area_full_sr": mean_area_full,
        "mean_area_subset_sr": mean_area_subset,
        "resolution_ratio": resolution_ratio,
        "uxarray_version": ux_version,
        "png_b64": base64.b64encode(png_bytes).decode(),
        "image_size_bytes": len(png_bytes),
    }


def remote_yac_remap_smoke() -> Dict[str, Any]:
    """Smoke-test YAC's availability on the remote worker.

    Runs the native YAC import/remap in a worker-side subprocess. Some YAC/MPI
    builds can terminate the importing process when their runtime library path
    is incomplete; keeping the import in a child process lets the Globus worker
    return structured diagnostics instead of disappearing as ``WorkerLost``.

    The function is self-contained and serialised via AllCodeStrategies so the
    Python 3.13/3.11 mismatch between local SDK and worker doesn't bite.
    """
    import json
    import os
    import re
    import shutil
    import subprocess
    import sys
    import textwrap

    code = r"""
import importlib.metadata
import json
import os
import sys
import time
import traceback

out = {
    "python": sys.version,
    "executable": sys.executable,
    "pythonpath_set": bool(os.environ.get("PYTHONPATH")),
    "ld_library_path_set": bool(os.environ.get("LD_LIBRARY_PATH")),
}

def _surface(mod):
    return {
        name: hasattr(mod, name)
        for name in (
            "BasicGrid",
            "InterpField",
            "InterpolationStack",
            "compute_weights",
            "Reg2dGrid",
        )
    }

try:
    import yac.core as yc

    out["yac_core_ok"] = True
    out["yac_core_file"] = getattr(yc, "__file__", None)
except Exception as exc:
    out["yac_core_ok"] = False
    out["yac_core_error"] = f"{type(exc).__name__}: {exc}"
    out["yac_core_traceback"] = traceback.format_exc()

try:
    from uxarray.remap.yac import _import_yac

    yc = _import_yac()
    out["yac_helper_ok"] = True
    out["yac_loader"] = "uxarray.remap.yac._import_yac"
    out["yac_module"] = getattr(yc, "__name__", None)
    out["yac_file"] = getattr(yc, "__file__", None)
    out["surface"] = _surface(yc)
except Exception as exc:
    out["yac_helper_ok"] = False
    out["yac_helper_error"] = f"{type(exc).__name__}: {exc}"
    out["yac_helper_traceback"] = traceback.format_exc()

try:
    out["uxarray_version"] = importlib.metadata.version("uxarray")
except Exception:
    out["uxarray_version"] = "unknown"

try:
    import numpy as np
    import uxarray as ux
    import xarray as xr

    src = ux.Grid.from_healpix(zoom=2)
    dst = ux.Grid.from_healpix(zoom=3)
    out["src_n_face"] = int(src.n_face)
    out["dst_n_face"] = int(dst.n_face)

    rng = np.random.default_rng(0)
    face_data = rng.standard_normal(int(src.n_face))
    uxda = ux.UxDataArray(
        xr.DataArray(face_data, dims=("n_face",), name="field"),
        uxgrid=src,
    )

    t0 = time.perf_counter()
    remapped = uxda.remap.nearest_neighbor(
        destination_grid=dst, remap_to="face centers"
    )
    out["remap_method"] = "nearest_neighbor"
    out["remap_ok"] = True
    out["remap_seconds"] = round(time.perf_counter() - t0, 3)
    out["remap_dst_shape"] = list(remapped.shape)
    out["remap_dst_mean"] = float(np.asarray(remapped).mean())
except Exception as exc:
    out["remap_ok"] = False
    out["remap_error"] = f"{type(exc).__name__}: {exc}"
    out["remap_traceback"] = traceback.format_exc()

print(json.dumps(out))
raise SystemExit(0 if out.get("yac_helper_ok") and out.get("remap_ok") else 1)
"""

    try:
        command = [sys.executable, "-c", textwrap.dedent(code)]
        launch_mode = "direct"
        if os.environ.get("SLURM_JOB_ID") and shutil.which("srun"):
            command = ["srun", "--ntasks", "1", *command]
            launch_mode = "srun"
        proc = subprocess.run(
            command,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "subprocess_ok": False,
            "subprocess_timeout_seconds": exc.timeout,
            "stdout": exc.stdout,
            "stderr": exc.stderr,
        }

    payload: Dict[str, Any] = {
        "subprocess_ok": proc.returncode == 0,
        "subprocess_returncode": proc.returncode,
        "launch_mode": launch_mode,
    }
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    if stdout:
        payload["stdout_tail"] = stdout[-4000:]
    if stderr:
        payload["stderr_tail"] = stderr[-4000:]
    for line in reversed(stdout.splitlines()):
        line = re.sub(r"^\d+:\s*", "", line)
        try:
            payload.update(json.loads(line))
            break
        except Exception:
            continue
    else:
        payload["json_parse_error"] = "No JSON object found in subprocess stdout."
    return payload


# ---------------------------------------------------------------------------
# Vector calculus remote functions
# Each function is fully self-contained — no uxarray_mcp imports.
# Serialized via AllCodeStrategies so the HPC worker only needs uxarray+numpy.
# ---------------------------------------------------------------------------


def remote_calculate_gradient(
    grid_path: str, data_path: str, variable_name: str
) -> Dict[str, Any]:
    """Compute the spatial gradient of a face-centered scalar field on HPC."""
    import os

    import numpy as np
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    else:
        uxds = ux.open_dataset(grid_path, data_path)
    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. Available: {list(uxds.data_vars)}"
        )
    var = uxds[variable_name]
    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Gradient requires face-centered data."
        )

    grad = var.gradient()
    comp_names = list(grad.data_vars)

    def _stats(arr: Any) -> Dict[str, Any]:
        vals = arr.values
        finite = vals[np.isfinite(vals)]
        if finite.size == 0:
            return {"min": None, "max": None, "mean": None}
        return {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
        }

    return {
        "variable_name": variable_name,
        "components": comp_names,
        "component_stats": {name: _stats(grad[name]) for name in comp_names},
        "n_face": int(uxds.uxgrid.n_face),
        "interpretation": "zonal (d/dx) and meridional (d/dy) components of the gradient",
    }


def remote_calculate_curl(
    grid_path: str, data_path: str, u_variable: str, v_variable: str
) -> Dict[str, Any]:
    """Compute relative vorticity (curl) of a 2-D wind field on HPC.

    zeta = dv/dx - du/dy
    """
    import os

    import numpy as np
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    else:
        uxds = ux.open_dataset(grid_path, data_path)
    for name in (u_variable, v_variable):
        if name not in uxds.data_vars:
            raise ValueError(
                f"Variable '{name}' not found. Available: {list(uxds.data_vars)}"
            )
    u, v = uxds[u_variable], uxds[v_variable]
    for name, var in ((u_variable, u), (v_variable, v)):
        if "n_face" not in var.dims and "nCells" not in var.dims:
            raise ValueError(
                f"Variable '{name}' is not face-centered. "
                "Curl requires face-centered vector components."
            )

    result = u.curl(v)
    vals = result.values
    finite = vals[np.isfinite(vals)]
    stats: Dict[str, Any] = (
        {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "std": float(finite.std()),
        }
        if finite.size > 0
        else {"min": None, "max": None, "mean": None, "std": None}
    )
    return {
        "u_variable": u_variable,
        "v_variable": v_variable,
        "interpretation": "relative vorticity zeta = dv/dx - du/dy",
        "n_face": int(uxds.uxgrid.n_face),
        "stats": stats,
    }


def remote_calculate_divergence(
    grid_path: str, data_path: str, u_variable: str, v_variable: str
) -> Dict[str, Any]:
    """Compute horizontal divergence of a 2-D vector field on HPC.

    divergence = du/dx + dv/dy
    """
    import os

    import numpy as np
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    else:
        uxds = ux.open_dataset(grid_path, data_path)
    for name in (u_variable, v_variable):
        if name not in uxds.data_vars:
            raise ValueError(
                f"Variable '{name}' not found. Available: {list(uxds.data_vars)}"
            )
    u, v = uxds[u_variable], uxds[v_variable]
    for name, var in ((u_variable, u), (v_variable, v)):
        if "n_face" not in var.dims and "nCells" not in var.dims:
            raise ValueError(
                f"Variable '{name}' is not face-centered. "
                "Divergence requires face-centered vector components."
            )

    result = u.divergence(v)
    vals = result.values
    finite = vals[np.isfinite(vals)]
    stats: Dict[str, Any] = (
        {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "std": float(finite.std()),
        }
        if finite.size > 0
        else {"min": None, "max": None, "mean": None, "std": None}
    )
    return {
        "u_variable": u_variable,
        "v_variable": v_variable,
        "interpretation": "horizontal divergence du/dx + dv/dy",
        "n_face": int(uxds.uxgrid.n_face),
        "stats": stats,
    }


def remote_calculate_azimuthal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    center_lon: float,
    center_lat: float,
    outer_radius: float,
    radius_step: float,
) -> Dict[str, Any]:
    """Compute the azimuthal (radial) mean around a centre point on HPC."""
    import os

    import uxarray as ux

    if grid_path.startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.open_dataset(grid.to_xarray(), data_path)
    else:
        uxds = ux.open_dataset(grid_path, data_path)
    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. Available: {list(uxds.data_vars)}"
        )
    var = uxds[variable_name]
    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Azimuthal mean requires face-centered data."
        )

    result = var.azimuthal_mean(
        center_coord=(center_lon, center_lat),
        outer_radius=outer_radius,
        radius_step=radius_step,
    )
    radii = result.coords[result.dims[0]].values.tolist()
    values = result.values.tolist()

    return {
        "variable_name": variable_name,
        "center": {"lon": center_lon, "lat": center_lat},
        "outer_radius_deg": outer_radius,
        "radius_step_deg": radius_step,
        "radii_deg": radii,
        "azimuthal_mean_values": values,
        "n_face": int(uxds.uxgrid.n_face),
    }
