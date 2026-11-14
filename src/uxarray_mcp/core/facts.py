"""Header-only facts about a mesh or data file, without opening it as a grid.

Reads dimensions and attributes only, so it costs the same on a 60 GB file
as on a 60 KB one.
"""

from __future__ import annotations

import os
from typing import Any

from uxarray_mcp.core.mesh import is_healpix_spec, parse_healpix_zoom

SMALL_BYTES = 50 * 1024 * 1024
MEDIUM_BYTES = 1024 * 1024 * 1024
MAX_FACE_VARIABLES = 50
EXODUS_SUFFIXES = (".g", ".exo", ".e", ".ex2")
TIME_DIM_NAMES = ("time", "time_counter", "Time", "nTime")

# Variables that describe the mesh rather than carry a field, by format.
_TOPOLOGY_PREFIXES: dict[str, tuple[str, ...]] = {
    "mpas": (
        "cellsOn",
        "verticesOn",
        "edgesOn",
        "nEdgesOn",
        "indexTo",
        "areaCell",
        "latCell",
        "lonCell",
        "xCell",
        "yCell",
        "zCell",
        "meshDensity",
        "cellMask",
        "bottomDepth",
        "maxLevelCell",
        "weightsOn",
        "dvEdge",
        "dcEdge",
        "angleEdge",
        "kiteAreas",
        "fCell",
        "fEdge",
        "fVertex",
        "areaTriangle",
        "latVertex",
        "lonVertex",
        "xVertex",
        "yVertex",
        "zVertex",
        "latEdge",
        "lonEdge",
        "xEdge",
        "yEdge",
        "zEdge",
        "restingThickness",
        "boundaryLayerDepth",
    ),
    "scrip": ("grid_",),
    "esmf": (
        "elementConn",
        "numElementConn",
        "centerCoords",
        "elementArea",
        "elementMask",
        "nodeCoords",
        "origGridDims",
    ),
    "ugrid": (
        "Mesh2",
        "mesh",
        "grid_topology",
        "face_node",
        "face_edge",
        "face_face",
        "edge_node",
        "edge_face",
        "node_",
        "face_lon",
        "face_lat",
        "face_x",
        "face_y",
        "face_z",
        "face_area",
        "edge_lon",
        "edge_lat",
    ),
    "icon": (
        "vertex_of_cell",
        "edge_of_cell",
        "clon",
        "clat",
        "cell_area",
        "neighbor_cell_index",
        "adjacent_cell_of_edge",
        "cell_domain_id",
        "cell_index",
        "parent_cell_index",
        "refin_c_ctrl",
        "cell_sea_land_mask",
        "vlon",
        "vlat",
        "elon",
        "elat",
        "edge_vertices",
        "cells_of_vertex",
    ),
    "exodus": ("connect", "eb_", "coord", "elem_", "ns_", "ss_", "attrib"),
}
_TOPOLOGY_MARKERS: dict[str, tuple[str, ...]] = {
    "mpas": ("verticesOnCell",),
    "scrip": ("grid_corner_lat", "grid_corner_lon"),
    "esmf": ("elementConn",),
    "ugrid": ("face_node_connectivity", "Mesh2_face_nodes"),
    "icon": ("vertex_of_cell",),
    "exodus": ("connect1",),
}


def _size_class(size_bytes: int) -> str:
    if size_bytes < SMALL_BYTES:
        return "small"
    if size_bytes < MEDIUM_BYTES:
        return "medium"
    return "large"


def _read_header(
    path: str,
) -> tuple[dict[str, int], dict[str, Any], dict[str, tuple[str, ...]], dict[str, str]]:
    """Return ``(dims, global_attrs, var_dims, cf_roles)`` reading no variable data."""
    try:
        import netCDF4

        with netCDF4.Dataset(path, "r") as nc:
            dims = {str(k): len(v) for k, v in nc.dimensions.items()}
            attrs = {k: nc.getncattr(k) for k in nc.ncattrs()}
            var_dims = {str(k): tuple(v.dimensions) for k, v in nc.variables.items()}
            roles = {
                str(k): str(v.getncattr("cf_role"))
                for k, v in nc.variables.items()
                if "cf_role" in v.ncattrs()
            }
        return dims, attrs, var_dims, roles
    except ImportError:
        pass
    except OSError as exc:
        if path.lower().endswith(EXODUS_SUFFIXES):
            raise ValueError(f"Cannot read file header: {path}: {exc}") from exc

    import xarray as xr

    try:
        with xr.open_dataset(path, decode_times=False, chunks=None) as ds:
            dims = {str(k): int(v) for k, v in ds.sizes.items()}
            attrs = dict(ds.attrs)
            var_dims = {
                str(k): tuple(str(d) for d in v.dims) for k, v in ds.variables.items()
            }
            roles = {
                str(k): str(v.attrs["cf_role"])
                for k, v in ds.variables.items()
                if "cf_role" in v.attrs
            }
    except Exception as exc:
        raise ValueError(f"Cannot read file header: {path}: {exc}") from exc
    return dims, attrs, var_dims, roles


def _detect_format(
    dims: dict[str, int], var_dims: dict[str, tuple[str, ...]], roles: dict[str, str]
) -> tuple[str, set[str], str | None]:
    """Return ``(format, face_dims, node_dim)`` from dimension and variable names."""
    if "nCells" in dims:
        return "mpas", {"nCells"}, "nVertices" if "nVertices" in dims else None
    if "grid_size" in dims or "grid_corners" in dims:
        return "scrip", {"grid_size"}, None
    blocks = {d for d in dims if d.startswith("num_el_in_blk")}
    if blocks or any(v.startswith("connect") for v in var_dims):
        return "exodus", blocks, "num_nodes" if "num_nodes" in dims else None
    if "nodeCount" in dims or "elementConn" in var_dims:
        return "esmf", {"elementCount"}, "nodeCount" if "nodeCount" in dims else None
    if "cell" in dims and "vertex_of_cell" in var_dims:
        return "icon", {"cell"}, "vertex" if "vertex" in dims else None
    is_ugrid = (
        "Mesh2" in var_dims
        or "mesh_topology" in roles.values()
        or "nMesh2_face" in dims
        or "n_face" in dims
    )
    if is_ugrid:
        face_dim = "nMesh2_face" if "nMesh2_face" in dims else "n_face"
        node_dim = "nMesh2_node" if "nMesh2_node" in dims else "n_node"
        return "ugrid", {face_dim}, node_dim if node_dim in dims else None
    if "ncol" in dims:
        return "unknown", {"ncol"}, None
    return "unknown", set(), None


def _healpix_facts(path: str) -> dict[str, Any]:
    zoom = parse_healpix_zoom(path)
    return {
        "path": path,
        "format": "healpix",
        "n_face": 12 * 4**zoom,
        "n_node": None,
        "size_bytes": 0,
        "size_class": "small",
        "variables_face_centered": [],
        "has_data_variables": False,
        "role": "grid",
    }


def header_facts(path: str) -> dict[str, Any]:
    """Format, face/node counts, size class and variable roles from the header only.

    Accepts a ``healpix:<zoom>`` spec as well as a NetCDF/Exodus path. Raises
    ``FileNotFoundError`` for a missing file and ``ValueError`` when the header
    cannot be read.
    """
    if is_healpix_spec(path):
        return _healpix_facts(path)
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    size_bytes = int(os.stat(path).st_size)

    dims, _attrs, var_dims, roles = _read_header(path)
    format_name, face_dims, node_dim = _detect_format(dims, var_dims, roles)

    n_face: int | None = sum(dims[d] for d in face_dims if d in dims) or None
    if format_name == "scrip" and "grid_size" not in dims:
        n_face = None
    n_node = int(dims[node_dim]) if node_dim and node_dim in dims else None

    prefixes = _TOPOLOGY_PREFIXES.get(format_name, ())
    face_vars = sorted(
        name
        for name, vdims in var_dims.items()
        if face_dims.intersection(vdims) and not name.startswith(prefixes)
    )
    has_topology = any(m in var_dims for m in _TOPOLOGY_MARKERS.get(format_name, ()))
    has_data = bool(face_vars)
    role = "grid+data" if has_data and has_topology else "data" if has_data else "grid"

    facts: dict[str, Any] = {
        "path": path,
        "format": format_name,
        "n_face": int(n_face) if n_face is not None else None,
        "n_node": n_node,
        "size_bytes": size_bytes,
        "size_class": _size_class(size_bytes),
        "variables_face_centered": face_vars[:MAX_FACE_VARIABLES],
        "has_data_variables": has_data,
        "role": role,
    }
    time_dim = next((d for d in TIME_DIM_NAMES if d in dims), None)
    if time_dim is not None:
        facts["n_time"] = int(dims[time_dim])
    return facts
