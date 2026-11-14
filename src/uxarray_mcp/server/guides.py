"""Guided multi-step analysis plans, returned as text for the client to follow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def first_look(grid_path: str, data_path: str | None = None, **_: Any) -> str:
    data = f', data_path="{data_path}"' if data_path else ""
    return (
        f"First look at `{grid_path}`"
        + (f" with `{data_path}`" if data_path else "")
        + ".\n\n"
        f'1. `inspect_dataset(grid_path="{grid_path}"{data}, first_look=True)` — '
        "topology, coverage, variables, validation, face areas, a zonal mean "
        "of the first face-centered variable, and mesh/field plots in one call.\n"
        "2. Read `plot_hint` and `size_class` before asking for more plots.\n"
        "3. Summarise: mesh format and size, global or regional, data quality "
        "issues, the selected variable's range, and what to compute next."
    )


def vorticity(
    grid_path: str, data_path: str, u_variable: str, v_variable: str, **_: Any
) -> str:
    args = f'grid_path="{grid_path}", data_path="{data_path}", u_variable="{u_variable}", v_variable="{v_variable}", sphere_radius=6371000'
    return (
        f"Vorticity and divergence of ({u_variable}, {v_variable}) in `{data_path}`.\n\n"
        f'1. `vector_calc(operation="curl", {args})` — relative vorticity in s^-1.\n'
        f'2. `vector_calc(operation="divergence", {args})`.\n'
        "3. If either is refused for missing velocity units or component identity, "
        "check the variables' `units`/`standard_name` with `inspect_dataset` before "
        "overriding.\n"
        '4. Interpret min/max/mean/std; plot one with `plot(kind="field", ...)` '
        "and subset the region of strongest rotation."
    )


def cyclone_structure(
    grid_path: str,
    data_path: str,
    variable_name: str,
    center_lon: float,
    center_lat: float,
    u_variable: str | None = None,
    v_variable: str | None = None,
    outer_radius: float = 10.0,
    **_: Any,
) -> str:
    base = f'grid_path="{grid_path}", data_path="{data_path}"'
    steps = [
        f'1. `compute(statistic="azimuthal_mean", {base}, variable_name="{variable_name}", '
        f"center_lon={center_lon}, center_lat={center_lat}, outer_radius={outer_radius}, "
        "radius_step=0.5)` — radial profile about the centre.",
        f'2. `subset(shape="bbox", {base}, variable_name="{variable_name}", '
        f"lon_bounds=[{center_lon - outer_radius}, {center_lon + outer_radius}], "
        f"lat_bounds=[{center_lat - outer_radius}, {center_lat + outer_radius}])` — "
        'isolate the storm; plot the result_handle with `plot(kind="field")`.',
    ]
    if u_variable and v_variable:
        steps.append(
            f'3. `vector_calc(operation="curl", {base}, u_variable="{u_variable}", '
            f'v_variable="{v_variable}", sphere_radius=6371000)` — confirm the rotational signature.'
        )
    steps.append(
        f"{len(steps) + 1}. Locate the radius of maximum wind / minimum pressure, the "
        "radial extent and any asymmetry."
    )
    return (
        f"Cyclone structure near ({center_lon}, {center_lat}) in `{data_path}`.\n\n"
        + "\n".join(steps)
    )


def eddy_activity(grid_path: str, data_path: str, variable_name: str, **_: Any) -> str:
    base = f'grid_path="{grid_path}", data_path="{data_path}", variable_name="{variable_name}"'
    return (
        f"Eddy / wave activity of `{variable_name}` in `{data_path}`.\n\n"
        f'1. `compute(statistic="zonal_mean", {base})` — latitudinal background state.\n'
        f'2. `compute(statistic="zonal_anomaly", {base})` — departures from each band (the eddy field).\n'
        f'3. `vector_calc(operation="gradient", {base}, sphere_radius=6371000)` — fronts and sharp gradients.\n'
        "4. Read anomaly std/max as eddy strength, note where it concentrates, and "
        'plot the anomaly result_handle with `plot(kind="field")`.'
    )


def model_evaluation(
    grid_path: str, data_path_a: str, data_path_b: str, variable_name: str, **_: Any
) -> str:
    return (
        f"Evaluate `{variable_name}` in `{data_path_a}` against `{data_path_b}`.\n\n"
        f'1. `compare(variable_name="{variable_name}", data_path_a="{data_path_a}", '
        f'data_path_b="{data_path_b}", grid_path="{grid_path}")` — area-weighted bias, '
        "rmse and pattern_correlation in one call.\n"
        "2. If refused for unit disagreement, convert one file; do not override.\n"
        "3. Interpret together: bias = systematic offset, rmse = typical error size, "
        "pattern_correlation = structural agreement (1.0 perfect). Say whether the "
        "error is an offset or a structural mismatch."
    )


def climatology_anomaly(
    data_path: str, variable_name: str, grid_path: str | None = None, **_: Any
) -> str:
    grid = f', grid_path="{grid_path}"' if grid_path else ""
    steps = [
        f'1. `compute(statistic="temporal_mean", data_path="{data_path}", variable_name="{variable_name}")` '
        "— the climatology; check `temporal_coverage` says how many steps were averaged.",
        f'2. `compute(statistic="anomaly", data_path="{data_path}", variable_name="{variable_name}")` '
        "— departures from it.",
        '3. Plot the anomaly result_handle with `plot(kind="field"' + grid + ")`.",
    ]
    if grid_path:
        steps.append(
            f'4. `compute(statistic="zonal_mean", grid_path="{grid_path}", data_path="{data_path}", '
            f'variable_name="{variable_name}")` — summarise by latitude.'
        )
    steps.append(
        f"{len(steps) + 1}. Say where and when the field departs most from its climatology."
    )
    return (
        f"Climatology and anomalies of `{variable_name}` in `{data_path}`.\n\n"
        + "\n".join(steps)
    )


def hpc_diagnose(endpoint: str | None = None, **_: Any) -> str:
    ep = f', endpoint="{endpoint}"' if endpoint else ""
    return (
        "Diagnose the Globus Compute setup.\n\n"
        f'1. `endpoint(action="status"{ep})` — manager state of every configured endpoint '
        "and a worker probe (node, Python, uxarray, server versions, round trip).\n"
        f'2. `endpoint(action="validate"{ep}, path="<a file on the cluster>")` — header read on the worker.\n'
        f'3. `endpoint(action="check_yac"{ep})` if conservative remapping is needed.\n'
        "4. Turn failures into actions: `offline` → start the endpoint; `NO_WORKER` → wait for "
        "the scheduler; `WORKER_MISSING_PACKAGE` → `pip install --no-deps uxarray-mcp` in the "
        "worker env and restart; version drift → update the worker env."
    )


GUIDES: dict[str, Callable[..., str]] = {
    "first_look": first_look,
    "vorticity": vorticity,
    "cyclone_structure": cyclone_structure,
    "eddy_activity": eddy_activity,
    "model_evaluation": model_evaluation,
    "climatology_anomaly": climatology_anomaly,
    "hpc_diagnose": hpc_diagnose,
}
