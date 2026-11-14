"""Scan a directory for mesh/data files and describe each from its header.

Classification reads the file header (dimensions, attributes), not the
filename, so ``WC14to60E2r5.nc`` is a grid because it has ``nCells`` and
``nVertices``, not because its name says so.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uxarray_mcp.core.facts import header_facts

EXTENSIONS = {".nc", ".nc4", ".h5", ".he5", ".g", ".exo", ".e", ".zarr"}

#: Header reads above this many files get skipped so a scan stays fast.
HEADER_READ_LIMIT = 200


def scan(
    directory: str, recursive: bool = False, max_files: int = 200
) -> dict[str, Any]:
    """List candidate files under ``directory`` with header-only facts."""
    root = Path(directory).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"{directory} is not a directory")
    it = root.rglob("*") if recursive else root.iterdir()
    paths = sorted(
        p
        for p in it
        if p.suffix.lower() in EXTENSIONS and (p.is_file() or p.suffix == ".zarr")
    )
    truncated = len(paths) > max_files
    paths = paths[:max_files]

    files: list[dict[str, Any]] = []
    for i, path in enumerate(paths):
        entry: dict[str, Any] = {"path": str(path)}
        try:
            entry["size_mb"] = round(path.stat().st_size / 1e6, 2)
        except OSError:
            pass
        if i < HEADER_READ_LIMIT:
            try:
                facts = header_facts(str(path))
                for key in (
                    "format",
                    "role",
                    "n_face",
                    "n_node",
                    "n_time",
                    "size_class",
                    "variables_face_centered",
                ):
                    if facts.get(key) is not None:
                        entry[key] = facts[key]
            except Exception as exc:
                entry["role"] = "unknown"
                entry["header_error"] = f"{type(exc).__name__}: {exc}"[:200]
        files.append(entry)

    subdirs: list[str] = []
    if not files and not recursive:
        try:
            subdirs = sorted(p.name for p in root.iterdir() if p.is_dir())[:20]
        except OSError:
            pass
    return {
        "directory": str(root),
        "total_files": len(files),
        "truncated": truncated,
        "files": files,
        "subdirectories": subdirs,
        "grids": [f["path"] for f in files if f.get("role") in ("grid", "grid+data")],
        "data_files": [
            f["path"] for f in files if f.get("role") in ("data", "grid+data")
        ],
    }
