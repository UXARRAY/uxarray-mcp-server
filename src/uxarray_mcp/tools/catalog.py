"""Dataset catalog and discovery tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from uxarray_mcp.provenance import attach_provenance

# File extensions recognised as potential mesh/data files
_MESH_EXTENSIONS = {".nc", ".nc4", ".h5", ".he5", ".grb", ".grib"}

# Heuristic: filenames containing these substrings are likely grid files
_GRID_HINTS = {"grid", "mesh", "topo", "coord", "geo"}

# Heuristic: filenames containing these are likely data files
_DATA_HINTS = {"data", "output", "field", "var", "diag", "hist"}


def _classify(name: str) -> str:
    """Guess whether a filename is a grid, data, or unknown file."""
    lower = name.lower()
    if any(h in lower for h in _GRID_HINTS):
        return "grid"
    if any(h in lower for h in _DATA_HINTS):
        return "data"
    return "unknown"


def list_datasets(
    directory: str,
    recursive: bool = False,
    max_files: int = 200,
) -> Dict[str, Any]:
    """Scan a directory for mesh and data files and return a structured catalog.

    Discovers NetCDF, HDF5, and GRIB files and groups them by subdirectory.
    Each entry includes file size, a heuristic classification (grid vs data),
    and example tool invocations so you can immediately act on the results.

    Args:
        directory: Local path to scan.
        recursive: If True, scan subdirectories recursively (default False).
        max_files: Maximum number of files to return (default 200). Prevents
                   accidentally scanning enormous directory trees.

    Returns:
        Dictionary containing:
        - directory: The scanned path
        - total_files: Total number of matching files found
        - truncated: True if results were capped at max_files
        - groups: Files grouped by subdirectory, each with path, size_mb,
                  kind ("grid", "data", or "unknown"), and suggested tools
        - recommendations: Suggested next steps based on what was found
        - _provenance: Provenance metadata

    Examples:
        Scan a local directory::

            list_datasets("/data/mpas")

        Scan recursively with a higher limit::

            list_datasets("/lus/grand/projects/climate", recursive=True, max_files=500)
    """
    root = Path(directory)
    if not root.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    if not root.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    # Gather files
    glob_fn = root.rglob if recursive else root.glob
    all_files: List[Path] = []
    for ext in _MESH_EXTENSIONS:
        all_files.extend(glob_fn(f"*{ext}"))

    all_files = sorted(set(all_files))
    truncated = len(all_files) > max_files
    all_files = all_files[:max_files]

    # Group by parent directory
    groups_map: Dict[str, List[Dict[str, Any]]] = {}
    grid_found = False
    data_found = False

    for f in all_files:
        try:
            size_mb = round(f.stat().st_size / 1_048_576, 3)
        except OSError:
            size_mb = None

        kind = _classify(f.name)
        if kind == "grid":
            grid_found = True
        elif kind == "data":
            data_found = True

        # Suggest the most immediately useful tool
        if kind == "grid":
            suggested = f'inspect_mesh("{f}")'
        elif kind == "data":
            suggested = f'inspect_variable("<grid_path>", "{f}")'
        else:
            suggested = f'inspect_mesh("{f}")'

        rel_dir = str(f.parent.relative_to(root)) if f.parent != root else "."
        groups_map.setdefault(rel_dir, []).append(
            {
                "path": str(f),
                "name": f.name,
                "size_mb": size_mb,
                "kind": kind,
                "suggested_tool": suggested,
            }
        )

    groups = [
        {"subdir": subdir, "files": files}
        for subdir, files in sorted(groups_map.items())
    ]

    # Build recommendations
    recommendations: List[str] = []
    if not all_files:
        recommendations.append(
            f"No mesh or data files found in {directory}. "
            "Try recursive=True or check the path."
        )
    else:
        if grid_found and data_found:
            recommendations.append(
                "Grid and data files detected. "
                "Pair a grid file with a data file using inspect_variable, "
                "plot_variable, or run_scientific_agent."
            )
        elif grid_found:
            recommendations.append(
                "Grid files found. Use inspect_mesh to explore topology, "
                "or calculate_area for face area statistics."
            )
        elif data_found:
            recommendations.append(
                "Data files found but no obvious grid files. "
                "Some MPAS and UGRID files contain both grid and data — "
                "try inspect_mesh on the data file directly."
            )
        if truncated:
            recommendations.append(
                f"Results truncated at {max_files} files. "
                "Use recursive=False or increase max_files to see more."
            )

    result: Dict[str, Any] = {
        "directory": str(root),
        "total_files": len(all_files),
        "truncated": truncated,
        "groups": groups,
        "recommendations": recommendations,
    }

    return attach_provenance(
        result,
        tool="list_datasets",
        inputs={
            "directory": directory,
            "recursive": recursive,
            "max_files": max_files,
        },
    )
