"""Correctness assertions applied to heavy-benchmark results.

A tool that returns *something* is not a tool that returned the *right*
thing.  These checks encode the invariants that a green pytest run does not
cover, because the unit tests mock the UXarray layer.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _shape(values: Any) -> tuple:
    try:
        return np.asarray(values, dtype="float64").shape
    except (ValueError, TypeError):
        return ()


def check_zonal(name: str, result: dict) -> list[str]:
    """Latitude coordinates must be latitudes, and must match the value axis."""
    problems: list[str] = []
    lats = result.get("latitudes")
    values = result.get("zonal_mean_values")
    if lats is None or values is None:
        return [f"{name}: missing latitudes/zonal_mean_values"]

    lats_arr = np.asarray(lats, dtype="float64")
    shape = _shape(values)

    if lats_arr.size and not ((lats_arr >= -90.0) & (lats_arr <= 90.0)).all():
        problems.append(
            f"{name}: latitudes outside [-90, 90] -> {lats_arr[:6].tolist()}"
        )
    # A monotonically increasing 0..N-1 run is the signature of a time axis
    # leaking into the latitude slot.
    if lats_arr.size > 2 and np.array_equal(lats_arr, np.arange(lats_arr.size)):
        problems.append(
            f"{name}: latitudes look like positional indices, not degrees "
            f"-> {lats_arr[:6].tolist()}"
        )
    if shape and shape[-1] != lats_arr.size:
        problems.append(
            f"{name}: value axis {shape} does not match {lats_arr.size} latitudes"
        )
    return problems


def check_plot(name: str, result: dict) -> list[str]:
    problems: list[str] = []
    size = result.get("image_size_bytes")
    b64_len = result.get("png_b64_len")
    if not size:
        problems.append(f"{name}: image_size_bytes missing/zero")
    if b64_len is not None and b64_len == 0:
        problems.append(f"{name}: empty PNG payload")
    return problems


def check_provenance(name: str, result: dict, *, remote: bool) -> list[str]:
    """Provenance must describe where the work actually ran.

    Cases that only exercise pure predicates (no tool call, no compute) set
    ``_pure`` and are exempt -- demanding provenance from them would be a
    false positive that trains the reader to ignore this check.
    """
    problems: list[str] = []
    if result.get("_pure"):
        return problems
    prov = result.get("_provenance")
    if not isinstance(prov, dict):
        return [f"{name}: no _provenance"]

    venue = prov.get("execution_venue")
    if remote:
        if not (venue or "").startswith("hpc:"):
            problems.append(f"{name}: expected hpc venue, got {venue!r}")
        if not prov.get("remote_hostname"):
            problems.append(f"{name}: remote run has no remote_hostname")
        if not prov.get("python_version"):
            problems.append(f"{name}: remote run has no worker python_version")
    elif venue not in (None, "local"):
        problems.append(f"{name}: expected local venue, got {venue!r}")
    return problems


def check_subset(name: str, result: dict) -> list[str]:
    problems: list[str] = []
    original = (result.get("original_grid") or {}).get("n_face")
    subset = (result.get("subset_grid") or {}).get("n_face")
    if original and subset:
        if subset >= original:
            problems.append(f"{name}: subset {subset} not smaller than {original}")
        if subset == 0:
            problems.append(f"{name}: subset selected zero faces")
    return problems


def run_checks(name: str, result: Any, *, remote: bool) -> list[str]:
    """Dispatch the assertions relevant to ``name``."""
    if not isinstance(result, dict):
        return [f"{name}: result is {type(result).__name__}, expected dict"]

    problems = check_provenance(name, result, remote=remote)
    if "zonal_mean" in name:
        problems += check_zonal(name, result)
    if name.startswith("plot_"):
        problems += check_plot(name, result)
    if name.startswith("subset_"):
        problems += check_subset(name, result)
    if name == "azimuthal_mean":
        radii = np.asarray(result.get("radii_deg") or [], dtype="float64")
        if radii.size > 2 and np.array_equal(radii, np.arange(radii.size)):
            problems.append(
                f"{name}: radii look like positional indices -> {radii[:6].tolist()}"
            )
    return problems
