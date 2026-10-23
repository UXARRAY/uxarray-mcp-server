"""Selection and element-transfer operations that ``run_analysis`` lacked.

Two tools, kept out of ``run_analysis`` on purpose. That front door is
already 46 parameters across 25 operations and #89 tracks splitting it;
adding a radius, a neighbour count, a centre and a destination element to
it would have made the measured problem worse to fix a different one.
Each tool here takes only the arguments its own operation can use.

Both were found by replaying the notebooks in UXARRAY/uxarray-community
through the server: ``subset.bounding_circle`` and
``subset.nearest_neighbor`` appear four times each, and
``topological_mean("face")`` three times -- the last one in the step that
moves node-centred vorticity onto faces before anything else can be done
with it. Before this, a caller handed node-centred data was told
"Variable 't_node' is not face-centered", which is true, and given no way
to act on it.
"""

from __future__ import annotations

from typing import Any

from uxarray_mcp.domain.mesh import load_grid
from uxarray_mcp.domain.subset_coverage import compute_subset_coverage, mesh_extent
from uxarray_mcp.provenance import attach_provenance
from uxarray_mcp.state import (
    OperationTracker,
    summarize_array,
    summarize_grid,
)
from uxarray_mcp.tools.advanced import (
    _load_dataarray,
    _persist_dataarray_result,
    _persist_grid_result,
    _resolve_paths,
)

#: ``topological_*`` reductions a caller may ask for by name.
#:
#: ``prod`` and the boolean pair are left out: a product over neighbouring
#: elements has no physical reading for a geophysical field, and the
#: server's operations are all on float fields. See
#: ``domain/uxarray_surface.py`` for the full record.
TOPOLOGICAL_STATISTICS: tuple[str, ...] = (
    "mean",
    "min",
    "max",
    "sum",
    "std",
    "var",
    "median",
)

#: Mesh elements a field can be carried onto.
ELEMENTS: tuple[str, ...] = ("node", "edge", "face")


def subset_advanced(
    selection: str,
    center_lon: float,
    center_lat: float,
    radius: float | None = None,
    k: int | None = None,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    session_id: str | None = None,
    dataset_handle: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Select faces near a point, by radius or by neighbour count.

    Args:
        selection: ``"circle"`` keeps every face within ``radius`` degrees
            of the centre. ``"nearest"`` keeps the ``k`` closest faces
            regardless of how far away they are.
        center_lon: Centre longitude in degrees.
        center_lat: Centre latitude in degrees.
        radius: Great-circle radius in degrees. Required for ``"circle"``.
        k: Number of faces to keep. Required for ``"nearest"``.
        grid_path: Mesh file, or ``healpix:<zoom>``.
        data_path: Optional data file; without it the mesh alone is subset.
        variable_name: Field to carry through the selection.
        session_id: Session to track this operation under.
        dataset_handle: Registered dataset to use instead of paths.
        result_name: Name for the persisted result.

    Returns:
        The selected grid or field, with ``subset_coverage`` reporting how
        much of the source mesh was kept.

    Raises:
        ValueError: Unknown ``selection``, a missing or non-positive
            ``radius``/``k``, or a selection that kept nothing.
    """
    if selection not in ("circle", "nearest"):
        raise ValueError(
            f"Unknown selection {selection!r}; expected 'circle' or 'nearest'."
        )
    if selection == "circle":
        if radius is None:
            raise ValueError("selection='circle' requires radius (in degrees).")
        if radius <= 0:
            raise ValueError(f"radius must be positive, got {radius}.")
    else:
        if k is None:
            raise ValueError("selection='nearest' requires k (number of faces).")
        if k < 1:
            raise ValueError(f"k must be at least 1, got {k}.")

    tracker = OperationTracker("subset_advanced", session_id=session_id)
    tracker.stage("loading", "Loading grid and optional dataset.")
    resolved_grid, resolved_data = _resolve_paths(
        session_id=session_id,
        dataset_handle=dataset_handle,
        grid_path=grid_path,
        data_path=data_path,
    )
    grid = load_grid(resolved_grid)
    center = (center_lon, center_lat)
    rule = "face_center_within_radius" if selection == "circle" else "k_nearest_faces"

    def _apply(obj):
        if selection == "circle":
            return obj.subset.bounding_circle(center_coord=center, r=radius)
        return obj.subset.nearest_neighbor(center_coord=center, k=k)

    try:
        subset_grid = _apply(grid)
    except ValueError as exc:
        # UXarray raises when a circle finds nothing. Reported the same way
        # an empty bounding box is, so the caller is told where the mesh
        # actually is rather than only that the circle was empty -- the
        # raw message says the first and not the second.
        if "No elements found" not in str(exc) and "not enough" not in str(exc).lower():
            raise
        raise ValueError(
            f"Selection kept no faces: {selection} centred at "
            f"({center_lon}, {center_lat})"
            + (f" with radius {radius} degrees" if radius is not None else "")
            + f". The mesh covers {mesh_extent(grid)}. Move the centre inside "
            "that extent, or widen the radius."
        ) from exc

    result_handle = None
    variable_summary = None
    selected = None
    if resolved_data is not None:
        _, uxda, selected = _load_dataarray(resolved_grid, resolved_data, variable_name)
        subset_data = _apply(uxda)
        variable_summary = summarize_array(subset_data.to_xarray())
        result_handle = _persist_dataarray_result(
            data=subset_data,
            session_id=session_id,
            name=result_name or f"{selection}:{selected}",
            kind="subset_advanced",
            summary=variable_summary,
            metadata={
                "selection": selection,
                "center": {"lon": center_lon, "lat": center_lat},
                "radius": radius,
                "k": k,
                "variable_name": selected,
            },
        )
    else:
        result_handle = _persist_grid_result(
            grid=subset_grid,
            session_id=session_id,
            name=result_name or f"{selection}_subset",
            kind="subset_advanced_grid",
            summary=summarize_grid(subset_grid),
        )

    tracker.succeed(f"Selected {subset_grid.n_face} faces.")
    result: dict[str, Any] = {
        "selection": selection,
        "center": {"lon": center_lon, "lat": center_lat},
        "radius_deg": radius,
        "k": k,
        "subset_grid": summarize_grid(subset_grid),
        "variable_name": selected,
        "variable_summary": variable_summary,
        "result_handle": result_handle,
        "subset_coverage": compute_subset_coverage(
            grid.n_face,
            subset_grid.n_face,
            extent=mesh_extent(grid),
            selection_rule=rule,
        ),
    }
    result = attach_provenance(
        result,
        tool="subset_advanced",
        inputs={
            "selection": selection,
            "center_lon": center_lon,
            "center_lat": center_lat,
            "radius": radius,
            "k": k,
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result


def regrid_elements(
    destination: str,
    grid_path: str | None = None,
    data_path: str | None = None,
    variable_name: str | None = None,
    statistic: str = "mean",
    session_id: str | None = None,
    dataset_handle: str | None = None,
    result_name: str | None = None,
) -> dict[str, Any]:
    """Carry a field between nodes, edges and faces.

    Most of this server's operations need face-centred data, and model
    output is frequently node-centred -- vorticity especially. This is the
    step that makes such a field usable, and the repair named when one of
    those operations refuses.

    This changes where the values live, not what they mean: each
    destination element takes the chosen statistic over the source
    elements touching it. ``mean`` is the usual choice; ``min``/``max``
    are for extremes, which averaging would hide.

    Args:
        destination: ``"node"``, ``"edge"`` or ``"face"``.
        grid_path: Mesh file, or ``healpix:<zoom>``.
        data_path: Data file holding the field.
        variable_name: Field to move.
        statistic: One of ``mean``, ``min``, ``max``, ``sum``, ``std``,
            ``var``, ``median``.
        session_id: Session to track this operation under.
        dataset_handle: Registered dataset to use instead of paths.
        result_name: Name for the persisted result.

    Returns:
        The field on its new element, with the source and destination
        dimensions both named so the move is auditable.

    Raises:
        ValueError: Unknown destination or statistic, no data supplied, or
            a field already on the requested element.
    """
    if destination not in ELEMENTS:
        raise ValueError(
            f"Unknown destination {destination!r}; expected one of "
            f"{', '.join(ELEMENTS)}."
        )
    if statistic not in TOPOLOGICAL_STATISTICS:
        raise ValueError(
            f"Unknown statistic {statistic!r}; expected one of "
            f"{', '.join(TOPOLOGICAL_STATISTICS)}."
        )

    tracker = OperationTracker("regrid_elements", session_id=session_id)
    resolved_grid, resolved_data = _resolve_paths(
        session_id=session_id,
        dataset_handle=dataset_handle,
        grid_path=grid_path,
        data_path=data_path,
    )
    if resolved_data is None:
        raise ValueError(
            "regrid_elements moves a field between elements and so needs "
            "data_path (or a dataset_handle that carries one)."
        )

    _, uxda, selected = _load_dataarray(resolved_grid, resolved_data, variable_name)
    source_dims = list(uxda.dims)
    target_dim = f"n_{destination}"
    if target_dim in source_dims:
        raise ValueError(
            f"Variable {selected!r} is already on {destination} elements "
            f"(dims {source_dims}); nothing to move."
        )

    moved = getattr(uxda, f"topological_{statistic}")(destination)
    summary = summarize_array(moved.to_xarray())
    result_handle = _persist_dataarray_result(
        data=moved,
        session_id=session_id,
        name=result_name or f"{selected}_on_{destination}",
        kind="regrid_elements",
        summary=summary,
        metadata={
            "destination": destination,
            "statistic": statistic,
            "variable_name": selected,
            "source_dims": source_dims,
        },
    )
    tracker.succeed(f"Moved {selected!r} onto {destination} elements.")

    result: dict[str, Any] = {
        "variable_name": selected,
        "destination": destination,
        "statistic": statistic,
        "source_dims": source_dims,
        "result_dims": list(moved.dims),
        "variable_summary": summary,
        "result_handle": result_handle,
    }
    result = attach_provenance(
        result,
        tool="regrid_elements",
        inputs={
            "destination": destination,
            "statistic": statistic,
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
        },
    )
    result["_provenance"]["operation_id"] = tracker.operation_id
    return result
