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
        "_worker_runtime": {
            "hostname": socket.gethostname(),
            "python_version": platform.python_version(),
            "uxarray_version": (modules.get("uxarray") or {}).get("version")
            or "unknown",
            "xarray_version": (modules.get("xarray") or {}).get("version") or "unknown",
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "pbs_job_id": os.environ.get("PBS_JOBID"),
        },
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

    try:
        _ux_version = getattr(__import__("uxarray"), "__version__", "unknown")
    except Exception:
        _ux_version = "unavailable"
    try:
        _xr_version = getattr(__import__("xarray"), "__version__", "unknown")
    except Exception:
        _xr_version = "unavailable"
    result["_worker_runtime"] = {
        "hostname": socket.gethostname(),
        "python_version": __import__("platform").python_version(),
        "uxarray_version": _ux_version,
        "xarray_version": _xr_version,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "pbs_job_id": os.environ.get("PBS_JOBID"),
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
        Mesh topology including n_face, n_node, n_edge, source, and the
        same ``mesh_coverage`` block the local path attaches.

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    All imports must be within function scope for serialization.
    """
    import os

    import uxarray as ux

    # The same measurement domain/mesh_coverage.py makes, nested here rather
    # than imported: AllCodeStrategies ships this function's code and nothing
    # else, so the worker has no uxarray_mcp to import from. Nested, not
    # module-level, for the same reason. tests/test_remote_mesh_coverage.py
    # asserts the two implementations agree on the same grid, which is the
    # only thing standing between them and drift.
    def _mesh_coverage(_grid, _steradians=None):
        import math as _math

        import numpy as _np

        _MAX_FACES = 250_000
        _DP = 6
        _cov: dict = {
            "sphere_fraction": None,
            "closed": None,
            "euler_characteristic": None,
            "lon_extent": None,
            "lat_extent": None,
        }
        if _steradians is None:
            try:
                _steradians = float(_np.asarray(_grid.face_areas).sum())
            except Exception:
                _steradians = None
        if _steradians is not None and _math.isfinite(_steradians):
            _cov["sphere_fraction"] = round(float(_steradians) / (4.0 * _math.pi), _DP)
        try:
            _lon = _np.asarray(_grid.node_lon, dtype=float)
            _lat = _np.asarray(_grid.node_lat, dtype=float)
            if _lon.size and _lat.size:
                _cov["lon_extent"] = [
                    round(float(_lon.min()), _DP),
                    round(float(_lon.max()), _DP),
                ]
                _cov["lat_extent"] = [
                    round(float(_lat.min()), _DP),
                    round(float(_lat.max()), _DP),
                ]
        except Exception:
            pass
        try:
            _n_face = int(_grid.n_face)
        except Exception:
            return _cov
        # Kept identical to the local limit, and it matters more here: the
        # meshes that justify an HPC endpoint are the ones above it.
        if _n_face > _MAX_FACES:
            _cov["topology_skipped"] = (
                f"{_n_face} faces exceeds the {_MAX_FACES}-face limit for "
                "counting edge incidences; closure was not checked."
            )
            return _cov
        try:
            _cov["euler_characteristic"] = (
                int(_grid.n_node) - int(_grid.n_edge) + _n_face
            )
        except Exception:
            pass
        try:
            _conn = _np.asarray(_grid.face_node_connectivity)
            _clon = _np.asarray(_grid.node_lon, dtype=float) % 360.0
            _clat = _np.asarray(_grid.node_lat, dtype=float)
        except Exception:
            return _cov
        _seen: dict = {}
        _ids = []
        for _x, _y in zip(_clon, _clat):
            if abs(abs(_y) - 90.0) < 1e-9:
                _key = f"pole{_y:+.1f}"
            else:
                _key = f"{round(_x, _DP) % 360:.6f}_{round(_y, _DP):.6f}"
            _ids.append(_seen.setdefault(_key, len(_seen)))
        _n_node = len(_ids)
        _incidence: dict = {}
        for _face in _conn:
            _nodes: list = []
            for _raw in _face:
                _index = int(_raw)
                if not 0 <= _index < _n_node:
                    continue
                _node = _ids[_index]
                if not _nodes or _nodes[-1] != _node:
                    _nodes.append(_node)
            if len(_nodes) > 1 and _nodes[0] == _nodes[-1]:
                _nodes.pop()
            if len(_nodes) < 3:
                continue
            for _index, _node in enumerate(_nodes):
                _other = _nodes[(_index + 1) % len(_nodes)]
                _edge = (min(_node, _other), max(_node, _other))
                _incidence[_edge] = _incidence.get(_edge, 0) + 1
        _cov["closed"] = bool(_incidence) and all(
            _count == 2 for _count in _incidence.values()
        )
        return _cov

    if file_path.lower().startswith("healpix:"):
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
        "mesh_coverage": _mesh_coverage(grid),
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }


def remote_validate_dataset(grid_path: str, data_path: str) -> Dict[str, Any]:
    """Validate numeric variables on the worker that can read the dataset."""
    import os

    import numpy as np
    import uxarray as ux

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        xr_ds = __import__("xarray").open_dataset(data_path)
        uxds = ux.UxDataset(xr_ds, uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        xr_ds = __import__("xarray").open_dataset(data_path)
        uxds = ux.UxDataset(xr_ds, uxgrid=grid)
    else:
        uxds = ux.open_dataset(grid_path, data_path)

    fill_candidates = [1e20, 9.96920996838687e36, -999.0, -9999.0]
    results = []
    all_warnings: list[str] = []
    for name in uxds.data_vars:
        values = uxds[name].values
        if not np.issubdtype(values.dtype, np.number):
            continue
        is_float = np.issubdtype(values.dtype, np.floating)
        n_nan = int(np.sum(np.isnan(values))) if is_float else 0
        n_inf = int(np.sum(np.isinf(values))) if is_float else 0
        n_fill = 0
        detected_fill = None
        if is_float:
            for candidate in fill_candidates:
                count = int(np.sum(np.isclose(values, candidate, rtol=1e-3)))
                if count:
                    n_fill = count
                    detected_fill = candidate
                    break
        warnings = []
        if n_nan:
            warnings.append(f"{name}: contains {n_nan} NaN values")
        if n_inf:
            warnings.append(f"{name}: contains {n_inf} Inf values")
        if n_fill:
            warnings.append(f"{name}: contains {n_fill} fill values")
        all_warnings.extend(warnings)
        results.append(
            {
                "name": name,
                "passed": not warnings,
                "n_nan": n_nan,
                "n_inf": n_inf,
                "n_fill_values": n_fill,
                "detected_fill_value": detected_fill,
                "shape": list(values.shape),
                "dtype": str(values.dtype),
                "warnings": warnings,
            }
        )

    passed = all(item["passed"] for item in results)
    return {
        "passed": passed,
        "is_valid": passed,
        "n_variables_checked": len(results),
        "n_variables_failed": sum(not item["passed"] for item in results),
        "variables": results,
        "issues": all_warnings,
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
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
        Area statistics including total_area, mean_area, min_area,
        max_area, and the ``mesh_coverage`` block that says what fraction
        of the sphere the total was summed over.

    Notes
    -----
    This function executes on the HPC endpoint, not locally.
    All imports must be within function scope for serialization.
    """
    import os

    import numpy as np
    import uxarray as ux

    # Nested copy of domain/mesh_coverage.py -- see remote_inspect_mesh for
    # why it cannot be imported or shared. Without it a remote total is the
    # bare number the local path stopped shipping in #33: nothing in the
    # payload says whether it was summed over the planet or over a patch.
    def _mesh_coverage(_grid, _steradians=None):
        import math as _math

        import numpy as _np

        _MAX_FACES = 250_000
        _DP = 6
        _cov: dict = {
            "sphere_fraction": None,
            "closed": None,
            "euler_characteristic": None,
            "lon_extent": None,
            "lat_extent": None,
        }
        if _steradians is None:
            try:
                _steradians = float(_np.asarray(_grid.face_areas).sum())
            except Exception:
                _steradians = None
        if _steradians is not None and _math.isfinite(_steradians):
            _cov["sphere_fraction"] = round(float(_steradians) / (4.0 * _math.pi), _DP)
        try:
            _lon = _np.asarray(_grid.node_lon, dtype=float)
            _lat = _np.asarray(_grid.node_lat, dtype=float)
            if _lon.size and _lat.size:
                _cov["lon_extent"] = [
                    round(float(_lon.min()), _DP),
                    round(float(_lon.max()), _DP),
                ]
                _cov["lat_extent"] = [
                    round(float(_lat.min()), _DP),
                    round(float(_lat.max()), _DP),
                ]
        except Exception:
            pass
        try:
            _n_face = int(_grid.n_face)
        except Exception:
            return _cov
        if _n_face > _MAX_FACES:
            _cov["topology_skipped"] = (
                f"{_n_face} faces exceeds the {_MAX_FACES}-face limit for "
                "counting edge incidences; closure was not checked."
            )
            return _cov
        try:
            _cov["euler_characteristic"] = (
                int(_grid.n_node) - int(_grid.n_edge) + _n_face
            )
        except Exception:
            pass
        try:
            _conn = _np.asarray(_grid.face_node_connectivity)
            _clon = _np.asarray(_grid.node_lon, dtype=float) % 360.0
            _clat = _np.asarray(_grid.node_lat, dtype=float)
        except Exception:
            return _cov
        _seen: dict = {}
        _ids = []
        for _x, _y in zip(_clon, _clat):
            if abs(abs(_y) - 90.0) < 1e-9:
                _key = f"pole{_y:+.1f}"
            else:
                _key = f"{round(_x, _DP) % 360:.6f}_{round(_y, _DP):.6f}"
            _ids.append(_seen.setdefault(_key, len(_seen)))
        _n_node = len(_ids)
        _incidence: dict = {}
        for _face in _conn:
            _nodes: list = []
            for _raw in _face:
                _index = int(_raw)
                if not 0 <= _index < _n_node:
                    continue
                _node = _ids[_index]
                if not _nodes or _nodes[-1] != _node:
                    _nodes.append(_node)
            if len(_nodes) > 1 and _nodes[0] == _nodes[-1]:
                _nodes.pop()
            if len(_nodes) < 3:
                continue
            for _index, _node in enumerate(_nodes):
                _other = _nodes[(_index + 1) % len(_nodes)]
                _edge = (min(_node, _other), max(_node, _other))
                _incidence[_edge] = _incidence.get(_edge, 0) + 1
        _cov["closed"] = bool(_incidence) and all(
            _count == 2 for _count in _incidence.values()
        )
        return _cov

    if file_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(file_path.split(":")[1]))
    elif os.path.splitext(file_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(file_path, backend="geopandas")
    else:
        grid = ux.open_grid(file_path)

    areas = grid.face_areas
    # None (not a fabricated "m^2" default) when the grid carries no units
    # attribute at all -- inventing a label the source file never provided
    # is exactly the silent-metadata failure this server's guardrails exist
    # to prevent, so an absent attribute must surface as absent.
    area_attrs = getattr(areas, "attrs", {}) or {}
    units = area_attrs.get("units")
    values = areas.values if hasattr(areas, "values") else np.asarray(areas)
    steradians = float(np.sum(values))

    return {
        "total_area": steradians,
        "mean_area": float(np.mean(values)),
        "min_area": float(np.min(values)),
        "max_area": float(np.max(values)),
        "area_units": units,
        "n_face": int(grid.n_face),
        # Measured on the unit sphere, before any radius the caller applies
        # locally -- the same place compute_area_stats attaches it.
        "mesh_coverage": _mesh_coverage(grid, steradians),
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
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
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    else:
        uxds = ux.open_dataset(grid_path, data_path)

    face_dims = {"n_face", "nCells"}
    node_dims = {"n_node", "nVertices"}
    edge_dims = {"n_edge", "nEdges"}

    var_names = [variable_name] if variable_name else list(uxds.keys())

    if variable_name and variable_name not in uxds:
        raise ValueError(f"Variable '{variable_name}' not found in dataset")

    variables = []

    def _jsonable(value: Any) -> Any:
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(item) for item in value]
        return value

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
                "attrs": _jsonable(dict(var.attrs)),
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
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
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

    if grid_path.lower().startswith("healpix:"):
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
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
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
    level_index: int = 0,
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
    time_index : int
        Index along a time-like dimension.
    level_index : int
        Index along a vertical dimension. Independent of ``time_index``:
        applying one to the other silently plots the wrong slice.

    Returns
    -------
    dict
        - png_b64: base64-encoded PNG string
        - image_size_bytes: size of the PNG
        - variable_name: plotted variable name
        - reduced_dims: which non-face dimension was collapsed, and at what
          index -- a PNG cannot say which slice it shows
        - grid_info: n_face, n_node, n_edge
    """
    import base64
    import io

    import matplotlib

    matplotlib.use("Agg")
    import os

    import matplotlib.pyplot as plt
    import uxarray as ux
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
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

    # Mirrors domain.dims.face_slice_selection. Kept inline because this
    # function is serialized and shipped to a Globus Compute endpoint that has
    # no uxarray_mcp install to import from.
    #
    # ``time_index`` selects a time axis and nothing else: applying it to a
    # vertical axis returns level 3 when the caller asked for time step 3.
    _LEVEL_EXACT = {"lev", "level", "levels", "plev", "z", "nvertlevels"}
    _LEVEL_SUBSTR = ("lev", "depth", "height", "altitude", "isobaric")
    selection = {}
    reduced_dims = {}
    for dim in uxda.dims:
        if dim in face_dims:
            continue
        size = int(uxda.sizes[dim])
        if size == 1:
            selection[dim] = 0
            continue
        name = str(dim).lower()
        if "time" in name:
            kind, index = "time", time_index
        elif name in _LEVEL_EXACT or any(s in name for s in _LEVEL_SUBSTR):
            kind, index = "level", level_index
        else:
            kind, index = "other", 0
        selection[dim] = index
        reduced_dims[str(dim)] = {"kind": kind, "index": index, "size": size}
    if selection:
        uxda = uxda.isel(**selection)

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
    # Mirrors domain.plotting._layout_with_colorbar: after the resize the
    # HoloViews colorbar axes sits over the map and tight_layout does not
    # move it, so the two are laid out by hand.
    _axes = list(fig.axes)
    if len(_axes) < 2:
        fig.tight_layout()
    else:
        _axes[0].set_position([0.08, 0.12, 0.76, 0.80])
        for _cax in _axes[1:]:
            _cax.set_position([0.87, 0.12, 0.025, 0.80])

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
        "reduced_dims": reduced_dims,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }


def remote_temporal_mean_map(
    grid_path: str,
    data_paths: list,
    variable_name: str,
    lon_bounds: Optional[list] = None,
    lat_bounds: Optional[list] = None,
    level_index: int = 0,
    scale_factor: float = 1.0,
    units_label: Optional[str] = None,
    region_name: str = "",
    width: int = 900,
    height: int = 520,
    cmap: str = "viridis",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    title: Optional[str] = None,
    geography: bool = True,
) -> Dict[str, Any]:
    """Average a variable over time across many files, cut to a box, and draw it.

    The three steps are one function because splitting them defeats the
    point. ``temporal_mean`` alone cannot reach a facility-only path, and a
    mean computed on the submitter would have to pull every input file over
    the wire; here the whole reduction happens on the worker and only the
    PNG plus a few summary numbers come back.

    The bounding box is applied *before* the time average, so a regional
    request reads the faces it asked for rather than the globe. On a mesh
    where the region is a small fraction of the faces this is the
    difference between a demo that finishes and one that does not.

    Parameters
    ----------
    grid_path : str
        Mesh file on the worker filesystem (or ``healpix:<zoom>``).
    data_paths : list
        One or more data files to average across, in time order. A bare
        string is accepted and treated as a single-element list.
    variable_name : str
        Face-centered variable to average.
    lon_bounds, lat_bounds : list | None
        ``[min, max]`` degrees. Both must be given to subset; either alone
        is refused rather than half-applied.
    level_index : int
        Index along a vertical dimension. Never applied to a time axis.
    scale_factor : float
        Multiplied into the mean after averaging, for unit conversion
        (CAM ``PRECT`` is m/s; 86400000.0 gives mm/day).
    units_label : str | None
        Units for the colorbar. Records what ``scale_factor`` converted to,
        since the number alone cannot say.
    region_name : str
        Human-readable region label for the default title.
    width, height : int
        PNG size in pixels.
    cmap : str
        Matplotlib colormap name.
    vmin, vmax : float | None
        Color limits, in the units produced by ``scale_factor``.
    title : str | None
        Overrides the generated title.
    geography : bool
        Draw coastlines, national borders and state lines under the data.
        The axes are plain degrees, which is what Natural Earth's geometries
        are in, so they overlay without a projection. Skipped without
        comment if cartopy or its data are missing on the worker; the
        result says which happened.

    Returns
    -------
    dict
        - png_b64, image_size_bytes: the rendered map
        - geography: how many coastline/border/state paths were drawn, or
          why none were
        - variable_name, units, scale_factor: what was drawn, in what units
        - n_files, n_time_steps, time_start, time_end: what was averaged
        - reduced_dims: the time dims collapsed and the level index held
        - n_face_total, n_face_subset, fraction_of_mesh: subset coverage
        - value_stats: min/mean/max of the mean field, for sanity checks
        - grid_info: n_face, n_node, n_edge of the *subset* grid
    """
    import base64
    import io
    import os

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import uxarray as ux

    if isinstance(data_paths, str):
        data_paths = [data_paths]
    data_paths = [str(p) for p in (data_paths or [])]
    if not data_paths:
        raise ValueError("remote_temporal_mean_map requires at least one data path.")
    missing = [p for p in data_paths if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} of {len(data_paths)} data paths are not readable "
            f"on the worker; first missing: {missing[0]}"
        )
    if (lon_bounds is None) != (lat_bounds is None):
        raise ValueError(
            "Subsetting needs both lon_bounds and lat_bounds; got only one. "
            "Pass both, or neither for the whole mesh."
        )

    # open_mfdataset takes a grid *path*, not a Grid object -- handing it one
    # fails with the Grid's repr as the error message. Only the two synthetic
    # grid spellings need the object, and those get the dataset attached by
    # hand, exactly as remote_plot_variable does.
    _spec = grid_path.lower()
    if _spec.startswith("healpix:") or os.path.splitext(_spec)[1] in [
        ".shp",
        ".geojson",
    ]:
        import xarray as xr

        if _spec.startswith("healpix:"):
            _grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        else:
            _grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(
            xr.open_mfdataset(data_paths, combine="by_coords"), uxgrid=_grid
        )
    else:
        uxds = ux.open_mfdataset(grid_path, data_paths, combine="by_coords")
    n_face_total = int(uxds.uxgrid.n_face)

    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. "
            f"Available: {list(uxds.data_vars.keys())}"
        )
    uxda = uxds[variable_name]

    face_dims = {"n_face", "nCells"}
    if not any(d in face_dims for d in uxda.dims):
        raise ValueError(f"Variable '{variable_name}' is not face-centered.")

    # Same split as remote_plot_variable: a time index and a level index
    # reach different axes, and mixing them silently averages the wrong one.
    _LEVEL_EXACT = {"lev", "level", "levels", "plev", "z", "nvertlevels"}
    _LEVEL_SUBSTR = ("lev", "depth", "height", "altitude", "isobaric")
    level_sel = {}
    time_dims = []
    reduced_dims: Dict[str, Any] = {}
    for dim in uxda.dims:
        if dim in face_dims:
            continue
        size = int(uxda.sizes[dim])
        name = str(dim).lower()
        if "time" in name:
            time_dims.append(str(dim))
            reduced_dims[str(dim)] = {"kind": "time", "how": "mean", "size": size}
            continue
        if size == 1:
            level_sel[dim] = 0
            continue
        if name in _LEVEL_EXACT or any(s in name for s in _LEVEL_SUBSTR):
            level_sel[dim] = level_index
            reduced_dims[str(dim)] = {
                "kind": "level",
                "index": level_index,
                "size": size,
            }
        else:
            level_sel[dim] = 0
            reduced_dims[str(dim)] = {"kind": "other", "index": 0, "size": size}
    if not time_dims:
        raise ValueError(
            f"Variable '{variable_name}' has no time dimension to average; "
            f"dims are {list(uxda.dims)}."
        )
    if level_sel:
        uxda = uxda.isel(**level_sel)

    n_time_steps = 1
    for d in time_dims:
        n_time_steps *= int(uxda.sizes[d])
    time_start = time_end = None
    for d in time_dims:
        if d in uxda.coords:
            _tv = uxda[d].values
            if len(_tv):
                time_start, time_end = str(_tv[0]), str(_tv[-1])
            break

    # Cut to the region before averaging: the mean then touches only the
    # faces that end up in the picture.
    subset_applied = False
    if lon_bounds is not None and lat_bounds is not None:
        uxda = uxda.subset.bounding_box(
            lon_bounds=[float(v) for v in lon_bounds],
            lat_bounds=[float(v) for v in lat_bounds],
        )
        subset_applied = True
        if int(uxda.uxgrid.n_face) == 0:
            raise ValueError(
                f"Bounding box lon={lon_bounds} lat={lat_bounds} selects no "
                f"faces of this {n_face_total}-face mesh. Longitudes here may "
                f"use a different convention (0..360 vs -180..180)."
            )

    mean_da = uxda.mean(dim=time_dims)
    if hasattr(mean_da, "compute"):
        mean_da = mean_da.compute()
    if scale_factor != 1.0:
        _scaled = mean_da * float(scale_factor)
        # Arithmetic can hand back a plain xarray object; the grid has to be
        # reattached or .plot.polygons has no mesh to draw on.
        if not hasattr(_scaled, "uxgrid") or _scaled.uxgrid is None:
            _scaled = ux.UxDataArray(_scaled, uxgrid=mean_da.uxgrid)
        mean_da = _scaled
    sub_grid = mean_da.uxgrid
    n_face_subset = int(sub_grid.n_face)

    label = variable_name if not units_label else f"{variable_name} ({units_label})"
    mean_da = mean_da.rename(label)

    vals = np.asarray(mean_da.values, dtype="float64")
    finite = vals[np.isfinite(vals)]
    value_stats = {
        "min": float(finite.min()) if finite.size else None,
        "mean": float(finite.mean()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "n_faces": int(vals.size),
        "n_nonfinite": int(vals.size - finite.size),
    }

    import holoviews as hv

    hv.extension("matplotlib")

    dpi = 100
    kwargs: Dict[str, Any] = {"backend": "matplotlib", "cmap": cmap}
    if vmin is not None or vmax is not None:
        kwargs["clim"] = (
            float(vmin) if vmin is not None else float(np.nanmin(vals)),
            float(vmax) if vmax is not None else float(np.nanmax(vals)),
        )

    element = mean_da.plot.polygons(**kwargs)
    renderer = hv.Store.renderers["matplotlib"]
    plot = renderer.get_plot(element)
    fig = plot.state
    fig.set_size_inches(width / dpi, height / dpi)
    fig.set_dpi(dpi)

    if title is None:
        _span = ""
        if time_start and time_end:
            _span = f" {time_start[:10]} to {time_end[:10]}"
        _where = f" over {region_name}" if region_name else ""
        title = f"Mean {label}{_where},{_span} ({n_time_steps} steps)"
    fig.axes[0].set_title(title)

    # Geography, drawn as plain paths rather than through a projection: the
    # polygons were plotted in degrees, and Natural Earth's geometries are in
    # degrees, so the two line up without cartopy owning the axes. A map of a
    # region with no coastline on it is hard to check and easy to misread.
    geo_info: Dict[str, Any] = {"drawn": False}
    if geography:
        try:
            import cartopy.feature as cfeature
            from matplotlib.collections import LineCollection

            _ax = fig.axes[0]
            _xlim, _ylim = _ax.get_xlim(), _ax.get_ylim()
            counts = {}
            for key, category, feature_name, lw, color in (
                ("coastlines", "physical", "coastline", 0.8, "#111111"),
                (
                    "borders",
                    "cultural",
                    "admin_0_boundary_lines_land",
                    0.6,
                    "#333333",
                ),
                (
                    "states",
                    "cultural",
                    "admin_1_states_provinces_lines",
                    0.4,
                    "#555555",
                ),
            ):
                segments = []
                for geom in cfeature.NaturalEarthFeature(
                    category, feature_name, "50m"
                ).geometries():
                    parts = getattr(geom, "geoms", None) or [geom]
                    for part in parts:
                        coords = getattr(part, "coords", None)
                        if coords is None:
                            continue
                        pts = list(coords)
                        if len(pts) > 1:
                            segments.append(pts)
                if segments:
                    _ax.add_collection(
                        LineCollection(
                            segments,
                            linewidths=lw,
                            colors=color,
                            zorder=5,
                        )
                    )
                counts[key] = len(segments)
            # add_collection re-autoscales to the whole world; the box the
            # caller asked for is the view that matters.
            _ax.set_xlim(_xlim)
            _ax.set_ylim(_ylim)
            geo_info = {"drawn": True, **counts}
        except Exception as exc:  # cartopy absent, or its data not cached
            geo_info = {"drawn": False, "reason": f"{type(exc).__name__}: {exc}"}

    # Mirrors remote_plot_variable: after the resize the HoloViews colorbar
    # sits over the map and tight_layout will not move it.
    _axes = list(fig.axes)
    if len(_axes) < 2:
        fig.tight_layout()
    else:
        _axes[0].set_position([0.08, 0.12, 0.76, 0.80])
        for _cax in _axes[1:]:
            _cax.set_position([0.87, 0.12, 0.025, 0.80])

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError("Rendered temporal mean map is empty.")

    return {
        "png_b64": base64.b64encode(png_bytes).decode("utf-8"),
        "image_size_bytes": len(png_bytes),
        "variable_name": variable_name,
        "units": units_label,
        "scale_factor": float(scale_factor),
        "n_files": len(data_paths),
        "n_time_steps": int(n_time_steps),
        "time_start": time_start,
        "time_end": time_end,
        "reduced_dims": reduced_dims,
        "subset_applied": subset_applied,
        "lon_bounds": list(lon_bounds) if lon_bounds is not None else None,
        "lat_bounds": list(lat_bounds) if lat_bounds is not None else None,
        "n_face_total": n_face_total,
        "n_face_subset": n_face_subset,
        "fraction_of_mesh": (n_face_subset / n_face_total) if n_face_total else None,
        "value_stats": value_stats,
        "geography": geo_info,
        "grid_info": {
            "n_face": n_face_subset,
            "n_node": int(sub_grid.n_node),
            "n_edge": int(sub_grid.n_edge),
        },
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
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
    time_index: int = 0,
    level_index: int = 0,
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
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
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

    # ``latitudes`` replaces the face axis, which is not axis 0 when the
    # variable has a time dimension; selecting positionally would plot time
    # indices as degrees.  Inlined rather than shared because module-level
    # helpers do not survive AllCodeStrategies serialization.
    _coord = "latitudes" if "latitudes" in result.coords else result.dims[-1]
    latitudes = result.coords[_coord].values.tolist()
    # Mirrors domain.dims.face_slice_selection. Inlined because module-level
    # helpers do not survive AllCodeStrategies serialization -- change both
    # together; tests/test_physical_fixtures.py pins them to each other.
    _LEVEL_EXACT = {"lev", "level", "levels", "plev", "z", "nvertlevels"}
    _LEVEL_SUBSTR = ("lev", "depth", "height", "altitude", "isobaric")
    _reduced = {}
    _sel = {}
    for _d in result.dims:
        if _d == _coord:
            continue
        _n = int(result.sizes[_d])
        if _n == 1:
            _sel[_d] = 0
            continue
        _name = str(_d).lower()
        if "time" in _name:
            _k, _i = "time", time_index
        elif _name in _LEVEL_EXACT or any(_s in _name for _s in _LEVEL_SUBSTR):
            _k, _i = "level", level_index
        else:
            _k, _i = "other", 0
        _sel[_d] = _i
        _reduced[str(_d)] = {"kind": _k, "index": _i, "size": _n}
    if _sel:
        result = result.isel(**_sel)
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
        "reduced_dims": _reduced,
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }


def remote_calculate_zonal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
    time_index: int = 0,
    level_index: int = 0,
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
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
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

    # Look the coordinate up by name: with a time dimension present the
    # reduced latitude axis is the trailing one, not ``dims[0]``.  Any other
    # surviving axis (vertical level, ensemble member) is collapsed to one
    # index and reported, so a single level is never mistaken for the whole
    # answer.  Inlined because module-level helpers do not survive
    # AllCodeStrategies serialization.
    _coord = "latitudes" if "latitudes" in result.coords else result.dims[-1]
    latitudes = result.coords[_coord].values.tolist()
    # Mirrors domain.dims.face_slice_selection. Inlined because module-level
    # helpers do not survive AllCodeStrategies serialization -- change both
    # together; tests/test_physical_fixtures.py pins them to each other.
    _LEVEL_EXACT = {"lev", "level", "levels", "plev", "z", "nvertlevels"}
    _LEVEL_SUBSTR = ("lev", "depth", "height", "altitude", "isobaric")
    _reduced = {}
    _sel = {}
    for _d in result.dims:
        if _d == _coord:
            continue
        _n = int(result.sizes[_d])
        if _n == 1:
            _sel[_d] = 0
            continue
        _name = str(_d).lower()
        if "time" in _name:
            _k, _i = "time", time_index
        elif _name in _LEVEL_EXACT or any(_s in _name for _s in _LEVEL_SUBSTR):
            _k, _i = "level", level_index
        else:
            _k, _i = "other", 0
        _sel[_d] = _i
        _reduced[str(_d)] = {"kind": _k, "index": _i, "size": _n}
    if _sel:
        result = result.isel(**_sel)

    # Same bin-coverage measurement as the local path, inlined because the
    # worker cannot import uxarray_mcp. Bins the caller chose need not touch
    # the mesh, and an all-NaN profile is shaped exactly like an answer.
    _np = __import__("numpy")
    _profile = _np.asarray(result.values.tolist(), dtype=float)
    _src = _np.asarray(var.values, dtype=float)
    _n_bins = int(_profile.size)
    _n_filled = int(_np.isfinite(_profile).sum())
    _src_missing = bool(_src.size) and bool((~_np.isfinite(_src)).any())
    if _n_filled == _n_bins:
        _cause = "none"
    elif not _src_missing:
        _cause = "bins_miss_mesh"
    else:
        _cause = "ambiguous"
    _profile_coverage = {
        "n_bins": _n_bins,
        "n_bins_filled": _n_filled,
        "source_has_missing": _src_missing,
        "cause": _cause,
    }

    return {
        "variable_name": variable_name,
        "latitudes": latitudes,
        "zonal_mean_values": result.values.tolist(),
        "conservative": conservative,
        "profile_coverage": _profile_coverage,
        "reduced_dims": _reduced,
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
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

    if grid_path.lower().startswith("healpix:"):
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
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": ux_version,
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
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


def remote_yac_remap_smoke(yac_prefix: str = "") -> Dict[str, Any]:
    """Smoke-test YAC's availability on the remote worker.

    Runs the native YAC import/remap in a worker-side subprocess. Some YAC/MPI
    builds can terminate the importing process when their runtime library path
    is incomplete; keeping the import in a child process lets the Globus worker
    return structured diagnostics instead of disappearing as ``WorkerLost``.

    ``yac_prefix`` points the probe at an install other than the one the
    endpoint's ``worker_init`` bakes in, which is how a freshly built YAC gets
    confirmed before anything is reconfigured to use it. Other ``yac-*``
    prefixes are dropped from both search paths rather than merely
    out-prioritised: prepending alone still leaves the old ``libyac`` reachable
    to the dynamic loader, so a broken new build could pass on the old one's
    libraries.

    The function is self-contained and serialised via AllCodeStrategies so the
    Python 3.13/3.11 mismatch between local SDK and worker doesn't bite.
    """
    import glob
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

    env = os.environ.copy()
    prefix_applied = None
    if yac_prefix:
        prefix = os.path.abspath(os.path.expanduser(yac_prefix))
        site = sorted(
            glob.glob(os.path.join(prefix, "lib", "python*", "site-packages"))
        )

        def _repoint(var, wanted):
            kept = [
                p
                for p in env.get(var, "").split(os.pathsep)
                if p and (os.sep + "yac-") not in p
            ]
            env[var] = os.pathsep.join(wanted + kept)

        _repoint("PYTHONPATH", site)
        _repoint("LD_LIBRARY_PATH", [os.path.join(prefix, "lib")])
        prefix_applied = {
            "prefix": prefix,
            "site_packages": site,
            "exists": os.path.isdir(prefix),
            "pythonpath": env["PYTHONPATH"],
            "ld_library_path": env["LD_LIBRARY_PATH"],
        }

    try:
        command = [sys.executable, "-c", textwrap.dedent(code)]
        launch_mode = "direct"
        if os.environ.get("SLURM_JOB_ID") and shutil.which("srun"):
            command = ["srun", "--ntasks", "1", *command]
            launch_mode = "srun"
        proc = subprocess.run(
            command,
            env=env,
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
        "yac_prefix_override": prefix_applied,
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(__import__("uxarray"), "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "pbs_job_id": os.environ.get("PBS_JOBID"),
        },
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
    grid_path: str,
    data_path: str,
    variable_name: str,
    scale_by_radius: bool = True,
    time_index: int = 0,
    level_index: int = 0,
    sphere_radius: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute the spatial gradient of a face-centered scalar field on HPC."""
    import inspect as _inspect
    import os

    import numpy as np
    import uxarray as ux
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
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

    # Select a single time/level slice so gradient() sees 1-D face-centered
    # data, mirroring the local domain.vector_calc._reduce_to_face behavior.
    # Inlined (not imported) since this function is serialized whole and
    # shipped to Globus Compute workers.
    _face_dims = {"n_face", "nCells"}
    # Mirrors domain.dims.classify_dim. An exact-name list kept missing real
    # spellings (``n_level``, ``nlev``, ``num_levels``), which silently pinned
    # those axes to index 0 here while the local path honored level_index --
    # the same request answering differently by venue. Inlined because
    # module-level helpers do not survive AllCodeStrategies serialization;
    # change both together.
    _LEVEL_EXACT = {"lev", "level", "levels", "plev", "z", "nvertlevels"}
    _LEVEL_SUBSTR = ("lev", "depth", "height", "altitude", "isobaric")
    _extra = [d for d in var.dims if d not in _face_dims]
    # Size-1 axes collapse without being reported: nothing was chosen over an
    # alternative, so there is nothing for the caller to second-guess.
    _reduced = {}
    if _extra:
        _sel = {}
        for _d in _extra:
            _n = int(var.sizes[_d])
            if _n == 1:
                _sel[_d] = 0
                continue
            _dname = str(_d).lower()
            if "time" in _dname:
                _k, _i = "time", time_index
            elif _dname in _LEVEL_EXACT or any(_s in _dname for _s in _LEVEL_SUBSTR):
                _k, _i = "level", level_index
            else:
                _k, _i = "other", 0
            _sel[_d] = _i
            _reduced[str(_d)] = {"kind": _k, "index": _i, "size": _n}
        if _sel:
            var = var.isel(**_sel)

    # Honor scale_by_radius when the worker's UXarray supports it; otherwise
    # fall back to the unit-sphere call so older workers keep working.
    # Capture any UXarray-internal UserWarning (e.g. missing sphere_radius
    # silently falling back to unit-sphere output) so it reaches the
    # structured result and _provenance.warnings, not just worker stderr.
    import warnings as _warnings_module

    # Mirrors domain.vector_calc._apply_sphere_radius: a caller-supplied radius
    # is attached to the grid so UXarray can scale, and where the radius came
    # from is reported. Inlined because the worker has no uxarray_mcp.
    _declared = "sphere_radius" in uxds.uxgrid._ds.attrs
    if sphere_radius is not None:
        if float(sphere_radius) <= 0:
            raise ValueError("sphere_radius must be a positive number of metres.")
        uxds.uxgrid.sphere_radius = float(sphere_radius)
        _radius_basis = {
            "sphere_radius": float(sphere_radius),
            "radius_source": "argument",
        }
    elif _declared:
        _radius_basis = {
            "sphere_radius": float(uxds.uxgrid.sphere_radius),
            "radius_source": "grid",
        }
    else:
        _radius_basis = {"sphere_radius": None, "radius_source": "none"}

    applied_scale = False
    with _warnings_module.catch_warnings(record=True) as _caught:
        _warnings_module.simplefilter("always")
        if "scale_by_radius" in _inspect.signature(var.gradient).parameters:
            grad = var.gradient(scale_by_radius=scale_by_radius)
            applied_scale = bool(scale_by_radius)
        else:
            grad = var.gradient()
        _seen: set = set()
        uxarray_warnings = []
        for _w in _caught:
            _msg = str(_w.message)
            if _msg not in _seen:
                _seen.add(_msg)
                uxarray_warnings.append(_msg)
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
        "scale_by_radius": applied_scale,
        "radius_basis": _radius_basis,
        "interpretation": "zonal (d/dx) and meridional (d/dy) components of the gradient",
        "component_warnings": uxarray_warnings,
        "reduced_dims": _reduced,
        "scientific_status": {
            "status": "warning" if uxarray_warnings else "complete",
            "physically_interpretable": not uxarray_warnings,
            "warning_codes": (
                ["SPHERE_RADIUS_UNAVAILABLE"] if uxarray_warnings else []
            ),
            "warnings": uxarray_warnings,
        },
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }


def remote_calculate_curl(
    grid_path: str,
    data_path: str,
    u_variable: str,
    v_variable: str,
    scale_by_radius: bool = True,
    time_index: int = 0,
    level_index: int = 0,
    sphere_radius: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute relative vorticity (curl) of a 2-D wind field on HPC.

    zeta = dv/dx - du/dy
    """
    import inspect as _inspect
    import os

    import numpy as np
    import uxarray as ux
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
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

    # Select a single time/level slice so curl() sees 1-D face-centered data,
    # mirroring the local domain.vector_calc._reduce_to_face behavior.
    # Inlined (not imported) since this function is serialized whole and
    # shipped to Globus Compute workers.
    _face_dims = {"n_face", "nCells"}
    # Mirrors domain.dims.classify_dim. An exact-name list kept missing real
    # spellings (``n_level``, ``nlev``, ``num_levels``), which silently pinned
    # those axes to index 0 here while the local path honored level_index --
    # the same request answering differently by venue. Inlined because
    # module-level helpers do not survive AllCodeStrategies serialization;
    # change both together.
    _LEVEL_EXACT = {"lev", "level", "levels", "plev", "z", "nvertlevels"}
    _LEVEL_SUBSTR = ("lev", "depth", "height", "altitude", "isobaric")
    # Both components are sliced the same way whenever they share dims, which
    # is the normal case; v's entry overwrites u's only where they differ,
    # matching the local {**u_reduced, **v_reduced} merge.
    _reduced = {}
    for _which, _var in (("u", u), ("v", v)):
        _extra = [d for d in _var.dims if d not in _face_dims]
        if not _extra:
            continue
        _sel = {}
        for _d in _extra:
            _n = int(_var.sizes[_d])
            if _n == 1:
                _sel[_d] = 0
                continue
            _dname = str(_d).lower()
            if "time" in _dname:
                _k, _i = "time", time_index
            elif _dname in _LEVEL_EXACT or any(_s in _dname for _s in _LEVEL_SUBSTR):
                _k, _i = "level", level_index
            else:
                _k, _i = "other", 0
            _sel[_d] = _i
            _reduced[str(_d)] = {"kind": _k, "index": _i, "size": _n}
        if not _sel:
            continue
        if _which == "u":
            u = u.isel(**_sel)
        else:
            v = v.isel(**_sel)

    # Soft semantic guardrail: curl is only physical for genuine vector
    # components. Warn (do not block) on same-field or non-velocity inputs.
    component_warnings = []
    warning_codes = []
    if u_variable == v_variable:
        warning_codes.append("VECTOR_COMPONENTS_IDENTICAL")
        component_warnings.append(
            f"curl: u_variable and v_variable are the same field "
            f"('{u_variable}'); result is a mathematical artifact, not a "
            "physical curl."
        )
    _u_units = str((getattr(u, "attrs", {}) or {}).get("units", "")).strip().lower()
    _v_units = str((getattr(v, "attrs", {}) or {}).get("units", "")).strip().lower()
    _vel_hints = ("m/s", "m s-1", "m s^-1", "cm/s", "km/h", "pa/s", "kg/m2/s")
    if not any(h in _u_units or h in _v_units for h in _vel_hints):
        warning_codes.append("VECTOR_UNITS_UNVERIFIED")
        component_warnings.append(
            f"curl: neither component has a velocity-like 'units' attribute "
            f"(u='{_u_units or 'unset'}', v='{_v_units or 'unset'}'); verify "
            "inputs are genuine vector components before interpreting."
        )

    # Capture any UXarray-internal UserWarning (e.g. missing sphere_radius
    # silently falling back to unit-sphere output) so it reaches the
    # structured result and _provenance.warnings, not just worker stderr.
    import warnings as _warnings_module

    # Mirrors domain.vector_calc._apply_sphere_radius: a caller-supplied radius
    # is attached to the grid so UXarray can scale, and where the radius came
    # from is reported. Inlined because the worker has no uxarray_mcp.
    _declared = "sphere_radius" in uxds.uxgrid._ds.attrs
    if sphere_radius is not None:
        if float(sphere_radius) <= 0:
            raise ValueError("sphere_radius must be a positive number of metres.")
        uxds.uxgrid.sphere_radius = float(sphere_radius)
        _radius_basis = {
            "sphere_radius": float(sphere_radius),
            "radius_source": "argument",
        }
    elif _declared:
        _radius_basis = {
            "sphere_radius": float(uxds.uxgrid.sphere_radius),
            "radius_source": "grid",
        }
    else:
        _radius_basis = {"sphere_radius": None, "radius_source": "none"}

    applied_scale = False
    with _warnings_module.catch_warnings(record=True) as _caught:
        _warnings_module.simplefilter("always")
        if "scale_by_radius" in _inspect.signature(u.curl).parameters:
            result = u.curl(v, scale_by_radius=scale_by_radius)
            applied_scale = bool(scale_by_radius)
        else:
            result = u.curl(v)
            if scale_by_radius:
                component_warnings.append(
                    "Worker UXarray does not support scale_by_radius; returned "
                    "the unit-sphere curl."
                )
                warning_codes.append("SCALE_BY_RADIUS_UNSUPPORTED")
        _seen: set = set()
        for _w in _caught:
            _msg = str(_w.message)
            if _msg not in _seen:
                _seen.add(_msg)
                component_warnings.append(_msg)
                warning_codes.append("SPHERE_RADIUS_UNAVAILABLE")
                applied_scale = False
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
        "scale_by_radius": applied_scale,
        "radius_basis": _radius_basis,
        "stats": stats,
        "component_warnings": component_warnings,
        "reduced_dims": _reduced,
        "scientific_status": {
            "status": "warning" if component_warnings else "complete",
            "physically_interpretable": not component_warnings,
            "physical_scaling_requested": bool(scale_by_radius),
            "physical_scaling_applied": bool(applied_scale),
            "warning_codes": warning_codes,
            "warnings": component_warnings,
        },
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }


def remote_calculate_divergence(
    grid_path: str,
    data_path: str,
    u_variable: str,
    v_variable: str,
    scale_by_radius: bool = True,
    time_index: int = 0,
    level_index: int = 0,
    sphere_radius: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute horizontal divergence of a 2-D vector field on HPC.

    divergence = du/dx + dv/dy
    """
    import inspect as _inspect
    import os

    import numpy as np
    import uxarray as ux
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
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

    # Select a single time/level slice so divergence() sees 1-D face-centered
    # data, mirroring the local domain.vector_calc._reduce_to_face behavior.
    # Inlined (not imported) since this function is serialized whole and
    # shipped to Globus Compute workers.
    _face_dims = {"n_face", "nCells"}
    # Mirrors domain.dims.classify_dim. An exact-name list kept missing real
    # spellings (``n_level``, ``nlev``, ``num_levels``), which silently pinned
    # those axes to index 0 here while the local path honored level_index --
    # the same request answering differently by venue. Inlined because
    # module-level helpers do not survive AllCodeStrategies serialization;
    # change both together.
    _LEVEL_EXACT = {"lev", "level", "levels", "plev", "z", "nvertlevels"}
    _LEVEL_SUBSTR = ("lev", "depth", "height", "altitude", "isobaric")
    # Both components are sliced the same way whenever they share dims, which
    # is the normal case; v's entry overwrites u's only where they differ,
    # matching the local {**u_reduced, **v_reduced} merge.
    _reduced = {}
    for _which, _var in (("u", u), ("v", v)):
        _extra = [d for d in _var.dims if d not in _face_dims]
        if not _extra:
            continue
        _sel = {}
        for _d in _extra:
            _n = int(_var.sizes[_d])
            if _n == 1:
                _sel[_d] = 0
                continue
            _dname = str(_d).lower()
            if "time" in _dname:
                _k, _i = "time", time_index
            elif _dname in _LEVEL_EXACT or any(_s in _dname for _s in _LEVEL_SUBSTR):
                _k, _i = "level", level_index
            else:
                _k, _i = "other", 0
            _sel[_d] = _i
            _reduced[str(_d)] = {"kind": _k, "index": _i, "size": _n}
        if not _sel:
            continue
        if _which == "u":
            u = u.isel(**_sel)
        else:
            v = v.isel(**_sel)

    # Soft semantic guardrail (mirrors curl): warn on same-field or
    # non-velocity inputs; do not block.
    component_warnings = []
    warning_codes = []
    if u_variable == v_variable:
        warning_codes.append("VECTOR_COMPONENTS_IDENTICAL")
        component_warnings.append(
            f"divergence: u_variable and v_variable are the same field "
            f"('{u_variable}'); result is a mathematical artifact, not a "
            "physical divergence."
        )
    _u_units = str((getattr(u, "attrs", {}) or {}).get("units", "")).strip().lower()
    _v_units = str((getattr(v, "attrs", {}) or {}).get("units", "")).strip().lower()
    _vel_hints = ("m/s", "m s-1", "m s^-1", "cm/s", "km/h", "pa/s", "kg/m2/s")
    if not any(h in _u_units or h in _v_units for h in _vel_hints):
        warning_codes.append("VECTOR_UNITS_UNVERIFIED")
        component_warnings.append(
            f"divergence: neither component has a velocity-like 'units' "
            f"attribute (u='{_u_units or 'unset'}', v='{_v_units or 'unset'}'); "
            "verify inputs are genuine vector components before interpreting."
        )

    import warnings as _warnings_module

    # Mirrors domain.vector_calc._apply_sphere_radius: a caller-supplied radius
    # is attached to the grid so UXarray can scale, and where the radius came
    # from is reported. Inlined because the worker has no uxarray_mcp.
    _declared = "sphere_radius" in uxds.uxgrid._ds.attrs
    if sphere_radius is not None:
        if float(sphere_radius) <= 0:
            raise ValueError("sphere_radius must be a positive number of metres.")
        uxds.uxgrid.sphere_radius = float(sphere_radius)
        _radius_basis = {
            "sphere_radius": float(sphere_radius),
            "radius_source": "argument",
        }
    elif _declared:
        _radius_basis = {
            "sphere_radius": float(uxds.uxgrid.sphere_radius),
            "radius_source": "grid",
        }
    else:
        _radius_basis = {"sphere_radius": None, "radius_source": "none"}

    applied_scale = False
    with _warnings_module.catch_warnings(record=True) as _caught:
        _warnings_module.simplefilter("always")
        if "scale_by_radius" in _inspect.signature(u.divergence).parameters:
            result = u.divergence(v, scale_by_radius=scale_by_radius)
            applied_scale = bool(scale_by_radius)
        else:
            result = u.divergence(v)
            if scale_by_radius:
                component_warnings.append(
                    "Worker UXarray does not support scale_by_radius; returned "
                    "the unit-sphere divergence."
                )
                warning_codes.append("SCALE_BY_RADIUS_UNSUPPORTED")
        for _warning in _caught:
            _message = str(_warning.message)
            if _message not in component_warnings:
                component_warnings.append(_message)
                warning_codes.append("SPHERE_RADIUS_UNAVAILABLE")
                applied_scale = False
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
        "scale_by_radius": applied_scale,
        "radius_basis": _radius_basis,
        "stats": stats,
        "component_warnings": component_warnings,
        "reduced_dims": _reduced,
        "scientific_status": {
            "status": "warning" if component_warnings else "complete",
            "physically_interpretable": not component_warnings,
            "physical_scaling_requested": bool(scale_by_radius),
            "physical_scaling_applied": bool(applied_scale),
            "warning_codes": warning_codes,
            "warnings": component_warnings,
        },
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }


def remote_calculate_azimuthal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    center_lon: float,
    center_lat: float,
    outer_radius: float,
    radius_step: float,
    time_index: int = 0,
    level_index: int = 0,
) -> Dict[str, Any]:
    """Compute the azimuthal (radial) mean around a centre point on HPC."""
    import os

    import uxarray as ux
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
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
    # ``radius`` replaces the face axis, which is not axis 0 when a time
    # dimension is present.  Other surviving axes are collapsed to one index
    # and reported.  Inlined because module-level helpers do not survive
    # AllCodeStrategies serialization.
    _coord = "radius" if "radius" in result.coords else result.dims[-1]
    radii = result.coords[_coord].values.tolist()
    # Mirrors domain.dims.face_slice_selection. Inlined because module-level
    # helpers do not survive AllCodeStrategies serialization -- change both
    # together; tests/test_physical_fixtures.py pins them to each other.
    _LEVEL_EXACT = {"lev", "level", "levels", "plev", "z", "nvertlevels"}
    _LEVEL_SUBSTR = ("lev", "depth", "height", "altitude", "isobaric")
    _reduced = {}
    _sel = {}
    for _d in result.dims:
        if _d == _coord:
            continue
        _n = int(result.sizes[_d])
        if _n == 1:
            _sel[_d] = 0
            continue
        _name = str(_d).lower()
        if "time" in _name:
            _k, _i = "time", time_index
        elif _name in _LEVEL_EXACT or any(_s in _name for _s in _LEVEL_SUBSTR):
            _k, _i = "level", level_index
        else:
            _k, _i = "other", 0
        _sel[_d] = _i
        _reduced[str(_d)] = {"kind": _k, "index": _i, "size": _n}
    if _sel:
        result = result.isel(**_sel)
    values = result.values.tolist()

    # Same bin-coverage measurement as the local path, inlined because the
    # worker cannot import uxarray_mcp. Bins the caller chose need not touch
    # the mesh, and an all-NaN profile is shaped exactly like an answer.
    _np = __import__("numpy")
    # The ring at radius zero is a point, not a circle, and is NaN by
    # construction; it is left out of the count as in the local path.
    _radii_arr = _np.asarray(radii, dtype=float)
    _degenerate = [i for i, r in enumerate(_radii_arr) if r == 0.0]
    _profile = _np.asarray(
        [v for i, v in enumerate(values) if i not in _degenerate], dtype=float
    )
    _src = _np.asarray(var.values, dtype=float)
    _n_bins = int(_profile.size)
    _n_filled = int(_np.isfinite(_profile).sum())
    _src_missing = bool(_src.size) and bool((~_np.isfinite(_src)).any())
    if _n_filled == _n_bins:
        _cause = "none"
    elif not _src_missing:
        _cause = "bins_miss_mesh"
    else:
        _cause = "ambiguous"
    _profile_coverage = {
        "n_bins": _n_bins,
        "n_bins_filled": _n_filled,
        "source_has_missing": _src_missing,
        "cause": _cause,
        "degenerate_bins_excluded": len(_degenerate),
    }

    return {
        "variable_name": variable_name,
        "center": {"lon": center_lon, "lat": center_lat},
        "outer_radius_deg": outer_radius,
        "radius_step_deg": radius_step,
        "radii_deg": radii,
        "azimuthal_mean_values": values,
        "reduced_dims": _reduced,
        "n_face": int(uxds.uxgrid.n_face),
        "profile_coverage": _profile_coverage,
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }


def remote_grid_facts(
    grid_path: str, data_path: Optional[str] = None
) -> Dict[str, Any]:
    """Return grid topology + variable locations for capability discovery.

    This is the remote half of ``get_capabilities``. It loads the grid (and
    optional dataset) on the HPC worker and returns only the small, picklable
    facts the local report builder needs — never the mesh itself. The local
    ``get_capabilities`` then constructs the full capability report from these
    facts, so the (potentially multi-GB) grid never crosses the network.

    Returns
    -------
    dict
        ``grid_format``, ``n_face``/``n_node``/``n_edge``, and (when
        ``data_path`` is given) ``variables`` — a list of
        ``{name, location}`` where location is faces/nodes/edges/other.
    """
    import os

    import uxarray as ux
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        grid_format = "HEALPix"
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        grid_format = str(getattr(grid, "source_grid_spec", "Unknown"))
    else:
        grid = ux.open_grid(grid_path)
        grid_format = str(getattr(grid, "source_grid_spec", "Unknown"))

    facts: Dict[str, Any] = {
        "grid_format": grid_format,
        "n_face": int(grid.n_face) if hasattr(grid, "n_face") else 0,
        "n_node": int(grid.n_node) if hasattr(grid, "n_node") else 0,
        "n_edge": int(grid.n_edge) if hasattr(grid, "n_edge") else 0,
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }

    if data_path is not None:
        if grid_path.lower().startswith("healpix:") or os.path.splitext(
            grid_path.lower()
        )[1] in [".shp", ".geojson"]:
            uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
        else:
            uxds = ux.open_dataset(grid_path, data_path)

        variables = []
        for var_name in uxds.data_vars:
            variable = uxds[var_name]
            dims = variable.dims
            if any(d in dims for d in ("n_face", "nCells")):
                location = "faces"
            elif any(d in dims for d in ("n_node", "nVertices")):
                location = "nodes"
            elif any(d in dims for d in ("n_edge", "nEdges")):
                location = "edges"
            else:
                location = "other"
            variables.append(
                {
                    "name": str(var_name),
                    "location": location,
                    "dims": list(dims),
                    "units": variable.attrs.get("units"),
                    "standard_name": variable.attrs.get("standard_name"),
                    "long_name": variable.attrs.get("long_name"),
                }
            )
        facts["variables"] = variables

    return facts


def remote_remap_variable(
    grid_path: str,
    data_path: str,
    target_grid_path: str,
    variable_name: str,
    method: str = "nearest_neighbor",
    remap_to: str = "faces",
    backend: str = "uxarray",
    yac_method: Optional[str] = None,
) -> Dict[str, Any]:
    """Remap a face-centered variable onto a target grid on HPC.

    Returns compact summary statistics and grid topology (not the full remapped
    array) so large meshes never cross the network. The heavy compute runs on
    the worker where the data lives.
    """
    import os

    import numpy as np
    import uxarray as ux

    def _open_ds(gp, dp):
        if gp.lower().startswith("healpix:"):
            g = ux.Grid.from_healpix(int(gp.split(":")[1]))
            return ux.open_dataset(g.to_xarray(), dp)
        if os.path.splitext(gp.lower())[1] in [".shp", ".geojson"]:
            g = ux.Grid.from_file(gp, backend="geopandas")
            return ux.open_dataset(g.to_xarray(), dp)
        return ux.open_dataset(gp, dp)

    def _open_grid(gp):
        if gp.lower().startswith("healpix:"):
            return ux.Grid.from_healpix(int(gp.split(":")[1]))
        if os.path.splitext(gp.lower())[1] in [".shp", ".geojson"]:
            return ux.Grid.from_file(gp, backend="geopandas")
        return ux.open_grid(gp)

    uxds = _open_ds(grid_path, data_path)
    source_grid = uxds.uxgrid
    target_grid = _open_grid(target_grid_path)

    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. Available: {list(uxds.data_vars)}"
        )
    uxda = uxds[variable_name]
    # Mirrors domain.remap_backend.resolve_remap_plan; inlined because the
    # worker has no uxarray_mcp. Change both together.
    _YAC_METHODS = ("nnn", "dnn", "average", "conservative")
    _UX_METHODS = ("nearest_neighbor", "inverse_distance_weighted", "bilinear")
    _method = (method or "nearest_neighbor").strip().lower()
    _backend = (backend or "uxarray").strip().lower()
    _yac = yac_method.strip().lower() if yac_method else None
    if _method in _YAC_METHODS:
        _backend, _yac = "yac", _yac or _method
    if _backend == "yac":
        _yac = _yac or "nnn"
        if _yac not in _YAC_METHODS:
            raise ValueError(
                f"Unsupported yac_method {yac_method!r}. Choose from {_YAC_METHODS}."
            )
    elif _backend != "uxarray":
        raise ValueError(
            f"Unsupported remap backend {backend!r}. Choose 'uxarray' or 'yac'."
        )
    elif _method not in _UX_METHODS:
        raise ValueError(
            f"Unsupported remap method {method!r}. Choose from {_UX_METHODS} "
            f"(uxarray backend) or {_YAC_METHODS} (YAC backend)."
        )
    _label = f"yac:{_yac}" if _backend == "yac" else _method
    _coverage_method = _yac if _backend == "yac" else _method

    def _remap_one(_uxda):
        if _backend == "yac":
            try:
                return _uxda.remap.nearest_neighbor(
                    target_grid, remap_to=remap_to, backend="yac", yac_method=_yac
                )
            except Exception as exc:
                if "yac" in type(exc).__name__.lower() or "yac.core" in str(exc):
                    raise RuntimeError(
                        "backend='yac' was requested but the 'yac' Python package "
                        "could not be imported on the HPC worker. Build YAC with "
                        "scripts/hpc_build_yac.py and put its site-packages on the "
                        "worker's PYTHONPATH, or use backend='uxarray'."
                    ) from exc
                raise
        return getattr(_uxda.remap, _method)(target_grid, remap_to=remap_to)

    # Coverage of the target mesh by the source, measured before remapping.
    # Mirrors domain.remap_coverage.compute_scattered_coverage.
    def _coverage(_src_grid):
        _lon_attr, _lat_attr = (
            ("node_lon", "node_lat")
            if remap_to == "nodes"
            else ("face_lon", "face_lat")
        )
        try:
            _tl = np.asarray(getattr(target_grid, _lon_attr), dtype=float)
            _tla = np.asarray(getattr(target_grid, _lat_attr), dtype=float)
        except (AttributeError, ValueError, TypeError):
            return None
        if _tl.size == 0 or _tl.shape != _tla.shape:
            return None
        _tl = (_tl + 180.0) % 360.0 - 180.0
        _sl = (np.asarray(_src_grid.node_lon, dtype=float) + 180.0) % 360.0 - 180.0
        _sla = np.asarray(_src_grid.node_lat, dtype=float)
        _bbox = {
            "lon_min": float(_sl.min()),
            "lon_max": float(_sl.max()),
            "lat_min": float(_sla.min()),
            "lat_max": float(_sla.max()),
        }
        _pts = np.column_stack([_tl, _tla])
        _in = (
            (_pts[:, 0] >= _bbox["lon_min"])
            & (_pts[:, 0] <= _bbox["lon_max"])
            & (_pts[:, 1] >= _bbox["lat_min"])
            & (_pts[:, 1] <= _bbox["lat_max"])
        )
        _n = int(_pts.shape[0])
        _inside = int(_in.sum())
        _test = "bounding_box"
        if _inside and _n <= 20000:
            try:
                _f, _counts = _src_grid.get_faces_containing_point(_pts[_in])
                _inside = int(np.count_nonzero(np.asarray(_counts) > 0))
                _test = "point_in_cell"
            except Exception:
                _test = "bounding_box"
        _conservative = _coverage_method in (
            "conservative",
            "conservative_normed",
            "first_order_conservative",
        )
        _codes = []
        if _inside == 0:
            _codes.append("REMAP_COVERAGE_ZERO")
        elif _inside < _n:
            _codes.append("REMAP_COVERAGE_PARTIAL")
        if not _conservative:
            _codes.append("REMAP_METHOD_NOT_CONSERVATIVE")
        return {
            "n_target_points": _n,
            "points_in_source": _inside,
            "coverage_fraction": (float(_inside) / _n) if _n else 0.0,
            "source_bbox": _bbox,
            "test": _test,
            "method": _coverage_method,
            "method_is_conservative": _conservative,
            "warning_codes": _codes,
        }

    coverage = _coverage(source_grid)
    remapped = _remap_one(uxda)
    vals = np.asarray(remapped.values, dtype=float)
    finite = vals[np.isfinite(vals)]
    stats = (
        {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "std": float(finite.std()),
        }
        if finite.size > 0
        else {"min": None, "max": None, "mean": None, "std": None}
    )

    out = {
        "variable_name": variable_name,
        "method": _label,
        "backend": _backend,
        "yac_method": _yac,
        "remap_to": remap_to,
        "source_grid": {
            "n_face": int(source_grid.n_face),
            "n_node": int(source_grid.n_node),
            "n_edge": int(source_grid.n_edge),
        },
        "target_grid": {
            "n_face": int(target_grid.n_face),
            "n_node": int(target_grid.n_node),
            "n_edge": int(target_grid.n_edge),
        },
        "result_shape": list(remapped.shape),
        "stats": stats,
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }
    if coverage is not None:
        out["source_coverage"] = coverage
    return out


def remote_regrid_dataset(
    grid_path: str,
    data_path: str,
    target_grid_path: str,
    variable_names: Optional[list] = None,
    method: str = "nearest_neighbor",
    remap_to: str = "faces",
    backend: str = "uxarray",
    yac_method: Optional[str] = None,
) -> Dict[str, Any]:
    """Remap all selected face-centered variables onto a target grid on HPC.

    Returns per-variable summary statistics (not full arrays).
    """
    import os

    import numpy as np
    import uxarray as ux

    def _open_ds(gp, dp):
        if gp.lower().startswith("healpix:"):
            g = ux.Grid.from_healpix(int(gp.split(":")[1]))
            return ux.open_dataset(g.to_xarray(), dp)
        if os.path.splitext(gp.lower())[1] in [".shp", ".geojson"]:
            g = ux.Grid.from_file(gp, backend="geopandas")
            return ux.open_dataset(g.to_xarray(), dp)
        return ux.open_dataset(gp, dp)

    def _open_grid(gp):
        if gp.lower().startswith("healpix:"):
            return ux.Grid.from_healpix(int(gp.split(":")[1]))
        if os.path.splitext(gp.lower())[1] in [".shp", ".geojson"]:
            return ux.Grid.from_file(gp, backend="geopandas")
        return ux.open_grid(gp)

    uxds = _open_ds(grid_path, data_path)
    target_grid = _open_grid(target_grid_path)

    variables = variable_names or [
        name
        for name, var in uxds.data_vars.items()
        if "n_face" in var.dims or "nCells" in var.dims
    ]
    if not variables:
        raise ValueError("No face-centered variables available for remapping.")

    # Mirrors domain.remap_backend.resolve_remap_plan; inlined because the
    # worker has no uxarray_mcp. Change both together.
    _YAC_METHODS = ("nnn", "dnn", "average", "conservative")
    _UX_METHODS = ("nearest_neighbor", "inverse_distance_weighted", "bilinear")
    _method = (method or "nearest_neighbor").strip().lower()
    _backend = (backend or "uxarray").strip().lower()
    _yac = yac_method.strip().lower() if yac_method else None
    if _method in _YAC_METHODS:
        _backend, _yac = "yac", _yac or _method
    if _backend == "yac":
        _yac = _yac or "nnn"
        if _yac not in _YAC_METHODS:
            raise ValueError(
                f"Unsupported yac_method {yac_method!r}. Choose from {_YAC_METHODS}."
            )
    elif _backend != "uxarray":
        raise ValueError(
            f"Unsupported remap backend {backend!r}. Choose 'uxarray' or 'yac'."
        )
    elif _method not in _UX_METHODS:
        raise ValueError(
            f"Unsupported remap method {method!r}. Choose from {_UX_METHODS} "
            f"(uxarray backend) or {_YAC_METHODS} (YAC backend)."
        )
    _label = f"yac:{_yac}" if _backend == "yac" else _method
    _coverage_method = _yac if _backend == "yac" else _method

    def _remap_one(_uxda):
        if _backend == "yac":
            try:
                return _uxda.remap.nearest_neighbor(
                    target_grid, remap_to=remap_to, backend="yac", yac_method=_yac
                )
            except Exception as exc:
                if "yac" in type(exc).__name__.lower() or "yac.core" in str(exc):
                    raise RuntimeError(
                        "backend='yac' was requested but the 'yac' Python package "
                        "could not be imported on the HPC worker. Build YAC with "
                        "scripts/hpc_build_yac.py and put its site-packages on the "
                        "worker's PYTHONPATH, or use backend='uxarray'."
                    ) from exc
                raise
        return getattr(_uxda.remap, _method)(target_grid, remap_to=remap_to)

    # Coverage of the target mesh by the source, measured before remapping.
    # Mirrors domain.remap_coverage.compute_scattered_coverage.
    def _coverage(_src_grid):
        _lon_attr, _lat_attr = (
            ("node_lon", "node_lat")
            if remap_to == "nodes"
            else ("face_lon", "face_lat")
        )
        try:
            _tl = np.asarray(getattr(target_grid, _lon_attr), dtype=float)
            _tla = np.asarray(getattr(target_grid, _lat_attr), dtype=float)
        except (AttributeError, ValueError, TypeError):
            return None
        if _tl.size == 0 or _tl.shape != _tla.shape:
            return None
        _tl = (_tl + 180.0) % 360.0 - 180.0
        _sl = (np.asarray(_src_grid.node_lon, dtype=float) + 180.0) % 360.0 - 180.0
        _sla = np.asarray(_src_grid.node_lat, dtype=float)
        _bbox = {
            "lon_min": float(_sl.min()),
            "lon_max": float(_sl.max()),
            "lat_min": float(_sla.min()),
            "lat_max": float(_sla.max()),
        }
        _pts = np.column_stack([_tl, _tla])
        _in = (
            (_pts[:, 0] >= _bbox["lon_min"])
            & (_pts[:, 0] <= _bbox["lon_max"])
            & (_pts[:, 1] >= _bbox["lat_min"])
            & (_pts[:, 1] <= _bbox["lat_max"])
        )
        _n = int(_pts.shape[0])
        _inside = int(_in.sum())
        _test = "bounding_box"
        if _inside and _n <= 20000:
            try:
                _f, _counts = _src_grid.get_faces_containing_point(_pts[_in])
                _inside = int(np.count_nonzero(np.asarray(_counts) > 0))
                _test = "point_in_cell"
            except Exception:
                _test = "bounding_box"
        _conservative = _coverage_method in (
            "conservative",
            "conservative_normed",
            "first_order_conservative",
        )
        _codes = []
        if _inside == 0:
            _codes.append("REMAP_COVERAGE_ZERO")
        elif _inside < _n:
            _codes.append("REMAP_COVERAGE_PARTIAL")
        if not _conservative:
            _codes.append("REMAP_METHOD_NOT_CONSERVATIVE")
        return {
            "n_target_points": _n,
            "points_in_source": _inside,
            "coverage_fraction": (float(_inside) / _n) if _n else 0.0,
            "source_bbox": _bbox,
            "test": _test,
            "method": _coverage_method,
            "method_is_conservative": _conservative,
            "warning_codes": _codes,
        }

    coverage = _coverage(uxds.uxgrid)
    per_variable = {}
    for name in variables:
        remapped = _remap_one(uxds[name])
        vals = np.asarray(remapped.values, dtype=float)
        finite = vals[np.isfinite(vals)]
        per_variable[name] = (
            {
                "min": float(finite.min()),
                "max": float(finite.max()),
                "mean": float(finite.mean()),
                "shape": list(remapped.shape),
            }
            if finite.size > 0
            else {"min": None, "max": None, "mean": None, "shape": list(vals.shape)}
        )

    out = {
        "method": _label,
        "backend": _backend,
        "yac_method": _yac,
        "remap_to": remap_to,
        "variables": list(variables),
        "target_grid": {
            "n_face": int(target_grid.n_face),
            "n_node": int(target_grid.n_node),
            "n_edge": int(target_grid.n_edge),
        },
        "per_variable_stats": per_variable,
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }
    if coverage is not None:
        out["source_coverage"] = coverage
    return out


def remote_remap_to_rectilinear(
    grid_path: str,
    data_path: str,
    variable_name: str,
    target_lon: list,
    target_lat: list,
    backend: str = "uxarray",
    yac_method: Optional[str] = None,
) -> Dict[str, Any]:
    """Remap a face-centered variable onto a rectilinear lon/lat grid on HPC.

    The target rectilinear grid is typically small, so the full remapped array
    is returned (as nested lists) to allow local persistence.
    """
    import os

    import numpy as np
    import uxarray as ux
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    else:
        uxds = ux.open_dataset(grid_path, data_path)

    if variable_name not in uxds.data_vars:
        raise ValueError(
            f"Variable '{variable_name}' not found. Available: {list(uxds.data_vars)}"
        )
    uxda = uxds[variable_name]
    if not hasattr(uxda.remap, "to_rectilinear"):
        raise NotImplementedError(
            "remap_to_rectilinear requires a UXarray release that provides "
            "remap.to_rectilinear. Upgrade the worker's uxarray to use this."
        )

    lon = list(target_lon)
    lat = list(target_lat)
    # Mirrors domain.remap_backend.resolve_remap_plan for the rectilinear case.
    _YAC_METHODS = ("nnn", "dnn", "average", "conservative")
    _backend = (backend or "uxarray").strip().lower()
    _yac = yac_method.strip().lower() if yac_method else None
    if _yac in _YAC_METHODS:
        _backend = "yac"
    if _backend == "yac":
        _yac = _yac or "nnn"
        if _yac not in _YAC_METHODS:
            raise ValueError(
                f"Unsupported yac_method {yac_method!r}. Choose from {_YAC_METHODS}."
            )
    elif _backend != "uxarray":
        raise ValueError(
            f"Unsupported remap backend {backend!r}. Choose 'uxarray' or 'yac'."
        )
    elif _yac:
        raise ValueError(f"yac_method={yac_method!r} requires backend='yac'.")
    _coverage_method = _yac if _backend == "yac" else "nearest_neighbor"
    _conservative = _coverage_method == "conservative"
    # Same coverage screen as the local path, inlined because the worker does
    # not have uxarray_mcp installed.
    grid_lon = (np.asarray(uxda.uxgrid.node_lon, dtype=float) + 180.0) % 360.0 - 180.0
    grid_lat = np.asarray(uxda.uxgrid.node_lat, dtype=float)
    bbox = {
        "lon_min": float(grid_lon.min()),
        "lon_max": float(grid_lon.max()),
        "lat_min": float(grid_lat.min()),
        "lat_max": float(grid_lat.max()),
    }
    t_lon = (np.asarray(lon, dtype=float) + 180.0) % 360.0 - 180.0
    mesh_lon, mesh_lat = np.meshgrid(t_lon, np.asarray(lat, dtype=float))
    pts = np.column_stack([mesh_lon.ravel(), mesh_lat.ravel()])
    in_bbox = (
        (pts[:, 0] >= bbox["lon_min"])
        & (pts[:, 0] <= bbox["lon_max"])
        & (pts[:, 1] >= bbox["lat_min"])
        & (pts[:, 1] <= bbox["lat_max"])
    )
    n_points = int(pts.shape[0])
    n_inside = int(in_bbox.sum())
    coverage_test = "bounding_box"
    if n_inside and n_points <= 20000:
        try:
            _faces, counts = uxda.uxgrid.get_faces_containing_point(pts[in_bbox])
            n_inside = int(np.count_nonzero(np.asarray(counts) > 0))
            coverage_test = "point_in_cell"
        except Exception:
            coverage_test = "bounding_box"
    coverage_codes = []
    if n_inside == 0:
        coverage_codes.append("REMAP_COVERAGE_ZERO")
    elif n_inside < n_points:
        coverage_codes.append("REMAP_COVERAGE_PARTIAL")
    if not _conservative:
        coverage_codes.append("REMAP_METHOD_NOT_CONSERVATIVE")
    coverage = {
        "n_target_points": n_points,
        "points_in_source": n_inside,
        "coverage_fraction": (float(n_inside) / n_points) if n_points else 0.0,
        "source_bbox": bbox,
        "test": coverage_test,
        "method": _coverage_method,
        "method_is_conservative": _conservative,
        "warning_codes": coverage_codes,
    }

    try:
        remapped = uxda.remap.to_rectilinear(
            lon, lat, backend=_backend, yac_method=_yac
        )
    except Exception as exc:
        if _backend == "yac" and (
            "yac" in type(exc).__name__.lower() or "yac.core" in str(exc)
        ):
            raise RuntimeError(
                "backend='yac' was requested but the 'yac' Python package could "
                "not be imported on the HPC worker. Build YAC with "
                "scripts/hpc_build_yac.py and put its site-packages on the "
                "worker's PYTHONPATH, or use backend='uxarray'."
            ) from exc
        if _backend == "yac" and "Cannot reshape remapped data" in str(exc):
            raise RuntimeError(
                f"{exc} This is a known UXarray limitation of backend='yac' when "
                "target_lon spans the full 360 degrees. Use a regional "
                "target_lon, or backend='uxarray' for a global one."
            ) from exc
        raise
    vals = np.asarray(remapped.values, dtype=float)
    finite = vals[np.isfinite(vals)]
    stats = (
        {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
        }
        if finite.size > 0
        else {"min": None, "max": None, "mean": None}
    )

    return {
        "variable_name": variable_name,
        "backend": _backend,
        "method": f"yac:{_yac}" if _backend == "yac" else "nearest_neighbor",
        "yac_method": _yac,
        "target_shape": [len(lat), len(lon)],
        "stats": stats,
        "source_coverage": coverage,
        "values": vals.tolist(),
        "target_lon": lon,
        "target_lat": lat,
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }


def remote_calculate_zonal_anomaly(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
) -> Dict[str, Any]:
    """Compute zonal-anomaly statistics on the HPC worker.

    The zonal anomaly is each face value minus the zonal mean of its latitude
    band. Returns compact summary statistics (not the full per-face field) so
    large meshes never cross the network.
    """
    import os

    import numpy as np
    import uxarray as ux
    import xarray as xr

    if grid_path.lower().startswith("healpix:"):
        grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
    elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
        grid = ux.Grid.from_file(grid_path, backend="geopandas")
        uxds = ux.UxDataset(xr.open_dataset(data_path), uxgrid=grid)
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
            "Zonal anomaly only supports face-centered data."
        )
    if not hasattr(var, "zonal_anomaly"):
        raise NotImplementedError(
            "zonal_anomaly requires a UXarray release that provides "
            "UxDataArray.zonal_anomaly. Upgrade the worker's uxarray to use this."
        )

    if lat_spec is not None:
        result = var.zonal_anomaly(lat=lat_spec, conservative=conservative)
    else:
        result = var.zonal_anomaly(conservative=conservative)

    vals = result.values
    finite = vals[np.isfinite(vals)]
    stats = (
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
        "variable_name": variable_name,
        "conservative": conservative,
        "n_face": int(uxds.uxgrid.n_face),
        "stats": stats,
        "interpretation": (
            "per-face deviation from the zonal mean of its latitude band"
        ),
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
        "_worker_runtime": {
            "hostname": __import__("socket").gethostname(),
            "python_version": __import__("platform").python_version(),
            "uxarray_version": getattr(ux, "__version__", "unknown"),
            "xarray_version": getattr(__import__("xarray"), "__version__", "unknown"),
            "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
            "pbs_job_id": __import__("os").environ.get("PBS_JOBID"),
        },
    }
