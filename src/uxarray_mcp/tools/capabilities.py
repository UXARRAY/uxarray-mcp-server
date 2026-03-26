"""Tool discovery and capability filtering for UXarray MCP server."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import uxarray as ux

from uxarray_mcp.provenance import attach_provenance
from uxarray_mcp.remote.config import load_config


def get_capabilities(
    grid_path: str,
    data_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Discover applicable tools and UXarray capabilities for a mesh and dataset.

    Inspects the grid topology and data variable locations to determine which
    MCP server tools and native UXarray API methods can be applied to this
    specific dataset. Addresses two key needs from the team:

    1. Tool filtering — only surfaces tools that actually work on your data
       (e.g. zonal_mean needs face-centered data; area needs faces, not points).
    2. Tool transparency — shows both MCP server tools (what this server wraps)
       and the broader native UXarray API (what exists beyond the server).

    Args:
        grid_path: Path to mesh file (UGRID, MPAS, SCRIP, ESMF, etc.) or
                   "healpix:<zoom_level>" for HEALPix grids.
        data_path: Optional path to data file with variables. If provided,
                   variable-level filtering and per-variable method lists
                   are included in the response.

    Returns:
        Dictionary containing:
        - grid_summary: topology info (n_face, n_node, n_edge, format,
          has_faces, has_nodes, has_edges)
        - mcp_server_tools: list of tool dicts with applicable (bool),
          reason (str), and call_example (str)
        - uxarray_capabilities: categorized native UXarray API methods grouped
          by spatial_analysis, subsetting, remapping, vector_calculus,
          topological_ops, and visualization
        - variables: per-variable applicability (only when data_path provided)
        - recommendations: plain-English suggestions based on the dataset

    Example:
        >>> get_capabilities("healpix:2")
        {
            "grid_summary": {"n_face": 192, "n_node": 162, "n_edge": 352, ...},
            "mcp_server_tools": [
                {"name": "inspect_mesh", "applicable": True, ...},
                {"name": "calculate_area", "applicable": True, ...},
                {"name": "calculate_zonal_mean", "applicable": False,
                 "reason": "Requires face-centered data (data_path not provided).", ...},
            ],
            "uxarray_capabilities": {
                "spatial_analysis": ["grid.face_areas", ...],
                ...
            },
            "recommendations": ["Provide a data_path to unlock variable-level filtering."]
        }
    """
    # --- Load grid ---
    if grid_path.lower().startswith("healpix"):
        parts = grid_path.split(":")
        zoom = int(parts[1]) if len(parts) > 1 else 1
        try:
            grid = ux.Grid.from_healpix(zoom=zoom)
        except Exception as e:
            raise RuntimeError(f"Failed to create HEALPix grid: {e}") from e
        grid_format = "HEALPix"
    else:
        grid_file = Path(grid_path)
        if not grid_file.exists():
            raise FileNotFoundError(f"Grid file not found: {grid_path}")
        try:
            grid = ux.open_grid(grid_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load grid file: {e}") from e
        grid_format = str(getattr(grid, "source_grid_spec", "Unknown"))

    # --- Grid topology ---
    n_face = int(grid.n_face) if hasattr(grid, "n_face") else 0
    n_node = int(grid.n_node) if hasattr(grid, "n_node") else 0
    n_edge = int(grid.n_edge) if hasattr(grid, "n_edge") else 0

    has_faces = n_face > 0
    has_nodes = n_node > 0
    has_edges = n_edge > 0

    grid_summary = {
        "n_face": n_face,
        "n_node": n_node,
        "n_edge": n_edge,
        "format": grid_format,
        "has_faces": has_faces,
        "has_nodes": has_nodes,
        "has_edges": has_edges,
    }

    # --- Load dataset if data_path provided ---
    variables_info: List[Dict[str, Any]] = []
    has_face_centered_vars = False
    has_node_centered_vars = False
    has_edge_centered_vars = False
    face_centered_var_names: List[str] = []

    if data_path is not None:
        data_file = Path(data_path)
        if not data_file.exists():
            raise FileNotFoundError(f"Data file not found: {data_path}")
        try:
            uxds = ux.open_dataset(grid_path, data_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load dataset: {e}") from e

        for var_name in uxds.data_vars:
            var = uxds[var_name]

            # Detect location from dimension names
            if any(d in var.dims for d in ("n_face", "nCells")):
                location = "faces"
                has_face_centered_vars = True
                face_centered_var_names.append(var_name)
            elif any(d in var.dims for d in ("n_node", "nVertices")):
                location = "nodes"
                has_node_centered_vars = True
            elif any(d in var.dims for d in ("n_edge", "nEdges")):
                location = "edges"
                has_edge_centered_vars = True
            else:
                location = "other"

            # Per-variable applicable tools
            applicable_mcp: List[str] = ["inspect_variable", "validate_dataset"]
            applicable_uxarray: List[str] = []

            if location == "faces":
                applicable_mcp += ["calculate_zonal_mean", "calculate_zonal_mean_hpc"]
                applicable_uxarray += [
                    "var.zonal_mean()",
                    "var.integrate()",
                    "var.gradient()",
                    "var.weighted_mean()",
                    "var.remap.nearest_neighbor(dest_grid)",
                    "var.remap.inverse_distance_weighted(dest_grid)",
                    "var.remap.bilinear(dest_grid)",
                    "var.topological_mean()",
                    "var.plot.polygons()",
                ]
            elif location == "nodes":
                applicable_uxarray += [
                    "var.topological_mean()",
                    "var.topological_min()",
                    "var.topological_max()",
                    "var.topological_std()",
                    "var.plot.points()",
                ]
            elif location == "edges":
                applicable_uxarray += [
                    "var.topological_mean()",
                    "var.topological_sum()",
                ]

            variables_info.append(
                {
                    "name": var_name,
                    "location": location,
                    "applicable_mcp_tools": applicable_mcp,
                    "applicable_uxarray_methods": applicable_uxarray,
                }
            )

    # --- MCP Server tool filtering ---
    gp = f'"{grid_path}"'
    dp = f', "{data_path}"' if data_path else ""

    mcp_tools = [
        {
            "name": "inspect_mesh",
            "applicable": True,
            "reason": "Always available — inspects topology and format of any mesh.",
            "call_example": f"inspect_mesh({gp})",
        },
        {
            "name": "inspect_variable",
            "applicable": data_path is not None,
            "reason": (
                "Available — inspects all variables in the dataset."
                if data_path
                else "Requires a data file (data_path not provided)."
            ),
            "call_example": f"inspect_variable({gp}{dp})",
        },
        {
            "name": "calculate_area",
            "applicable": has_faces,
            "reason": (
                f"Available — mesh has {n_face:,} faces for area calculation."
                if has_faces
                else "Not applicable — no faces found (point cloud or node-only mesh)."
            ),
            "call_example": f"calculate_area({gp})",
        },
        {
            "name": "calculate_zonal_mean",
            "applicable": has_face_centered_vars,
            "reason": (
                f"Available — face-centered variables found: {face_centered_var_names}."
                if has_face_centered_vars
                else (
                    "Requires face-centered data — provide data_path with face-centered variables."
                    if data_path is None
                    else "Not applicable — no face-centered variables found. Zonal mean requires data mapped to faces."
                )
            ),
            "call_example": f'calculate_zonal_mean({gp}{dp}, variable_name="...")',
        },
        {
            "name": "validate_dataset",
            "applicable": data_path is not None,
            "reason": (
                "Available — checks for NaN, Inf, and fill value issues."
                if data_path
                else "Requires a data file (data_path not provided)."
            ),
            "call_example": f"validate_dataset({gp}{dp})",
        },
    ]

    if load_config().has_endpoint:
        mcp_tools += [
            {
                "name": "inspect_mesh_hpc",
                "applicable": True,
                "reason": (
                    "Available — same as inspect_mesh with optional remote execution "
                    "on a configured Globus Compute endpoint."
                ),
                "call_example": f"inspect_mesh_hpc({gp}, use_remote=True)",
            },
            {
                "name": "calculate_area_hpc",
                "applicable": has_faces,
                "reason": (
                    "Available — same as calculate_area but can offload to a configured Globus Compute endpoint."
                    if has_faces
                    else "Not applicable — no faces found."
                ),
                "call_example": f"calculate_area_hpc({gp}, use_remote=True)",
            },
            {
                "name": "inspect_variable_hpc",
                "applicable": data_path is not None,
                "reason": (
                    "Available — same as inspect_variable with optional remote execution."
                    if data_path
                    else "Requires a data file."
                ),
                "call_example": f"inspect_variable_hpc({gp}{dp}, use_remote=True)",
            },
            {
                "name": "calculate_zonal_mean_hpc",
                "applicable": has_face_centered_vars,
                "reason": (
                    f"Available — face-centered variables: {face_centered_var_names}."
                    if has_face_centered_vars
                    else "Not applicable — no face-centered variables found."
                ),
                "call_example": (
                    f'calculate_zonal_mean_hpc({gp}{dp}, variable_name="...", '
                    "use_remote=True)"
                ),
            },
        ]

    # --- Native UXarray capabilities ---
    uxarray_capabilities: Dict[str, List[str]] = {
        "spatial_analysis": [],
        "subsetting": [],
        "remapping": [],
        "vector_calculus": [],
        "topological_ops": [],
        "visualization": [],
    }

    # Spatial analysis — based on topology
    uxarray_capabilities["spatial_analysis"] += [
        "grid.get_ball_tree()",
        "grid.get_kd_tree()",
        "grid.bounds",
    ]
    if has_faces:
        uxarray_capabilities["spatial_analysis"] += [
            "grid.face_areas",
            "grid.face_jacobian",
            "grid.calculate_total_face_area()",
            "grid.global_sphere_coverage()",
            "grid.construct_face_centers()",
        ]
    if has_edges:
        uxarray_capabilities["spatial_analysis"] += [
            "grid.edge_node_distances",
            "grid.edge_face_distances",
        ]

    # Subsetting — always available, richer with faces
    uxarray_capabilities["subsetting"] = [
        "grid.subset.bounding_box(lon_bounds, lat_bounds)",
        "grid.subset.bounding_circle(center_coord, r)",
        "grid.subset.nearest_neighbor(center_coord, k)",
    ]
    if has_faces:
        uxarray_capabilities["subsetting"] += [
            "grid.cross_section.constant_latitude(lat)",
            "grid.cross_section.constant_longitude(lon)",
            "grid.get_faces_at_constant_latitude(lat)",
            "grid.get_faces_between_latitudes(lat_min, lat_max)",
            "grid.get_faces_containing_point(lon, lat)",
        ]

    # Remapping — requires face-centered data
    if has_face_centered_vars:
        uxarray_capabilities["remapping"] = [
            "var.remap.nearest_neighbor(dest_grid)",
            "var.remap.inverse_distance_weighted(dest_grid)",
            "var.remap.bilinear(dest_grid)",
        ]
    elif has_faces:
        uxarray_capabilities["remapping"] = [
            "var.remap.nearest_neighbor(dest_grid)  [needs face-centered data]",
            "var.remap.inverse_distance_weighted(dest_grid)  [needs face-centered data]",
            "var.remap.bilinear(dest_grid)  [needs face-centered data]",
        ]

    # Vector calculus — requires face-centered data
    if has_face_centered_vars:
        uxarray_capabilities["vector_calculus"] = [
            "var.gradient()",
            "var.zonal_mean()",
            "var.integrate()",
            "var.weighted_mean()",
        ]
        if len(face_centered_var_names) >= 2:
            uxarray_capabilities["vector_calculus"] += [
                "ux_da_u.curl(ux_da_v)  [two face-centered vars required]",
                "ux_da_u.divergence(ux_da_v)  [two face-centered vars required]",
            ]

    # Topological ops — for node/edge data
    if has_node_centered_vars or has_edge_centered_vars:
        uxarray_capabilities["topological_ops"] = [
            "var.topological_mean()",
            "var.topological_min()",
            "var.topological_max()",
            "var.topological_std()",
            "var.topological_sum()",
            "var.topological_var()",
        ]

    # Visualization — always available, richer with data
    uxarray_capabilities["visualization"] = [
        "grid.plot.mesh()",
        "grid.plot.nodes()",
        "grid.plot.edges()",
        "grid.plot.face_centers()",
        "grid.plot.face_degree_distribution()",
        "grid.plot.face_area_distribution()",
    ]
    if has_face_centered_vars:
        uxarray_capabilities["visualization"] += [
            "var.plot.polygons()",
            "var.plot.points()",
        ]

    # --- Plain-English recommendations ---
    recommendations: List[str] = []

    if not has_faces:
        recommendations.append(
            "This appears to be a point cloud or node-only mesh. Area calculations and "
            "zonal means are not available. Spatial indexing and topological operations "
            "are your best options."
        )

    if data_path is None:
        recommendations.append(
            "Provide a data_path to unlock variable-level filtering and tools like "
            "inspect_variable, calculate_zonal_mean, and validate_dataset."
        )

    if has_face_centered_vars:
        var_list = ", ".join(face_centered_var_names)
        recommendations.append(
            f"Face-centered variables ({var_list}) support the full analysis pipeline: "
            "validate_dataset → calculate_area → calculate_zonal_mean → remap to a new grid."
        )

    if (
        data_path
        and not has_face_centered_vars
        and (has_node_centered_vars or has_edge_centered_vars)
    ):
        recommendations.append(
            "Your data is on nodes or edges, not faces. Use topological aggregation "
            "(e.g. var.topological_mean()) to map values to face centers before applying "
            "zonal mean or remapping."
        )

    if has_face_centered_vars and len(face_centered_var_names) >= 2:
        recommendations.append(
            "Multiple face-centered variables detected — you can compute vector operations "
            "like curl and divergence between pairs (e.g. wind u/v components)."
        )

    result: Dict[str, Any] = {
        "grid_summary": grid_summary,
        "mcp_server_tools": mcp_tools,
        "uxarray_capabilities": uxarray_capabilities,
        "recommendations": recommendations,
    }

    if variables_info:
        result["variables"] = variables_info

    return attach_provenance(
        result,
        tool="get_capabilities",
        inputs={"grid_path": grid_path, "data_path": data_path},
    )
