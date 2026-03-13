import uxarray as ux
from pathlib import Path
from typing import Dict, Any, Optional

from uxarray_mcp.domain import (
    load_grid,
    compute_area_stats,
    compute_variable_info,
    compute_zonal_mean_stats,
)
from uxarray_mcp.provenance import attach_provenance


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
    if file_path.lower().startswith("healpix"):
        try:
            grid = load_grid(file_path)
            return attach_provenance(
                {
                    "format": "HEALPix",
                    "n_face": int(grid.n_face),
                    "n_node": int(grid.n_node),
                    "n_edge": int(grid.n_edge),
                    "n_max_face_nodes": int(grid.n_max_face_nodes),
                    "file_size_mb": 0.0,
                },
                tool="inspect_mesh",
                inputs={"file_path": file_path},
            )
        except ValueError:
            raise ValueError(
                "Invalid HEALPix format. Use 'healpix:<zoom_level>' (e.g., 'healpix:2')."
            )
        except Exception as e:
            raise RuntimeError(f"Failed to generate HEALPix mesh: {str(e)}")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Mesh file not found: {file_path}")

    file_size_mb = path.stat().st_size / (1024 * 1024)

    try:
        grid = ux.open_grid(file_path)
    except Exception as e:
        raise RuntimeError(f"Failed to load mesh file: {str(e)}")

    return attach_provenance(
        {
            "format": grid.source_grid_spec,
            "n_face": int(grid.n_face),
            "n_node": int(grid.n_node),
            "n_edge": int(grid.n_edge),
            "n_max_face_nodes": int(grid.n_max_face_nodes),
            "file_size_mb": round(file_size_mb, 2),
        },
        tool="inspect_mesh",
        inputs={"file_path": file_path},
    )


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
    if not Path(grid_path).exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")
    if not Path(data_path).exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    try:
        uxds = ux.open_dataset(grid_path, data_path)
    except Exception as e:
        raise RuntimeError(f"Failed to load dataset: {str(e)}")

    return attach_provenance(
        compute_variable_info(uxds, variable_name),
        tool="inspect_variable",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
        },
    )


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
    if not file_path.lower().startswith("healpix"):
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Mesh file not found: {file_path}")

    try:
        grid = load_grid(file_path)
    except ValueError:
        raise ValueError(
            "Invalid HEALPix format. Use 'healpix:<zoom_level>' (e.g., 'healpix:2')."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to load mesh file: {str(e)}")

    try:
        result = compute_area_stats(grid)
    except Exception as e:
        raise RuntimeError(f"Failed to calculate face areas: {str(e)}")

    return attach_provenance(
        result, tool="calculate_area", inputs={"file_path": file_path}
    )


def calculate_zonal_mean(
    grid_path: str,
    data_path: str,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
) -> Dict[str, Any]:
    """
    Calculate zonal mean of a face-centered variable along latitude bands.

    This tool computes averages along lines of constant latitude (non-conservative)
    or over latitude bands (conservative) using UXarray's built-in zonal_mean method.

    Args:
        grid_path: Path to the mesh grid file
        data_path: Path to the data file with variables
        variable_name: Name of the variable to compute zonal mean for
        lat_spec: Latitude specification:
            - None: Uses default (-90, 90, 10)
            - tuple (start, end, step): Latitude range and interval
            - float: Single latitude for non-conservative
            - list: Explicit latitudes or band edges
        conservative: If True, performs area-weighted averaging over latitude bands.
                     If False, performs intersection-weighted averaging at latitude lines.

    Returns:
        Dictionary containing:
        - variable_name: Name of the original variable
        - latitudes: List of latitude values/bands
        - zonal_mean_values: List of computed zonal mean values
        - conservative: Whether conservative method was used
        - grid_info: Grid summary {n_face, n_node, n_edge}

    Example:
        >>> calculate_zonal_mean("grid.nc", "data.nc", "temperature")
        {
            "variable_name": "temperature",
            "latitudes": [-90, -80, -70, ..., 80, 90],
            "zonal_mean_values": [271.5, 273.2, ..., 268.9],
            "conservative": False,
            "grid_info": {"n_face": 40962, "n_node": 20480, "n_edge": 61440}
        }
    """
    if not Path(grid_path).exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")
    if not Path(data_path).exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    try:
        uxds = ux.open_dataset(grid_path, data_path)
    except Exception as e:
        raise RuntimeError(f"Failed to load dataset: {str(e)}")

    try:
        result = compute_zonal_mean_stats(uxds, variable_name, lat_spec, conservative)
    except ValueError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to compute zonal mean: {str(e)}")

    return attach_provenance(
        result,
        tool="calculate_zonal_mean",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "lat_spec": lat_spec,
            "conservative": conservative,
        },
    )
