"""Shared plotting logic for UXarray MCP Server.

Pure rendering functions that take loaded UXarray objects and return
PNG bytes. No MCP, provenance, or file-loading logic belongs here.
"""

import io
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render_mesh(
    grid: Any,
    width: int = 800,
    height: int = 400,
) -> bytes:
    """Render a mesh wireframe to PNG bytes.

    Parameters
    ----------
    grid : ux.Grid
        Loaded UXarray grid.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.

    Returns
    -------
    bytes
        PNG image data.
    """
    import holoviews as hv

    hv.extension("matplotlib")

    dpi = 100
    fig_w = width / dpi
    fig_h = height / dpi

    element = grid.plot.mesh(backend="matplotlib")

    renderer = hv.Store.renderers["matplotlib"]
    plot = renderer.get_plot(element)
    fig = plot.state
    fig.set_size_inches(fig_w, fig_h)
    fig.set_dpi(dpi)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError(
            "Rendered mesh plot is empty. The file may be empty or contain no "
            "plottable geometry."
        )
    return png_bytes


_FACE_DIMS = {"n_face", "nCells"}


def _reduce_to_face(uxda: Any, time_index: int = 0) -> Any:
    """Squeeze or isel any non-face extra dims so uxda is 1-D face-centered."""
    extra = [d for d in uxda.dims if d not in _FACE_DIMS]
    if not extra:
        return uxda
    return uxda.isel(**{d: 0 if uxda.sizes[d] == 1 else time_index for d in extra})


def render_variable(
    uxda: Any,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
    title: str | None = None,
    time_index: int = 0,
) -> bytes:
    """Render a face-centered variable as a filled polygon plot to PNG bytes.

    Parameters
    ----------
    uxda : ux.UxDataArray
        Face-centered UXarray data array.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    cmap : str
        Matplotlib colormap name (e.g. "viridis", "plasma", "RdBu_r", "coolwarm").
    vmin : float | None
        Minimum value for the colormap. Defaults to data minimum.
    vmax : float | None
        Maximum value for the colormap. Defaults to data maximum.
    title : str | None
        Plot title. Defaults to the variable name.

    Returns
    -------
    bytes
        PNG image data.
    """
    import holoviews as hv

    hv.extension("matplotlib")

    dpi = 100
    fig_w = width / dpi
    fig_h = height / dpi

    kwargs: dict[str, Any] = {"backend": "matplotlib", "cmap": cmap}
    if vmin is not None:
        kwargs["clim"] = (vmin, vmax if vmax is not None else uxda.values.max())
    elif vmax is not None:
        kwargs["clim"] = (uxda.values.min(), vmax)

    uxda = _reduce_to_face(uxda, time_index)
    element = uxda.plot.polygons(**kwargs)

    renderer = hv.Store.renderers["matplotlib"]
    plot = renderer.get_plot(element)
    fig = plot.state
    fig.set_size_inches(fig_w, fig_h)
    fig.set_dpi(dpi)

    if title is not None:
        fig.axes[0].set_title(title)

    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError(
            "Rendered variable plot is empty. The file may be empty or contain "
            "no plottable data."
        )
    return png_bytes


def render_zonal_mean(
    latitudes: list[float],
    values: list[float],
    variable_name: str,
    width: int = 800,
    height: int = 400,
    line_color: str = "#1f77b4",
    title: str | None = None,
) -> bytes:
    """Render a zonal mean profile (latitude vs value) to PNG bytes.

    Parameters
    ----------
    latitudes : list[float]
        Latitude values.
    values : list[float]
        Zonal mean values at each latitude.
    variable_name : str
        Variable name for the axis label.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.
    line_color : str
        Matplotlib color string for the profile line (e.g. "red", "#e74c3c",
        "steelblue"). Defaults to "#1f77b4" (matplotlib blue).
    title : str | None
        Plot title. Defaults to "Zonal Mean — <variable_name>".

    Returns
    -------
    bytes
        PNG image data.
    """
    dpi = 100
    fig_w = width / dpi
    fig_h = height / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    ax.plot(latitudes, values, linewidth=1.5, color=line_color)
    ax.set_xlabel("Latitude (°)")
    ax.set_ylabel(variable_name)
    ax.set_title(title if title is not None else f"Zonal Mean — {variable_name}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()
    if not png_bytes:
        raise ValueError(
            "Rendered zonal mean plot is empty. The data may be empty or contain "
            "no plottable values."
        )
    return png_bytes
