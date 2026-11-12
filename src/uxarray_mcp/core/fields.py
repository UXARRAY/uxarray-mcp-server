"""Load a face-centred field and summarise grids/arrays/datasets for results."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import numpy as np

from uxarray_mcp.core.dims import FACE_DIMS
from uxarray_mcp.core.mesh import load_dataset


def load_face_variable(
    grid_path: str, data_path: str, variable_name: str | None
) -> tuple[Any, Any, str]:
    """Open ``data_path`` on ``grid_path`` and pick ``variable_name`` or the first
    face-centred variable. Returns ``(uxds, uxda, name)``."""
    uxds = load_dataset(grid_path, data_path)
    selected = variable_name
    if selected is None:
        for name, var in uxds.data_vars.items():
            if FACE_DIMS & set(var.dims):
                selected = name
                break
    if selected is None:
        raise ValueError("No face-centered variable found in dataset.")
    if selected not in uxds.data_vars:
        raise ValueError(
            f"Variable '{selected}' not found. Available variables: {list(uxds.data_vars)}"
        )
    return uxds, uxds[selected], selected


def summarize_grid(grid: Any) -> dict[str, Any]:
    """Format and element counts of a grid."""
    return {
        "format": str(getattr(grid, "source_grid_spec", "Unknown")),
        "n_face": int(getattr(grid, "n_face", 0)),
        "n_node": int(getattr(grid, "n_node", 0)),
        "n_edge": int(getattr(grid, "n_edge", 0)),
    }


def summarize_array(data: Any) -> dict[str, Any]:
    """Shape, dtype and finite-only min/max/mean; ``n_finite``/``n_total``
    appear only when values are missing, and nothing finite reports None."""
    values = np.asarray(data.values)
    summary: dict[str, Any] = {
        "dims": list(data.dims),
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "name": str(data.name) if data.name is not None else None,
    }
    if values.size == 0:
        return summary

    with suppress(Exception):
        if np.issubdtype(values.dtype, np.inexact):
            finite = np.isfinite(values)
            n_finite = int(finite.sum())
            if n_finite != values.size:
                summary["n_finite"] = n_finite
                summary["n_total"] = int(values.size)
            usable = values[finite]
            summary["min"] = float(usable.min()) if n_finite else None
            summary["max"] = float(usable.max()) if n_finite else None
            summary["mean"] = float(usable.mean()) if n_finite else None
        else:
            summary["min"] = float(values.min())
            summary["max"] = float(values.max())
            summary["mean"] = float(values.mean())
    return summary


def summarize_dataset(dataset: Any) -> dict[str, Any]:
    """Variable names and dimension sizes."""
    return {
        "variables": list(dataset.data_vars),
        "dims": {str(k): int(v) for k, v in dataset.sizes.items()},
    }
