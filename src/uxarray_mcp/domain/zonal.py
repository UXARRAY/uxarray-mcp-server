"""Shared zonal mean computation logic."""

from __future__ import annotations

from typing import Any, Optional

from uxarray_mcp.domain.dims import face_slice_selection
from uxarray_mcp.domain.profile_coverage import compute_profile_coverage


def compute_zonal_mean_stats(
    uxds: Any,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
    time_index: int = 0,
    level_index: int = 0,
) -> dict:
    """Compute zonal mean statistics from a loaded UXarray dataset.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset.
    variable_name : str
        Name of face-centered variable to average.
    lat_spec : tuple | float | list | None
        Latitude specification for zonal bands.
    conservative : bool
        If True, use area-weighted conservative averaging.
    time_index : int
        Index used to reduce any non-latitude dimension (e.g. time) so the
        returned profile is 1-D.

    Returns
    -------
    dict
        Keys: variable_name, latitudes, zonal_mean_values, conservative, grid_info
    """
    if variable_name not in uxds.data_vars:
        available = list(uxds.data_vars.keys())
        raise ValueError(
            f"Variable '{variable_name}' not found. Available variables: {available}"
        )

    var = uxds[variable_name]

    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Zonal mean only supports face-centered data."
        )

    if lat_spec is not None:
        zonal_result = var.zonal_mean(lat=lat_spec, conservative=conservative)
    else:
        zonal_result = var.zonal_mean(conservative=conservative)

    latitudes, zonal_mean_values, reduced_dims = extract_profile(
        zonal_result, "latitudes", time_index=time_index, level_index=level_index
    )

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
        "reduced_dims": reduced_dims,
        "grid_info": grid_info,
        # Bands the caller asked for need not touch the mesh. A regional mesh
        # asked for bands it does not span returns a profile of the right
        # length made of NaN, which reads as an answer unless it is counted.
        "profile_coverage": compute_profile_coverage(zonal_mean_values, source=var),
    }


def compute_zonal_anomaly_stats(
    uxds: Any,
    variable_name: str,
    lat_spec: Optional[tuple | float | list] = None,
    conservative: bool = False,
) -> dict:
    """Compute zonal-anomaly statistics from a loaded UXarray dataset.

    The zonal anomaly is each face value minus the zonal mean of its latitude
    band, producing a per-face field with the same shape as the input variable.

    Parameters
    ----------
    uxds : ux.UxDataset
        Loaded UXarray dataset.
    variable_name : str
        Name of the face-centered variable.
    lat_spec : tuple | float | list | None
        Latitude band specification passed through to ``zonal_anomaly``. A
        ``(start, end, step)`` tuple or explicit band edges. ``None`` uses the
        UXarray default ``(-90, 90, 10)``.
    conservative : bool
        If True, use area-weighted band means.

    Returns
    -------
    dict
        Keys: variable_name, conservative, n_face, stats (min/max/mean/std of
        the anomaly field), grid_info.

    Raises
    ------
    ValueError
        If the variable is missing, is not face-centered, or ``lat_spec`` is
        not a shape ``zonal_anomaly`` accepts.
    NotImplementedError
        If the installed UXarray does not provide ``UxDataArray.zonal_anomaly``.
    """
    import numpy as np

    if variable_name not in uxds.data_vars:
        available = list(uxds.data_vars.keys())
        raise ValueError(
            f"Variable '{variable_name}' not found. Available variables: {available}"
        )

    var = uxds[variable_name]

    if "n_face" not in var.dims and "nCells" not in var.dims:
        raise ValueError(
            f"Variable '{variable_name}' is not face-centered. "
            "Zonal anomaly only supports face-centered data."
        )

    if not hasattr(var, "zonal_anomaly"):
        raise NotImplementedError(
            "zonal_anomaly requires a UXarray release that provides "
            "UxDataArray.zonal_anomaly. Upgrade uxarray to use this operation."
        )

    # UXarray >=2026.8.0 raises TypeError for a malformed ``lat`` (it raised
    # ValueError before). Either way the caller supplied a bad argument, not a
    # bad type of call, so normalize it to the ValueError this module uses for
    # every other input problem and name the accepted forms.
    try:
        if lat_spec is not None:
            result = var.zonal_anomaly(lat=lat_spec, conservative=conservative)
        else:
            result = var.zonal_anomaly(conservative=conservative)
    except TypeError as exc:
        raise ValueError(
            f"Invalid lat_spec {lat_spec!r} for zonal_anomaly. Pass a tuple "
            "(start, end, step), array-like band edges, or omit it to use the "
            f"default bands. UXarray reported: {exc}"
        ) from None

    vals = result.values
    finite = vals[np.isfinite(vals)]
    stats: dict[str, float | None]
    if finite.size > 0:
        stats = {
            "min": float(finite.min()),
            "max": float(finite.max()),
            "mean": float(finite.mean()),
            "std": float(finite.std()),
        }
    else:
        stats = {"min": None, "max": None, "mean": None, "std": None}

    return {
        "variable_name": variable_name,
        "conservative": conservative,
        "n_face": int(uxds.uxgrid.n_face),
        "stats": stats,
        "interpretation": "per-face deviation from the zonal mean of its latitude band",
        "grid_info": {
            "n_face": int(uxds.uxgrid.n_face),
            "n_node": int(uxds.uxgrid.n_node),
            "n_edge": int(uxds.uxgrid.n_edge),
        },
    }


def extract_profile(
    result: Any,
    coord_name: str,
    time_index: int = 0,
    level_index: int = 0,
) -> tuple[list, list, dict]:
    """Return ``(coordinate_values, profile_values, reduced_dims)``.

    ``zonal_mean``/``azimuthal_mean`` place their new coordinate at the former
    face-axis position, which is *not* necessarily axis 0: a variable with dims
    ``(time, n_face)`` reduces to ``(time, latitudes)``.  Selecting the
    coordinate positionally therefore returns the time axis and silently
    mislabels time indices as degrees, so the coordinate is always looked up by
    name.

    Any remaining dimension is collapsed to a single index so callers get the
    1-D series a line plot requires.  Which index is used depends on the
    dimension: a time axis uses ``time_index``, a vertical axis uses
    ``level_index``, anything else (an ensemble member) uses 0, because
    neither selector says anything about it.  The classification is shared
    with the plotting and vector-calculus paths via
    :func:`uxarray_mcp.domain.dims.face_slice_selection`, so the three cannot
    drift on what counts as a time axis.  Every collapse is reported in
    ``reduced_dims`` -- returning a profile that is one slice of a
    multi-level field without saying so is how a caller ends up believing a
    single level is the whole answer.
    """
    if coord_name in result.coords:
        coords = result.coords[coord_name].values.tolist()
    else:
        # Older UXarray builds may not name the coordinate; the reduced axis is
        # always the trailing one in that case.
        coord_name = result.dims[-1]
        coords = result.coords[coord_name].values.tolist()

    # The axis to keep here is the new coordinate, not a face dimension.
    selection, reduced = face_slice_selection(
        result.sizes,
        time_index=time_index,
        level_index=level_index,
        keep=[coord_name],
    )

    if selection:
        result = result.isel(**selection)
    return coords, result.values.tolist(), reduced
