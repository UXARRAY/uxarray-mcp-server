"""Shared plotting logic for UXarray MCP Server.

Pure rendering functions that take loaded UXarray objects and return
PNG bytes. No MCP, provenance, or file-loading logic belongs here.
"""

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

    import io

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


def render_variable(
    uxda: Any,
    width: int = 800,
    height: int = 400,
    cmap: str = "viridis",
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
        Matplotlib colormap name.

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

    element = uxda.plot.polygons(backend="matplotlib", cmap=cmap)

    renderer = hv.Store.renderers["matplotlib"]
    plot = renderer.get_plot(element)
    fig = plot.state
    fig.set_size_inches(fig_w, fig_h)
    fig.set_dpi(dpi)
    fig.tight_layout()

    import io

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

    Returns
    -------
    bytes
        PNG image data.
    """
    dpi = 100
    fig_w = width / dpi
    fig_h = height / dpi

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    ax.plot(latitudes, values, linewidth=1.5, color="#1f77b4")
    ax.set_xlabel("Latitude (°)")
    ax.set_ylabel(variable_name)
    ax.set_title(f"Zonal Mean — {variable_name}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    import io

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
