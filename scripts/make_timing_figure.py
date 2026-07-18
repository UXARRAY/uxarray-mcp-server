"""Generate paper Figure 3: remote execution timing summary."""

from __future__ import annotations

import json

import matplotlib.pyplot as plt
import numpy as np
from figure_style import (
    BLUE,
    DARK,
    GREY,
    MUTED,
    ORANGE,
    configure_matplotlib,
    ensure_output_dirs,
    save_figure,
)

TIMINGS = [
    # operation, first measured call, warm/cached worker call, note
    ("inspect mesh", 37.6, 1.2, "MPAS QU 480 km"),
    ("face area", 11.0, 1.0, "MPAS QU 480 km"),
    ("gradient", 11.4, 1.8, "DYAMOND subset"),
    ("curl", 11.1, 1.8, "DYAMOND subset"),
    ("divergence", 10.9, 1.8, "DYAMOND subset"),
    ("zonal mean", 1.0, 1.0, "MPAS QU 480 km"),
]
COLD_START_RANGE = (180.0, 240.0)


def main() -> None:
    configure_matplotlib()
    ensure_output_dirs()

    labels = [f"{row[0]}\n{row[3]}" for row in TIMINGS]
    first = np.array([row[1] for row in TIMINGS])
    warm = np.array([row[2] for row in TIMINGS])
    y = np.arange(len(TIMINGS))
    height = 0.36

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    ax.barh(y + height / 2, first, height, color=GREY, label="first measured call")
    ax.barh(y - height / 2, warm, height, color=BLUE, label="warm worker")

    ax.axvspan(
        COLD_START_RANGE[0],
        COLD_START_RANGE[1],
        color=ORANGE,
        alpha=0.16,
        label="scheduler cold start",
    )
    ax.text(
        np.mean(COLD_START_RANGE),
        len(TIMINGS) - 0.35,
        "cold PBS\nspin-up\n3–4 min",
        ha="center",
        va="center",
        color=ORANGE,
        fontsize=8.2,
    )

    ax.set_xscale("log")
    ax.set_xlim(0.7, 320)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    for tick in ax.get_yticklabels():
        tick.set_linespacing(1.25)
    ax.invert_yaxis()
    ax.set_xlabel("wall time (seconds, log scale)")
    ax.set_title(
        "Remote UXarray operations return in seconds once the worker is warm",
        loc="left",
        color=DARK,
        weight="bold",
        pad=12,
    )
    ax.grid(axis="x", which="both", alpha=0.5)
    ax.legend(frameon=False, loc="center right", bbox_to_anchor=(1.0, 0.42))

    for idx, (_, first_value, warm_value, _) in enumerate(TIMINGS):
        ax.text(
            first_value * 1.09,
            idx + height / 2,
            f"{first_value:g}s",
            va="center",
            color=DARK,
            fontsize=8.5,
        )
        ax.text(
            warm_value * 1.12,
            idx - height / 2,
            f"{warm_value:g}s",
            va="center",
            color=DARK,
            fontsize=8.5,
        )

    fig.text(
        0.01,
        -0.02,
        "Source: notebooks/whats_new_0.2_demo.py live Chrysalis runs; cold-start range from endpoint notes.",
        color=MUTED,
        fontsize=8.0,
    )

    save_figure(fig, "fig3_hpc_timing")
    plt.close(fig)

    metadata = {
        "source": "notebooks/whats_new_0.2_demo.py",
        "endpoint": "chrysalis",
        "timings_seconds": [
            {
                "operation": op,
                "first_measured": first_value,
                "warm_worker": warm_value,
                "dataset": note,
            }
            for op, first_value, warm_value, note in TIMINGS
        ],
        "cold_start_seconds_range": list(COLD_START_RANGE),
    }
    with open(
        "outputs/figures/fig3_hpc_timing_metadata.json", "w", encoding="utf-8"
    ) as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
