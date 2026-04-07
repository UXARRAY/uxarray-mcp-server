"""Globus Compute functions for remote execution.

These functions are serialized and sent to HPC endpoints via AllCodeStrategies.
They must be FULLY SELF-CONTAINED — only import packages available on the HPC
environment (uxarray, numpy, etc.). Never import from uxarray_mcp here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def remote_runtime_probe() -> Dict[str, Any]:
    """Return lightweight runtime diagnostics from the remote worker.

    This intentionally does not touch UXarray or the filesystem. The goal is to
    prove that a submitted task can reach a real worker and report back enough
    environment detail to diagnose scheduler/bootstrap issues.
    """
    import getpass
    import os
    import platform
    import shutil
    import socket

    return {
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "cwd": os.getcwd(),
        "python_version": platform.python_version(),
        "qsub_path": shutil.which("qsub"),
        "path_head": os.environ.get("PATH", "").split(":")[:5],
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
    import uxarray as ux

    if file_path.startswith("healpix:"):
        zoom = int(file_path.split(":")[1])
        grid = ux.Grid.from_healpix(zoom)
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
    import numpy as np
    import uxarray as ux

    if file_path.startswith("healpix:"):
        zoom = int(file_path.split(":")[1])
        grid = ux.Grid.from_healpix(zoom)
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
    import numpy as np
    import uxarray as ux

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
    import matplotlib.pyplot as plt
    import uxarray as ux

    if grid_path.startswith("healpix:"):
        zoom = int(grid_path.split(":")[1])
        grid = ux.Grid.from_healpix(zoom)
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
    import matplotlib.pyplot as plt
    import uxarray as ux

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

    import holoviews as hv
    hv.extension("matplotlib")

    dpi = 100
    kwargs: Dict[str, Any] = {"backend": "matplotlib", "cmap": cmap}
    if vmin is not None:
        import numpy as np
        kwargs["clim"] = (vmin, vmax if vmax is not None else float(np.nanmax(uxda.values)))
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
    import matplotlib.pyplot as plt
    import uxarray as ux

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
    import uxarray as ux

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
