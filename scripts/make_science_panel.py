"""Generate paper Figure 2: UXarray MCP scientific output panel."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import uxarray as ux
import xarray as xr
from figure_style import (
    BLUE,
    DARK,
    DATA_DIR,
    GRID,
    MUTED,
    configure_matplotlib,
    ensure_output_dirs,
    save_figure,
)
from matplotlib.collections import PolyCollection

from uxarray_mcp.tools.frontdoor import run_analysis


def _variable_resolution_axis(
    start: float, stop: float, focus: tuple[float, float], coarse: float, fine: float
) -> np.ndarray:
    values: list[float] = []
    x = start
    while x < stop:
        step = fine if focus[0] <= x <= focus[1] else coarse
        values.append(round(x, 6))
        x += step
    return np.array(values, dtype=float)


def _write_demo_dataset() -> tuple[Path, Path]:
    ensure_output_dirs()
    grid_path = DATA_DIR / "paper_demo_grid.nc"
    data_path = DATA_DIR / "paper_demo_data.nc"

    lon = _variable_resolution_axis(-180, 180, (-102, -78), coarse=6.0, fine=1.5)
    lat = _variable_resolution_axis(-88, 89, (16, 34), coarse=4.0, fine=1.0)
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    grid.to_xarray().to_netcdf(grid_path)

    flon = np.asarray(grid.face_lon)
    flat = np.asarray(grid.face_lat)
    gulf = np.exp(-(((flon + 90) / 12) ** 2 + ((flat - 25) / 7) ** 2))
    wave = 4.5 * np.cos(np.radians(3 * flon)) * np.cos(np.radians(flat))
    temperature = 300 - 42 * np.sin(np.radians(flat)) ** 2 + wave + 7.5 * gulf
    u_wind = 22 * np.cos(np.radians(flat)) + 6 * np.sin(np.radians(2 * flon)) + 4 * gulf
    v_wind = 9 * np.sin(np.radians(2 * flat)) * np.cos(np.radians(flon)) - 3 * gulf

    xr.Dataset(
        {
            "temperature": (
                ["n_face"],
                temperature,
                {"units": "K", "long_name": "synthetic air temperature"},
            ),
            "u": (["n_face"], u_wind, {"units": "m s-1", "long_name": "zonal wind"}),
            "v": (
                ["n_face"],
                v_wind,
                {"units": "m s-1", "long_name": "meridional wind"},
            ),
        }
    ).to_netcdf(data_path)
    return grid_path, data_path


def _polygons(grid: ux.Grid) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
    ds = grid.to_xarray()
    node_lon = np.asarray(ds["node_lon"].values)
    node_lat = np.asarray(ds["node_lat"].values)
    conn = np.asarray(ds["face_node_connectivity"].values)

    polys: list[np.ndarray] = []
    kept: list[int] = []
    for face_idx, nodes in enumerate(conn):
        valid = nodes[nodes >= 0].astype(int)
        if valid.size < 3:
            continue
        lon = ((node_lon[valid] + 180) % 360) - 180
        lat = node_lat[valid]
        if np.ptp(lon) > 120:
            continue
        polys.append(np.column_stack([lon, lat]))
        kept.append(face_idx)
    return polys, np.asarray(kept, dtype=int), np.asarray(grid.face_lon)


def _style_map_axis(
    ax: plt.Axes,
    title: str,
    xlim: tuple[float, float] = (-101, -79),
    ylim: tuple[float, float] = (17, 33),
) -> None:
    ax.set_title(title, loc="left", color=DARK, weight="bold", pad=6)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(color=GRID, linewidth=0.5, alpha=0.75)
    for spine in ax.spines.values():
        spine.set_color("#c8d0d9")


def _add_panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        0.02,
        0.98,
        label,
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        weight="bold",
        color=DARK,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 2.5},
    )


def _add_collection(
    ax: plt.Axes,
    polygons: list[np.ndarray],
    values: np.ndarray | None = None,
    *,
    cmap: str = "viridis",
    edgecolor: str = "#334155",
    linewidth: float = 0.18,
    alpha: float = 1.0,
) -> PolyCollection:
    collection = PolyCollection(
        polygons, edgecolors=edgecolor, linewidths=linewidth, alpha=alpha
    )
    if values is None:
        collection.set_facecolor("#e7eef6")
    else:
        collection.set_array(values)
        collection.set_cmap(cmap)
    ax.add_collection(collection)
    return collection


def main() -> None:
    configure_matplotlib()
    grid_path, data_path = _write_demo_dataset()

    # Route through MCP front door so outputs exercise the same public dispatcher.
    curl_stats = run_analysis(
        operation="curl",
        grid_path=str(grid_path),
        data_path=str(data_path),
        u_variable="u",
        v_variable="v",
    )
    zonal_stats = run_analysis(
        operation="calculate_zonal_mean",
        grid_path=str(grid_path),
        data_path=str(data_path),
        variable_name="temperature",
    )

    uxds = ux.open_dataset(grid_path, data_path)
    grid = uxds.uxgrid
    polygons, kept, _ = _polygons(grid)
    temperature = np.asarray(uxds["temperature"].values)[kept]
    vorticity = np.asarray(uxds["u"].curl(uxds["v"], scale_by_radius=False).values)[
        kept
    ]

    fig = plt.figure(figsize=(8.2, 6.8))
    gs = fig.add_gridspec(2, 2, hspace=0.30, wspace=0.48)
    ax_mesh = fig.add_subplot(gs[0, 0])
    ax_temp = fig.add_subplot(gs[0, 1])
    ax_vort = fig.add_subplot(gs[1, 0])
    ax_zonal = fig.add_subplot(gs[1, 1])

    _style_map_axis(
        ax_mesh, "Variable-resolution mesh", xlim=(-150, -30), ylim=(-8, 58)
    )
    _add_collection(
        ax_mesh, polygons, None, edgecolor="#27384a", linewidth=0.12, alpha=0.95
    )
    ax_mesh.text(-146, -4, f"{grid.n_face:,} faces", color=MUTED, fontsize=9)
    _add_panel_label(ax_mesh, "(a)")

    _style_map_axis(ax_temp, "Temperature field")
    temp_collection = _add_collection(
        ax_temp, polygons, temperature, cmap="viridis", edgecolor="none", linewidth=0.0
    )
    cbar = fig.colorbar(temp_collection, ax=ax_temp, fraction=0.046, pad=0.02)
    cbar.set_label("K")
    _add_panel_label(ax_temp, "(b)")

    _style_map_axis(ax_vort, "Relative vorticity")
    lim = float(np.nanpercentile(np.abs(vorticity), 98))
    vort_collection = _add_collection(
        ax_vort, polygons, vorticity, cmap="RdBu_r", edgecolor="none", linewidth=0.0
    )
    vort_collection.set_clim(-lim, lim)
    cbar = fig.colorbar(vort_collection, ax=ax_vort, fraction=0.046, pad=0.02)
    cbar.set_label("1/rad")
    _add_panel_label(ax_vort, "(c)")

    latitudes = np.asarray(zonal_stats["latitudes"], dtype=float)
    zonal = np.asarray(zonal_stats["zonal_mean_values"], dtype=float)
    ax_zonal.plot(zonal, latitudes, color=BLUE, linewidth=2.2)
    ax_zonal.fill_betweenx(
        latitudes, zonal, np.nanmin(zonal) - 1, color=BLUE, alpha=0.08
    )
    ax_zonal.set_title(
        "Zonal mean profile", loc="left", color=DARK, weight="bold", pad=6
    )
    ax_zonal.set_xlabel("temperature (K)")
    ax_zonal.set_ylabel("latitude")
    ax_zonal.set_ylim(-90, 90)
    ax_zonal.grid(color=GRID, linewidth=0.6)
    ax_zonal.text(
        0.03,
        0.06,
        "computed via run_analysis\noperation='calculate_zonal_mean'",
        transform=ax_zonal.transAxes,
        color=MUTED,
        fontsize=8.2,
    )
    _add_panel_label(ax_zonal, "(d)")

    curl_min = curl_stats["stats"]["min"]
    curl_max = curl_stats["stats"]["max"]
    fig.text(
        0.02,
        0.01,
        f"Deterministic UGRID demo data; MCP dispatcher computed curl stats ({curl_min:.1f} to {curl_max:.1f}) and zonal mean.",
        color=MUTED,
        fontsize=8.5,
    )

    save_figure(fig, "fig2_science_panel")
    plt.close(fig)


if __name__ == "__main__":
    main()
