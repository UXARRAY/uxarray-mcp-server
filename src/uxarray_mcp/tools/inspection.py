import uxarray as ux
from pathlib import Path
from typing import Dict, Any

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
            zoom = int(parts[1]) if len(parts) > 1 else 1 # Default to zoom 1 if not specified
            
            grid = ux.Grid.from_healpix(zoom=zoom)
            file_size_mb = 0.0 # Virtual mesh, no file size
            
            # Extract topology information
            result = {
                "format": "HEALPix",
                "n_face": int(grid.n_face),
                "n_node": int(grid.n_node),
                "n_edge": int(grid.n_edge),
                "n_max_face_nodes": int(grid.n_max_face_nodes),
                "file_size_mb": 0.0
            }
            return result
        except ValueError:
             raise ValueError("Invalid HEALPix format. Use 'healpix:<zoom_level>' (e.g., 'healpix:2').")
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
        "file_size_mb": round(file_size_mb, 2)
    }

    return result
