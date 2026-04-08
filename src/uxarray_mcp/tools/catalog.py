"""Dataset catalog and discovery tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from uxarray_mcp.provenance import attach_provenance
from uxarray_mcp.remote.agent import get_agent
from uxarray_mcp.remote.config import load_config
from uxarray_mcp.tools.remote_tools import _endpoint_is_ready

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
    use_remote: bool = False,
) -> Dict[str, Any]:
    """Scan a directory for mesh and data files and return a structured catalog.

    Discovers NetCDF, HDF5, and GRIB files and groups them by subdirectory.
    Each entry includes file size, a heuristic classification (grid vs data),
    and example tool invocations so you can immediately act on the results.

    When use_remote=True and an HPC endpoint is configured, the directory scan
    is executed on the remote worker — enabling discovery of datasets that live
    entirely on the HPC filesystem without mounting them locally.

    Args:
        directory: Path to scan (local, or HPC filesystem when use_remote=True).
        recursive: If True, scan subdirectories recursively (default False).
        max_files: Maximum number of files to return (default 200). Prevents
                   accidentally scanning enormous directory trees.
        use_remote: If True and HPC is configured, run the scan on the remote
                    endpoint so that HPC-only paths are visible.

    Returns:
        Dictionary containing:
        - directory: The scanned path
        - total_files: Total number of matching files found
        - truncated: True if results were capped at max_files
        - groups: Files grouped by subdirectory, each with path, size_mb,
                  kind ("grid", "data", or "unknown"), and suggested tools
        - recommendations: Suggested next steps based on what was found
        - execution_venue: "local" or "hpc:<endpoint_id>"
        - _provenance: Provenance metadata

    Examples:
        Scan a local directory::

            list_datasets("/data/mpas")

        Scan an HPC directory without mounting it locally::

            list_datasets("/home/jain/uxarray/data", use_remote=True)

        Scan recursively with a higher limit::

            list_datasets("/lus/grand/projects/climate", recursive=True, max_files=500)
    """
    if use_remote:
        return _list_datasets_remote(directory, recursive, max_files)

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
        "execution_venue": "local",
    }

    return attach_provenance(
        result,
        tool="list_datasets",
        inputs={
            "directory": directory,
            "recursive": recursive,
            "max_files": max_files,
            "use_remote": False,
        },
    )


def _remote_catalog_fn(
    directory: str, recursive: bool, max_files: int
) -> Dict[str, Any]:
    """Self-contained catalog scan for execution on a remote HPC worker.

    This function has no imports from uxarray_mcp so it can be serialized
    by AllCodeStrategies and executed on the HPC endpoint.
    """
    from pathlib import Path

    _MESH_EXTENSIONS = {".nc", ".nc4", ".h5", ".he5", ".grb", ".grib"}
    _GRID_HINTS = {"grid", "mesh", "topo", "coord", "geo"}
    _DATA_HINTS = {"data", "output", "field", "var", "diag", "hist"}

    def _classify(name: str) -> str:
        lower = name.lower()
        if any(h in lower for h in _GRID_HINTS):
            return "grid"
        if any(h in lower for h in _DATA_HINTS):
            return "data"
        return "unknown"

    root = Path(directory)
    if not root.exists():
        return {"error": f"Directory not found: {directory}"}
    if not root.is_dir():
        return {"error": f"Not a directory: {directory}"}

    glob_fn = root.rglob if recursive else root.glob
    all_files: list[Path] = []
    for ext in _MESH_EXTENSIONS:
        all_files.extend(glob_fn(f"*{ext}"))

    all_files = sorted(set(all_files))
    truncated = len(all_files) > max_files
    all_files = all_files[:max_files]

    groups_map: Dict[str, List] = {}
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

    recommendations = []
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

    return {
        "directory": str(root),
        "total_files": len(all_files),
        "truncated": truncated,
        "groups": groups,
        "recommendations": recommendations,
    }


def _list_datasets_remote(
    directory: str, recursive: bool, max_files: int
) -> Dict[str, Any]:
    """Run list_datasets on the configured HPC endpoint."""
    config = load_config()
    if not config.has_endpoint:
        raise RuntimeError(
            "No HPC endpoint configured. Set endpoint_id in config.yaml "
            "or the GLOBUS_COMPUTE_ENDPOINT_ID environment variable."
        )

    agent = get_agent()
    ready, reason = _endpoint_is_ready(agent)
    if not ready:
        raise RuntimeError(
            f"HPC endpoint not ready ({reason}). Remote catalog scan not submitted."
        )

    try:
        from globus_compute_sdk import Executor
        from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer
    except ImportError as exc:
        raise RuntimeError(
            "HPC dependencies not installed. Run: uv sync --extra hpc"
        ) from exc

    executor = Executor(
        endpoint_id=config.endpoint_id,
        serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
    )
    future = executor.submit(_remote_catalog_fn, directory, recursive, max_files)
    raw = future.result(timeout=config.timeout_seconds)

    if "error" in raw:
        raise FileNotFoundError(raw["error"])

    raw["execution_venue"] = f"hpc:{config.endpoint_id}"
    return attach_provenance(
        raw,
        tool="list_datasets",
        inputs={
            "directory": directory,
            "recursive": recursive,
            "max_files": max_files,
            "use_remote": True,
        },
        venue=f"hpc:{config.endpoint_id}",
    )
