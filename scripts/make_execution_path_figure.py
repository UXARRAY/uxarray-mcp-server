"""Generate paper Figure 1: local and HPC execution paths."""

from __future__ import annotations

import matplotlib.pyplot as plt
from figure_style import (
    BLUE,
    DARK,
    GREY,
    LIGHT,
    MUTED,
    ORANGE,
    configure_matplotlib,
    save_figure,
)
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


def _box(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    *,
    edge: str,
    face: str = "white",
    text_color: str = DARK,
) -> None:
    patch = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.018,rounding_size=0.045",
        linewidth=1.25,
        edgecolor=edge,
        facecolor=face,
    )
    ax.add_patch(patch)
    ax.text(
        x + width / 2,
        y + height / 2,
        label,
        ha="center",
        va="center",
        color=text_color,
        fontsize=10.5,
        linespacing=1.15,
    )


def _arrow(
    ax: plt.Axes, start: tuple[float, float], end: tuple[float, float], color: str
) -> None:
    arrow = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=12,
        linewidth=1.25,
        color=color,
        shrinkA=6,
        shrinkB=6,
    )
    ax.add_patch(arrow)


def main() -> None:
    configure_matplotlib()

    fig, ax = plt.subplots(figsize=(11.0, 3.5))
    ax.set_xlim(0, 13.6)
    ax.set_ylim(0, 4.0)
    ax.axis("off")

    panel = FancyBboxPatch(
        (0.15, 0.2),
        13.3,
        3.55,
        boxstyle="round,pad=0.03,rounding_size=0.08",
        linewidth=0.9,
        edgecolor="#d7dee7",
        facecolor="white",
    )
    ax.add_patch(panel)

    ax.text(
        0.35,
        3.48,
        "Same request, same result — execution venue changes",
        color=DARK,
        fontsize=13,
        weight="bold",
    )
    ax.text(
        0.35,
        3.18,
        "UXarray MCP routes analysis locally by default or to HPC via Globus Compute when data lives on a cluster.",
        color=MUTED,
        fontsize=9.8,
    )

    rows = [
        {
            "label": "Local path",
            "y": 2.18,
            "color": GREY,
            "boxes": [
                ("Researcher\nprompt", GREY, LIGHT),
                ("AI client\n(MCP host)", GREY, LIGHT),
                ("uxarray-mcp\nfront door", BLUE, "#eef5fb"),
                ("UXarray\nlocal Python", GREY, LIGHT),
                ("Result +\nprovenance", BLUE, "#eef5fb"),
            ],
        },
        {
            "label": "HPC path",
            "y": 0.95,
            "color": ORANGE,
            "boxes": [
                ("Researcher\nprompt", GREY, LIGHT),
                ("AI client\n(MCP host)", GREY, LIGHT),
                ("uxarray-mcp\nfront door", BLUE, "#eef5fb"),
                ("Globus Compute\nsubmit", ORANGE, "#fff3ec"),
                ("HPC worker\nUXarray", ORANGE, "#fff3ec"),
                ("Result +\nprovenance", BLUE, "#eef5fb"),
            ],
        },
    ]

    box_w = 1.55
    box_h = 0.58
    x0 = 1.75
    gap = 0.45

    for row in rows:
        y = row["y"]
        ax.text(
            0.95,
            y + box_h / 2,
            row["label"],
            ha="center",
            va="center",
            color=row["color"],
            fontsize=10.5,
            weight="bold",
        )
        for idx, (label, edge, face) in enumerate(row["boxes"]):
            x = x0 + idx * (box_w + gap)
            if row["label"] == "Local path" and idx == 4:
                x = x0 + 5 * (box_w + gap)
            _box(ax, x, y, box_w, box_h, label, edge=edge, face=face)

            if idx < len(row["boxes"]) - 1:
                next_x = x0 + (idx + 1) * (box_w + gap)
                if row["label"] == "Local path" and idx == 3:
                    next_x = x0 + 5 * (box_w + gap)
                _arrow(
                    ax,
                    (x + box_w, y + box_h / 2),
                    (next_x, y + box_h / 2),
                    row["color"],
                )

    local_arrow_start = x0 + 3 * (box_w + gap) + box_w
    local_arrow_end = x0 + 5 * (box_w + gap)
    local_arrow_mid = (local_arrow_start + local_arrow_end) / 2
    ax.text(
        local_arrow_mid,
        2.98,
        "no cluster dependency",
        color=MUTED,
        fontsize=8.8,
        ha="center",
        style="italic",
    )
    ax.text(
        9.0,
        0.5,
        "data stays on cluster; JSON summary and artifacts return",
        color=MUTED,
        fontsize=8.8,
        ha="center",
        style="italic",
    )

    save_figure(fig, "fig1_execution_path")
    plt.close(fig)


if __name__ == "__main__":
    main()
