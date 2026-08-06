"""Case definitions for the heavy multi-operation benchmark.

Each case is a named callable taking a ``Ctx`` and returning the raw tool
result.  Cases are deliberately written against the *public* tool surface
(``uxarray_mcp.tools``) rather than the domain layer so that dispatch,
provenance, and remote routing are all exercised.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Ctx:
    """Inputs shared by every case in one benchmark run."""

    grid_path: str
    data_path: str
    variable: str = "temperature"
    endpoint: str | None = None
    #: Extra kwargs for tools that accept ``use_remote``/``endpoint``.
    remote_kwargs: dict = field(default_factory=dict)

    @property
    def is_remote(self) -> bool:
        return bool(self.remote_kwargs.get("use_remote"))


def _unwrap_plot(items: Any) -> dict:
    """Normalize a plot tool's ``[ImageContent, TextContent]`` into a dict."""
    if isinstance(items, list) and len(items) == 2:
        meta = json.loads(items[1].text)
        meta["png_b64_len"] = len(items[0].data)
        return meta
    return items


def case_inspect_mesh(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import inspect_mesh

    return inspect_mesh(ctx.grid_path, **ctx.remote_kwargs)


def case_calculate_area(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import calculate_area

    return calculate_area(ctx.grid_path, **ctx.remote_kwargs)


def case_inspect_variable(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import inspect_variable

    return inspect_variable(
        ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs
    )


def case_validate_dataset(ctx: Ctx) -> dict:
    from uxarray_mcp.tools.remote_tools import validate_dataset

    return validate_dataset(ctx.grid_path, ctx.data_path, **ctx.remote_kwargs)


def case_zonal_mean_default(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import calculate_zonal_mean

    return calculate_zonal_mean(
        ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs
    )


def case_zonal_mean_edges(ctx: Ctx) -> dict:
    """Explicit band edges — the array form of ``lat_spec``."""
    from uxarray_mcp.tools import calculate_zonal_mean

    return calculate_zonal_mean(
        ctx.grid_path,
        ctx.data_path,
        ctx.variable,
        lat_spec=[-60.0, -30.0, 0.0, 30.0, 60.0],
        **ctx.remote_kwargs,
    )


def case_zonal_mean_conservative(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import calculate_zonal_mean

    return calculate_zonal_mean(
        ctx.grid_path,
        ctx.data_path,
        ctx.variable,
        lat_spec=[-90.0, -45.0, 0.0, 45.0, 90.0],
        conservative=True,
        **ctx.remote_kwargs,
    )


def case_zonal_anomaly(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import calculate_zonal_anomaly

    return calculate_zonal_anomaly(
        ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs
    )


def case_plot_zonal_mean(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import plot_zonal_mean

    return _unwrap_plot(
        plot_zonal_mean(ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs)
    )


def case_plot_variable(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import plot_variable

    return _unwrap_plot(
        plot_variable(ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs)
    )


def case_subset_bbox(ctx: Ctx) -> dict:
    """Tropical band subset.  Always local today — see ``run_analysis``."""
    from uxarray_mcp.tools import subset_bbox

    return subset_bbox(
        [-60.0, 60.0],
        [-30.0, 30.0],
        grid_path=ctx.grid_path,
        data_path=ctx.data_path,
        variable_name=ctx.variable,
    )


def case_subset_polygon(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import subset_polygon

    return subset_polygon(
        [[-40.0, -20.0], [40.0, -20.0], [40.0, 20.0], [-40.0, 20.0]],
        grid_path=ctx.grid_path,
        data_path=ctx.data_path,
        variable_name=ctx.variable,
    )


def case_azimuthal_mean(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import calculate_azimuthal_mean

    return calculate_azimuthal_mean(
        ctx.grid_path,
        ctx.data_path,
        ctx.variable,
        center_lon=0.0,
        center_lat=0.0,
        outer_radius=30.0,
        radius_step=2.0,
        **ctx.remote_kwargs,
    )


def case_gradient(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import calculate_gradient

    return calculate_gradient(
        ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs
    )


def case_get_capabilities(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import get_capabilities

    return get_capabilities(ctx.grid_path, ctx.data_path, **ctx.remote_kwargs)


#: Ordered so cheap structural checks fail fast before expensive compute.
PIPELINE: list[tuple[str, Callable[[Ctx], Any]]] = [
    ("inspect_mesh", case_inspect_mesh),
    ("get_capabilities", case_get_capabilities),
    ("calculate_area", case_calculate_area),
    ("inspect_variable", case_inspect_variable),
    ("validate_dataset", case_validate_dataset),
    ("zonal_mean_default", case_zonal_mean_default),
    ("zonal_mean_edges", case_zonal_mean_edges),
    ("zonal_mean_conservative", case_zonal_mean_conservative),
    ("zonal_anomaly", case_zonal_anomaly),
    ("azimuthal_mean", case_azimuthal_mean),
    ("gradient", case_gradient),
    ("subset_bbox", case_subset_bbox),
    ("subset_polygon", case_subset_polygon),
    ("plot_zonal_mean", case_plot_zonal_mean),
    ("plot_variable", case_plot_variable),
]
