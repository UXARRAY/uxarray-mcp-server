import uxarray as ux
from pathlib import Path
from typing import Dict, Any, Optional, List
import numpy as np


def inspect_mesh(file_path: str) -> Dict[str, Any]:
    """
    Inspect an unstructured mesh file and return basic topology information.

    This tool loads a mesh file using UXarray and extracts fundamental
    topological properties including the number of faces, nodes, edges,
    and the mesh format.

    Args:
        file_path: Path to the mesh file (supports UGRID, MPAS, SCRIP, ESMF, etc.)

    Returns:
        Dictionary containing:
        - format: The mesh format (e.g., "MPAS", "UGRID")
        - n_face: Number of faces (cells/polygons) in the mesh
        - n_node: Number of nodes (vertices/corner points)
        - n_edge: Number of edges (boundaries between nodes)
        - n_max_face_nodes: Maximum number of nodes per face
        - file_size_mb: Size of the file in megabytes

    Example:
        >>> inspect_mesh("/path/to/mesh.nc")
        {
            "format": "MPAS",
            "n_face": 2621442,
            "n_node": 1310720,
            "n_edge": 3932160,
            "n_max_face_nodes": 7,
            "file_size_mb": 4.6
        }
    """
    # Handle HEALPix generation
    if file_path.lower().startswith("healpix"):
        try:
            # Expected format: "healpix:<zoom_level>" or just "healpix" (default zoom?)
            parts = file_path.split(":")
            zoom = (
                int(parts[1]) if len(parts) > 1 else 1
            )  # Default to zoom 1 if not specified

            grid = ux.Grid.from_healpix(zoom=zoom)
            file_size_mb = 0.0  # Virtual mesh, no file size

            # Extract topology information
            result = {
                "format": "HEALPix",
                "n_face": int(grid.n_face),
                "n_node": int(grid.n_node),
                "n_edge": int(grid.n_edge),
                "n_max_face_nodes": int(grid.n_max_face_nodes),
                "file_size_mb": 0.0,
            }
            return result
        except ValueError:
            raise ValueError(
                "Invalid HEALPix format. Use 'healpix:<zoom_level>' (e.g., 'healpix:2')."
            )
        except Exception as e:
            raise RuntimeError(f"Failed to generate HEALPix mesh: {str(e)}")

    # Validate file exists
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Mesh file not found: {file_path}")

    file_size_mb = path.stat().st_size / (1024 * 1024)

    # Load the mesh using UXarray
    try:
        grid = ux.open_grid(file_path)
    except Exception as e:
        raise RuntimeError(f"Failed to load mesh file: {str(e)}")

    # Extract topology information
    result = {
        "format": grid.source_grid_spec,
        "n_face": int(grid.n_face),
        "n_node": int(grid.n_node),
        "n_edge": int(grid.n_edge),
        "n_max_face_nodes": int(grid.n_max_face_nodes),
        "file_size_mb": round(file_size_mb, 2),
    }

    return result


def inspect_variable(
    grid_path: str, data_path: str, variable_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Inspect data variables in an unstructured mesh dataset.

    This tool loads a mesh dataset using UXarray and extracts information
    about the data variables stored on the mesh, including their dimensions,
    data types, attributes, and basic statistics.

    Args:
        grid_path: Path to the mesh grid file
        data_path: Path to the data file with variables
        variable_name: Optional specific variable to inspect. If None, inspect all variables.

    Returns:
        Dictionary containing:
        - variables: List of variable info dicts, each with:
          - name: Variable name
          - dims: Dimension names (tuple)
          - shape: Shape tuple
          - dtype: Data type string
          - location: "faces", "nodes", "edges", or "other"
          - attrs: Variable attributes dict (units, long_name, etc.)
          - statistics: {min, max, mean} if numeric, None otherwise
        - grid_info: Brief grid summary {n_face, n_node, n_edge}

    Example:
        >>> inspect_variable("grid.nc", "data.nc")
        {
            "variables": [
                {
                    "name": "temperature",
                    "dims": ("n_face", "n_level"),
                    "shape": (40962, 55),
                    "dtype": "float64",
                    "location": "faces",
                    "attrs": {"units": "K", "long_name": "Temperature"},
                    "statistics": {"min": 271.5, "max": 303.2, "mean": 288.1}
                }
            ],
            "grid_info": {"n_face": 40962, "n_node": 20480, "n_edge": 61440}
        }
    """
    # Validate file paths exist
    grid_path_obj = Path(grid_path)
    data_path_obj = Path(data_path)

    if not grid_path_obj.exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")
    if not data_path_obj.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    # Load the dataset using UXarray
    try:
        uxds = ux.open_dataset(grid_path, data_path)
    except Exception as e:
        raise RuntimeError(f"Failed to load dataset: {str(e)}")

    # Determine which variables to inspect
    if variable_name:
        if variable_name not in uxds.data_vars:
            available = list(uxds.data_vars.keys())
            raise ValueError(
                f"Variable '{variable_name}' not found. Available variables: {available}"
            )
        variables_to_inspect = [variable_name]
    else:
        variables_to_inspect = list(uxds.data_vars.keys())

    # Inspect each variable
    variables_info: List[Dict[str, Any]] = []
    for var_name in variables_to_inspect:
        var = uxds[var_name]

        # Extract basic metadata
        var_info = {
            "name": var_name,
            "dims": var.dims,
            "shape": var.shape,
            "dtype": str(var.dtype),
            "attrs": dict(var.attrs),
        }

        # Determine variable location (faces, nodes, or edges)
        location = "other"
        if "n_face" in var.dims or "nCells" in var.dims:
            location = "faces"
        elif "n_node" in var.dims or "nVertices" in var.dims:
            location = "nodes"
        elif "n_edge" in var.dims or "nEdges" in var.dims:
            location = "edges"
        var_info["location"] = location

        # Compute statistics if numeric
        try:
            if np.issubdtype(var.dtype, np.number):
                values = var.values
                var_info["statistics"] = {
                    "min": float(np.nanmin(values)),
                    "max": float(np.nanmax(values)),
                    "mean": float(np.nanmean(values)),
                }
            else:
                var_info["statistics"] = None
        except Exception:
            # If statistics computation fails, set to None
            var_info["statistics"] = None

        variables_info.append(var_info)

    # Get grid context
    grid_info = {
        "n_face": int(uxds.uxgrid.n_face),
        "n_node": int(uxds.uxgrid.n_node),
        "n_edge": int(uxds.uxgrid.n_edge),
    }

    return {"variables": variables_info, "grid_info": grid_info}


def calculate_area(file_path: str) -> Dict[str, Any]:
    """
    Calculate face areas for an unstructured mesh.

    This tool loads a mesh file using UXarray and calculates the area of each
    face (cell) in the mesh, returning statistics about the areas.

    Args:
        file_path: Path to the mesh file (supports UGRID, MPAS, SCRIP, ESMF, etc.)

    Returns:
        Dictionary containing:
        - total_area: Total surface area of the mesh
        - mean_area: Mean face area
        - min_area: Minimum face area
        - max_area: Maximum face area
        - area_units: Units of the area (e.g., "m^2", "km^2")
        - n_face: Number of faces in the mesh

    Example:
        >>> calculate_area("/path/to/mesh.nc")
        {
            "total_area": 5.10064e14,
            "mean_area": 1.246e7,
            "min_area": 8.5e6,
            "max_area": 1.8e7,
            "area_units": "m^2",
            "n_face": 40962
        }
    """
    # Handle HEALPix generation
    if file_path.lower().startswith("healpix"):
        try:
            parts = file_path.split(":")
            zoom = int(parts[1]) if len(parts) > 1 else 1

            grid = ux.Grid.from_healpix(zoom=zoom)
        except ValueError:
            raise ValueError(
                "Invalid HEALPix format. Use 'healpix:<zoom_level>' (e.g., 'healpix:2')."
            )
        except Exception as e:
            raise RuntimeError(f"Failed to generate HEALPix mesh: {str(e)}")
    else:
        # Validate file exists
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Mesh file not found: {file_path}")

        # Load the mesh using UXarray
        try:
            grid = ux.open_grid(file_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load mesh file: {str(e)}")

    # Calculate face areas
    try:
        face_areas = grid.face_areas
    except Exception as e:
        raise RuntimeError(f"Failed to calculate face areas: {str(e)}")

    # Compute statistics
    total_area = float(face_areas.sum())
    mean_area = float(face_areas.mean())
    min_area = float(face_areas.min())
    max_area = float(face_areas.max())

    # Determine units (UXarray typically uses square meters)
    area_units = "m^2"
    if hasattr(face_areas, "attrs") and "units" in face_areas.attrs:
        area_units = face_areas.attrs["units"]

    result = {
        "total_area": total_area,
        "mean_area": mean_area,
        "min_area": min_area,
        "max_area": max_area,
        "area_units": area_units,
        "n_face": int(grid.n_face),
    }

    return result
