"""Shared styling helpers for paper figure generation."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

BLUE = "#2166ac"
ORANGE = "#d6604d"
GREY = "#878787"
DARK = "#1f2933"
MUTED = "#5f6b76"
GRID = "#e0e0e0"
LIGHT = "#f7f9fb"

FIGURE_DIR = Path("outputs/figures")
DATA_DIR = FIGURE_DIR / "data"


def configure_matplotlib() -> None:
    """Use one publication style across generated figures."""
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#c8d0d9",
            "axes.linewidth": 0.8,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def ensure_output_dirs() -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def save_figure(fig: plt.Figure, stem: str) -> None:
    """Save both vector and high-resolution raster versions."""
    ensure_output_dirs()
    fig.savefig(FIGURE_DIR / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(FIGURE_DIR / f"{stem}.png", bbox_inches="tight", dpi=300)
