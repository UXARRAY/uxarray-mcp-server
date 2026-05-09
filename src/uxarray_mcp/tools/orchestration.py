"""Deterministic one-shot orchestration tools.

These tools run a fixed pipeline of inspection, validation, and analysis
calls in sequence and return a single structured result. They are the
"do everything reasonable" counterpart to ``run_scientific_agent``: no
LLM reasoning, no branching heuristics — just a predictable chain that
turns a single user invocation into a full first look at a dataset.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional

from uxarray_mcp.provenance import attach_provenance


def _safe_call(stage: str, fn, warnings: list[str]) -> Optional[Any]:
    """Run ``fn``; on failure append a warning and return None."""
    try:
        return fn()
    except Exception as exc:
        warnings.append(f"{stage}: {type(exc).__name__}: {exc}")
        return None


def _png_meta(items: list[Any]) -> dict[str, Any]:
    """Convert a plot tool's ``[ImageContent, TextContent]`` list to a dict."""
    if not items or len(items) < 2:
        return {}
    img = items[0]
    try:
        meta = json.loads(items[1].text)
    except Exception:
        meta = {}
    png_b64 = getattr(img, "data", None)
    image_size_bytes = meta.get("image_size_bytes")
    if image_size_bytes is None and png_b64:
        try:
            image_size_bytes = len(base64.b64decode(png_b64))
        except Exception:
            image_size_bytes = None
    return {
        "png_b64": png_b64,
        "image_size_bytes": image_size_bytes,
        "grid_info": meta.get("grid_info"),
        "variable_name": meta.get("variable_name"),
    }


def analyze_dataset(
    grid_path: Optional[str] = None,
    data_path: Optional[str] = None,
    variable_name: Optional[str] = None,
    session_id: Optional[str] = None,
    dataset_handle: Optional[str] = None,
    use_remote: bool = False,
    endpoint: Optional[str] = None,
    include_plots: bool = True,
) -> dict[str, Any]:
    """Run a complete first-look analysis of a mesh dataset in one call.

    Executes a fixed deterministic pipeline:

    1. ``inspect_mesh`` — topology summary
    2. ``validate_dataset`` — NaN/Inf/fill checks (only if ``data_path``)
    3. ``inspect_variable`` — variable metadata (only if ``data_path``)
    4. ``calculate_area`` — face area statistics
    5. ``calculate_zonal_mean`` — zonal profile of the first face-centered
       variable (only if ``data_path`` and a face-centered variable exists)
    6. ``plot_mesh`` — wireframe PNG (only if ``include_plots``)
    7. ``plot_variable`` — choropleth PNG of the chosen variable (only if
       ``include_plots`` and a face-centered variable exists)

    Each stage is run defensively — a failure in any single stage is
    recorded in ``warnings`` and the pipeline continues.

    Parameters
    ----------
    grid_path : str | None
        Path to the mesh grid file or ``healpix:<zoom>``. Optional when
        ``session_id`` and ``dataset_handle`` are provided.
    data_path : str | None
        Path to a data file with variables. If omitted, only mesh-level
        stages run.
    variable_name : str | None
        Specific face-centered variable to analyze. If omitted, the first
        face-centered variable discovered by ``inspect_variable`` is used.
    session_id, dataset_handle : str | None
        When both are provided, the grid/data paths are resolved from the
        registered session dataset.
    use_remote : bool
        Forwarded to each underlying ``*_hpc`` dispatcher.
    endpoint : str | None
        Forwarded to each underlying ``*_hpc`` dispatcher.
    include_plots : bool
        When False, the two plot stages are skipped (useful for headless
        callers that just want statistics).

    Returns
    -------
    dict
        A structured result with keys:

        - ``grid_path``, ``data_path``: resolved input paths
        - ``mesh``: ``inspect_mesh`` result (or ``None`` on failure)
        - ``validation``: ``validate_dataset`` result (or ``None``)
        - ``variables``: ``inspect_variable`` result (or ``None``)
        - ``area``: ``calculate_area`` result (or ``None``)
        - ``selected_variable``: name of the face-centered variable used
        - ``zonal_mean``: ``calculate_zonal_mean`` result (or ``None``)
        - ``mesh_plot``: PNG metadata dict (or ``None``)
        - ``variable_plot``: PNG metadata dict (or ``None``)
        - ``stages_run``: list of stage names that completed successfully
        - ``warnings``: list of stage failures (empty when everything ran)
        - ``recommended_next_steps``: chained-tool suggestions for the
          agent to act on after seeing this result
        - ``_provenance``: standard provenance block
    """
    from .inspection import inspect_mesh
    from .plotting import _resolve_plot_paths
    from .remote_tools import (
        calculate_area_hpc,
        calculate_zonal_mean_hpc,
        inspect_mesh_hpc,
        inspect_variable_hpc,
        plot_mesh_hpc,
        plot_variable_hpc,
    )

    resolved_grid, resolved_data = _resolve_plot_paths(
        grid_path, data_path, session_id, dataset_handle
    )

    warnings: list[str] = []
    stages_run: list[str] = []

    # ── Stage 1: inspect mesh ────────────────────────────────────────────────
    mesh = _safe_call(
        "inspect_mesh",
        lambda: inspect_mesh_hpc(
            resolved_grid,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        ),
        warnings,
    )
    if mesh is not None:
        stages_run.append("inspect_mesh")

    # ── Stage 2 + 3: validate + inspect variables (data path required) ──────
    validation: Optional[dict[str, Any]] = None
    variables: Optional[dict[str, Any]] = None
    selected_variable: Optional[str] = variable_name

    if resolved_data is not None:
        # validate_dataset is local-only by design (data is read directly);
        # if the dispatcher were ever added, prefer that. For now use the
        # local variant via inspection.validate_dataset.
        from .inspection import validate_dataset as _validate_dataset

        validation = _safe_call(
            "validate_dataset",
            lambda: _validate_dataset(resolved_grid, resolved_data),
            warnings,
        )
        if validation is not None:
            stages_run.append("validate_dataset")

        variables = _safe_call(
            "inspect_variable",
            lambda: inspect_variable_hpc(
                resolved_grid,
                resolved_data,
                variable_name,
                use_remote=use_remote,
                endpoint=endpoint,
                session_id=session_id,
            ),
            warnings,
        )
        if variables is not None:
            stages_run.append("inspect_variable")
            if selected_variable is None:
                for var in variables.get("variables", []):
                    if var.get("location") == "faces":
                        selected_variable = var.get("name")
                        break

    # ── Stage 4: face areas ──────────────────────────────────────────────────
    area = _safe_call(
        "calculate_area",
        lambda: calculate_area_hpc(
            resolved_grid,
            use_remote=use_remote,
            endpoint=endpoint,
            session_id=session_id,
        ),
        warnings,
    )
    if area is not None:
        stages_run.append("calculate_area")

    # ── Stage 5: zonal mean (needs data + face-centered variable) ───────────
    zonal_mean: Optional[dict[str, Any]] = None
    if resolved_data is not None and selected_variable is not None:
        zonal_mean = _safe_call(
            "calculate_zonal_mean",
            lambda: calculate_zonal_mean_hpc(
                resolved_grid,
                resolved_data,
                selected_variable,
                use_remote=use_remote,
                endpoint=endpoint,
                session_id=session_id,
            ),
            warnings,
        )
        if zonal_mean is not None:
            stages_run.append("calculate_zonal_mean")

    # ── Stage 6 + 7: plots (optional) ────────────────────────────────────────
    mesh_plot: Optional[dict[str, Any]] = None
    variable_plot: Optional[dict[str, Any]] = None

    if include_plots:
        plot_items = _safe_call(
            "plot_mesh",
            lambda: plot_mesh_hpc(
                grid_path=resolved_grid,
                use_remote=use_remote,
                endpoint=endpoint,
                session_id=session_id,
            ),
            warnings,
        )
        if plot_items is not None:
            mesh_plot = _png_meta(plot_items)
            stages_run.append("plot_mesh")

        if resolved_data is not None and selected_variable is not None:
            var_plot_items = _safe_call(
                "plot_variable",
                lambda: plot_variable_hpc(
                    grid_path=resolved_grid,
                    data_path=resolved_data,
                    variable_name=selected_variable,
                    use_remote=use_remote,
                    endpoint=endpoint,
                    session_id=session_id,
                ),
                warnings,
            )
            if var_plot_items is not None:
                variable_plot = _png_meta(var_plot_items)
                stages_run.append("plot_variable")

    # ── Recommended next steps ──────────────────────────────────────────────
    next_steps: list[str] = []
    if resolved_data is None:
        next_steps.append(
            f'inspect_variable("{resolved_grid}", "<data_path>") '
            "— rerun with a data file to unlock variable analysis"
        )
    if validation is not None and validation.get("passed") is False:
        next_steps.append(
            "Validation failed; review the per-variable warnings before "
            "trusting downstream results."
        )
    if selected_variable and resolved_data is not None:
        next_steps.append(
            f'plot_zonal_mean("{resolved_grid}", "{resolved_data}", '
            f'"{selected_variable}") — render the zonal profile'
        )
        next_steps.append(
            f'extract_cross_section(latitude=0.0, grid_path="{resolved_grid}", '
            f'data_path="{resolved_data}", variable_name="{selected_variable}")'
        )
        next_steps.append(
            f'subset_bbox(lon_bounds=[-180, 180], lat_bounds=[-90, 90], '
            f'grid_path="{resolved_grid}", data_path="{resolved_data}", '
            f'variable_name="{selected_variable}") — focus on a region'
        )
    if not next_steps:
        next_steps.append(
            f'plot_mesh(grid_path="{resolved_grid}") — visualize the mesh wireframe'
        )

    result: dict[str, Any] = {
        "grid_path": resolved_grid,
        "data_path": resolved_data,
        "mesh": mesh,
        "validation": validation,
        "variables": variables,
        "area": area,
        "selected_variable": selected_variable,
        "zonal_mean": zonal_mean,
        "mesh_plot": mesh_plot,
        "variable_plot": variable_plot,
        "stages_run": stages_run,
        "warnings": warnings,
        "recommended_next_steps": next_steps,
    }

    # Ensure inspect_mesh is callable for the local-only smoke fallback path
    # (used by tests that import `inspect_mesh` directly from this module).
    _ = inspect_mesh  # keep import alive

    venue = "hpc" if use_remote else "local"
    return attach_provenance(
        result,
        tool="analyze_dataset",
        inputs={
            "grid_path": grid_path,
            "data_path": data_path,
            "variable_name": variable_name,
            "session_id": session_id,
            "dataset_handle": dataset_handle,
            "use_remote": use_remote,
            "endpoint": endpoint,
            "include_plots": include_plots,
        },
        venue=venue,
        warnings=warnings,
        selected_variable=selected_variable,
    )
