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

    # Validate variable exists
    if variable_name not in uxds.data_vars:
        available = list(uxds.data_vars.keys())
        raise ValueError(
            f"Variable '{variable_name}' not found. Available variables: {available}"
        )

    # Get the data array
    var = uxds[variable_name]

    # Validate variable is face-centered
    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. Zonal mean only supports face-centered data."
        )

    # Compute zonal mean using UXarray's built-in method
    try:
        if lat_spec is not None:
            zonal_result = var.zonal_mean(lat=lat_spec, conservative=conservative)
        else:
            zonal_result = var.zonal_mean(conservative=conservative)
    except Exception as e:
        raise RuntimeError(f"Failed to compute zonal mean: {str(e)}")

    # Extract results
    latitudes = zonal_result.coords["latitudes"].values.tolist()
    zonal_mean_values = zonal_result.values.tolist()

    # Get grid context
    grid_info = {
        "n_face": int(uxds.uxgrid.n_face),
        "n_node": int(uxds.uxgrid.n_node),
        "n_edge": int(uxds.uxgrid.n_edge),
    }

    return {
        "variable_name": variable_name,
        "latitudes": latitudes,
        "zonal_mean_values": zonal_mean_values,
        "conservative": conservative,
        "grid_info": grid_info,
    }


def validate_dataset(grid_path: str, data_path: str) -> Dict[str, Any]:
    """
    Validate dataset quality and detect common data issues.

    Checks for NaN/Inf values, coordinate validity, and provides data quality
    summary for all variables in the dataset.

    Args:
        grid_path: Path to the mesh grid file
        data_path: Path to the data file with variables

    Returns:
        Dictionary containing:
        - is_valid: Overall validation status (bool)
        - issues: List of detected issues
        - variables: Per-variable validation results with:
          - name: Variable name
          - has_nan: Boolean, True if NaN values present
          - has_inf: Boolean, True if Inf values present
          - nan_count: Number of NaN values
          - inf_count: Number of Inf values
          - total_values: Total number of values
          - nan_percentage: Percentage of NaN values
          - value_range: [min, max] for numeric variables
        - grid_info: Grid summary {n_face, n_node, n_edge}

    Example:
        >>> validate_dataset("grid.nc", "data.nc")
        {
            "is_valid": True,
            "issues": [],
            "variables": [
                {
                    "name": "temperature",
                    "has_nan": False,
                    "has_inf": False,
                    "nan_count": 0,
                    "inf_count": 0,
                    "total_values": 40962,
                    "nan_percentage": 0.0,
                    "value_range": [271.5, 303.2]
                }
            ],
            "grid_info": {"n_face": 40962, "n_node": 20480, "n_edge": 61440}
        }
    """
    grid_path_obj = Path(grid_path)
    data_path_obj = Path(data_path)

    if not grid_path_obj.exists():
        raise FileNotFoundError(f"Grid file not found: {grid_path}")
    if not data_path_obj.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    try:
        uxds = ux.open_dataset(grid_path, data_path)
    except Exception as e:
        raise RuntimeError(f"Failed to load dataset: {str(e)}")

    issues = []
    variable_results = []

    for var_name in uxds.data_vars:
        try:
            var = uxds[var_name]
            values = var.values

            if not np.issubdtype(values.dtype, np.number):
                continue

            nan_mask = np.isnan(values)
            inf_mask = np.isinf(values)
            nan_count = int(np.sum(nan_mask))
            inf_count = int(np.sum(inf_mask))
            total_values = int(values.size)
            nan_percentage = (
                (nan_count / total_values * 100) if total_values > 0 else 0.0
            )

            fill_value = var.attrs.get("_FillValue", None)
            has_fill_value = fill_value is not None
            fill_value_count = 0
            if has_fill_value:
                fill_value_mask = np.isclose(values, fill_value, rtol=0, atol=0)
                fill_value_count = int(np.sum(fill_value_mask))

            common_fill_values = [9999, -9999, 999999, -999999, 9.96921e36]
            suspicious_fill_count = 0
            for fill_val in common_fill_values:
                suspicious_mask = np.isclose(values, fill_val, rtol=1e-5)
                suspicious_fill_count += int(np.sum(suspicious_mask))

            valid_values = values[~nan_mask & ~inf_mask]
            value_range = None
            if valid_values.size > 0:
                value_range = [float(np.min(valid_values)), float(np.max(valid_values))]

            has_nan = nan_count > 0
            has_inf = inf_count > 0

            if has_nan:
                issues.append(
                    f"{var_name}: contains {nan_count} NaN values ({nan_percentage:.2f}%)"
                )
            if has_inf:
                issues.append(f"{var_name}: contains {inf_count} Inf values")
            if fill_value_count > 0:
                issues.append(
                    f"{var_name}: contains {fill_value_count} fill values ({fill_value})"
                )
            if suspicious_fill_count > 0:
                issues.append(
                    f"{var_name}: contains {suspicious_fill_count} suspicious fill-like values"
                )

            coord_issues = []
            if "lat" in var_name.lower() or "latitude" in var_name.lower():
                if value_range and (value_range[0] < -90 or value_range[1] > 90):
                    coord_issues.append("latitude out of valid range [-90, 90]")
            if "lon" in var_name.lower() or "longitude" in var_name.lower():
                if value_range and (value_range[0] < -180 or value_range[1] > 360):
                    coord_issues.append("longitude out of valid range [-180, 360]")

            if coord_issues:
                issues.extend([f"{var_name}: {issue}" for issue in coord_issues])

            variable_results.append(
                {
                    "name": var_name,
                    "has_nan": has_nan,
                    "has_inf": has_inf,
                    "nan_count": nan_count,
                    "inf_count": inf_count,
                    "fill_value_count": fill_value_count,
                    "suspicious_fill_count": suspicious_fill_count,
                    "total_values": total_values,
                    "nan_percentage": round(nan_percentage, 2),
                    "value_range": value_range,
                    "coordinate_issues": coord_issues if coord_issues else None,
                }
            )

        except Exception as e:
            issues.append(f"{var_name}: validation failed - {str(e)}")

    grid_info = {
        "n_face": int(uxds.uxgrid.n_face),
        "n_node": int(uxds.uxgrid.n_node),
        "n_edge": int(uxds.uxgrid.n_edge),
    }

    is_valid = len(issues) == 0

    return {
        "is_valid": is_valid,
        "issues": issues,
        "variables": variable_results,
        "grid_info": grid_info,
    }
