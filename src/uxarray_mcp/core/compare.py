"""Same-grid field comparison: bias, RMSE, pattern correlation.

Metrics are area-weighted when a grid is supplied, because a mean over cells
is not a mean over the sphere on a variable-resolution mesh. When they cannot
be weighted, or the units disagree, the result says so in ``warning_codes``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import xarray as xr

from uxarray_mcp.core.dims import FACE_DIMS
from uxarray_mcp.core.mesh import load_dataset

#: Ratio of largest to smallest face area below which weighting changes nothing.
_EQUAL_AREA_TOLERANCE = 1.000001

_UNIT_SYNONYMS = {
    "kelvin": "k",
    "degrees_kelvin": "k",
    "degk": "k",
    "celsius": "degc",
    "degrees_celsius": "degc",
    "degree_celsius": "degc",
    "c": "degc",
    "m/s": "m s-1",
    "m s^-1": "m s-1",
    "meter/second": "m s-1",
    "metre/second": "m s-1",
    "percent": "%",
    "1": "",
    "dimensionless": "",
    "none": "",
    "unitless": "",
}

METRICS = ("bias", "rmse", "pattern_correlation")


def normalize_units(units: str | None) -> str | None:
    """Fold a units string to a comparable form, or None if undeclared.

    Deliberately shallow (case, whitespace, a fixed synonym table): calling two
    equivalent spellings different costs one acknowledgement, the reverse
    silently subtracts incompatible fields.
    """
    if units is None:
        return None
    folded = " ".join(str(units).strip().lower().split())
    if not folded:
        return None
    return _UNIT_SYNONYMS.get(folded, folded)


def _load_pair(
    grid_path: str | None, data_path_a: str, data_path_b: str, variable_name: str
) -> tuple[xr.DataArray, xr.DataArray, Any | None]:
    uxgrid = None
    if grid_path:
        first_ux = load_dataset(grid_path, data_path_a)[variable_name]
        second_ux = load_dataset(grid_path, data_path_b)[variable_name]
        uxgrid = getattr(first_ux, "uxgrid", None)
        first = first_ux.to_xarray()
        second = second_ux.to_xarray()
    else:
        first = xr.open_dataset(data_path_a)[variable_name]
        second = xr.open_dataset(data_path_b)[variable_name]
    if first.shape != second.shape or first.dims != second.dims:
        raise ValueError(
            "Comparison requires same-grid, same-shape variables. "
            f"Got dims {first.dims}/{second.dims} and shapes {first.shape}/{second.shape}."
        )
    return first, second, uxgrid


def comparison_units(first: xr.DataArray, second: xr.DataArray) -> dict[str, Any]:
    """Declared units of both sides; ``comparable`` is None when one is unset."""
    left = str((first.attrs or {}).get("units", "")).strip() or None
    right = str((second.attrs or {}).get("units", "")).strip() or None
    comparable: bool | None
    if left is None or right is None:
        comparable = None
    else:
        comparable = normalize_units(left) == normalize_units(right)
    return {"a": left, "b": right, "comparable": comparable}


def area_weights(
    field: xr.DataArray, uxgrid: Any | None
) -> tuple[xr.DataArray | None, dict[str, Any]]:
    """Per-face area weights plus a disclosure of whether weighting applies."""
    face_dim = next((str(d) for d in field.dims if str(d) in FACE_DIMS), None)
    if face_dim is None:
        return None, {
            "weighted": False,
            "reason": "field is not face-centered; no area weighting applies",
        }
    if uxgrid is None:
        return None, {
            "weighted": False,
            "reason": (
                "no grid was supplied, so face areas are unknown and the "
                "metrics weight every cell equally"
            ),
        }
    try:
        areas = np.asarray(uxgrid.face_areas, dtype=float)
    except Exception as exc:  # noqa: BLE001 - a missing area is a disclosure
        return None, {
            "weighted": False,
            "reason": f"face areas unavailable from the grid ({exc})",
        }
    if areas.shape != (field.sizes[face_dim],):
        return None, {
            "weighted": False,
            "reason": (
                f"face_areas has shape {areas.shape}, which does not match the "
                f"{face_dim} length {field.sizes[face_dim]}"
            ),
        }
    ratio = float(areas.max() / areas.min()) if areas.min() > 0 else float("inf")
    return xr.DataArray(areas, dims=[face_dim]), {
        "weighted": True,
        "face_dim": face_dim,
        "area_ratio_max_over_min": ratio,
        "equal_area": ratio <= _EQUAL_AREA_TOLERANCE,
    }


def weighted_mean(field: xr.DataArray, weights: xr.DataArray | None) -> float:
    """Mean over finite values, area-weighted when weights are given."""
    if weights is None:
        return float(field.mean(skipna=True).item())
    return float(field.weighted(weights).mean(skipna=True).item())


def pattern_correlation(
    first: xr.DataArray, second: xr.DataArray, weights: xr.DataArray | None = None
) -> float:
    """Pearson correlation over finite pairs, area-weighted when possible."""
    a = np.asarray(first.values).ravel()
    b = np.asarray(second.values).ravel()
    if weights is None:
        w = np.ones_like(a, dtype=float)
    else:
        w = np.asarray(weights.broadcast_like(first).values, dtype=float).ravel()
    mask = np.isfinite(a) & np.isfinite(b) & np.isfinite(w)
    if not mask.any():
        raise ValueError("No finite overlapping values available for correlation.")
    a, b, w = a[mask], b[mask], w[mask]
    wsum = w.sum()
    if wsum <= 0:
        raise ValueError("Area weights sum to zero; correlation is undefined.")
    a = a - (w * a).sum() / wsum
    b = b - (w * b).sum() / wsum
    denom = np.sqrt((w * a * a).sum() * (w * b * b).sum())
    if denom == 0:
        return 0.0
    return float((w * a * b).sum() / denom)


def compare_fields(
    variable_name: str,
    data_path_a: str,
    data_path_b: str,
    grid_path: str | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    """Difference ``a - b`` with bias, rmse and pattern correlation.

    ``metric`` narrows the result to one of ``bias``, ``rmse`` or
    ``pattern_correlation`` as a top-level key, keeping the weighting and units
    disclosures. ``_payload`` is the difference field.
    """
    if metric is not None and metric not in METRICS:
        raise ValueError(f"Unknown metric {metric!r}; expected one of {METRICS}.")
    first, second, uxgrid = _load_pair(
        grid_path, data_path_a, data_path_b, variable_name
    )
    units = comparison_units(first, second)
    diff = first - second
    weights, weighting = area_weights(diff, uxgrid)
    metrics = {
        "bias": weighted_mean(diff, weights),
        "rmse": float(np.sqrt(weighted_mean(diff**2, weights))),
        "pattern_correlation": pattern_correlation(first, second, weights),
        "max_abs_difference": float(np.nanmax(np.abs(diff.values))),
    }

    warnings: list[str] = []
    warning_codes: list[str] = []
    if not weighting["weighted"]:
        warning_codes.append("AREA_WEIGHTING_UNAVAILABLE")
        warnings.append(
            "bias, rmse and pattern_correlation weight every cell equally "
            f"because {weighting['reason']}. On a variable-resolution mesh "
            "that is a mean over cells, not over the sphere."
        )
    if units["comparable"] is None:
        warning_codes.append("UNITS_UNDECLARED")
        warnings.append(
            f"units_a={units['a'] or 'unset'!r}, units_b={units['b'] or 'unset'!r}: "
            "at least one field does not declare its units, so nothing here "
            "confirms the two are on the same scale. bias and rmse carry the "
            "units of the difference only if they are."
        )
    elif not units["comparable"]:
        warning_codes.append("UNITS_MISMATCHED")
        warnings.append(
            f"units_a={units['a']!r} and units_b={units['b']!r} do not match, "
            "so the difference mixes two scales. A K-versus-degC comparison "
            "reports the 273.15 offset as if it were model error."
        )

    result: dict[str, Any] = {
        "variable_name": variable_name,
        "alignment_summary": {
            "same_dims": True,
            "dims": [str(d) for d in first.dims],
            "shape": list(first.shape),
            "grid_path": grid_path,
        },
        "metrics": metrics,
        "area_weighting": weighting,
        "units": units,
        "coverage": {
            "n_elements": int(diff.size),
            "n_elements_finite": int(np.isfinite(diff.values).sum()),
        },
        "warning_codes": warning_codes,
        "warnings": warnings,
        "_payload": diff,
    }
    if metric is not None:
        result[metric] = metrics[metric]
    return result


def bias(
    variable_name: str, data_path_a: str, data_path_b: str, grid_path: str | None = None
) -> dict[str, Any]:
    """Area-weighted mean of ``a - b``."""
    return compare_fields(variable_name, data_path_a, data_path_b, grid_path, "bias")


def rmse(
    variable_name: str, data_path_a: str, data_path_b: str, grid_path: str | None = None
) -> dict[str, Any]:
    """Area-weighted root-mean-square of ``a - b``."""
    return compare_fields(variable_name, data_path_a, data_path_b, grid_path, "rmse")


def pattern_correlation_fields(
    variable_name: str, data_path_a: str, data_path_b: str, grid_path: str | None = None
) -> dict[str, Any]:
    """Area-weighted Pearson correlation between ``a`` and ``b``."""
    return compare_fields(
        variable_name, data_path_a, data_path_b, grid_path, "pattern_correlation"
    )
