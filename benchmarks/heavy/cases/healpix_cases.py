"""HEALPix-specific benchmark cases.

HEALPix is the one grid family where correctness is checkable in closed
form: zoom ``z`` has exactly ``12 * 4**z`` equal-area faces covering the unit
sphere, so the total area must be ``4*pi`` and every face area must be
identical.  That makes it the sharpest available probe for silent breakage in
grid loading, area computation, and zonal binning.

Cases here take a ``Ctx`` from :mod:`cases.pipeline_cases` so the shared
runner can execute HEALPix and file-backed meshes through one code path.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from .pipeline_cases import Ctx, _unwrap_plot

#: Zoom levels exercised by the resolution sweep.  z=7 is ~197k faces, which
#: is heavy enough to be a real workload but still finishes locally.
SWEEP_ZOOMS = (0, 1, 2, 3, 4, 5, 6, 7)


def expected_n_face(zoom: int) -> int:
    """Analytic face count for a HEALPix grid at ``zoom``."""
    return 12 * 4**zoom


def case_healpix_zoom_sweep(ctx: Ctx) -> dict:
    """Load every zoom in the sweep and check the analytic invariants.

    Verifies ``n_face == 12 * 4**z`` and that reported face areas sum to the
    surface area of the unit sphere with all faces equal (the defining
    HEALPix property).
    """
    from uxarray_mcp.tools import calculate_area, inspect_mesh

    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for zoom in SWEEP_ZOOMS:
        spec = f"healpix:{zoom}"
        mesh = inspect_mesh(spec)
        area = calculate_area(spec)

        want = expected_n_face(zoom)
        got = int(mesh["n_face"])
        total = float(area["total_area"])
        spread = float(area["max_area"]) - float(area["min_area"])
        mean = float(area["mean_area"])

        if got != want:
            problems.append(f"zoom={zoom}: n_face {got} != analytic {want}")
        # Unit-sphere total must be 4*pi.
        if not math.isclose(total, 4.0 * math.pi, rel_tol=1e-9):
            problems.append(f"zoom={zoom}: total_area {total!r} != 4*pi")
        # Equal-area is the defining property; allow only float noise.
        if mean and spread / mean > 1e-9:
            problems.append(
                f"zoom={zoom}: faces not equal-area, spread/mean={spread / mean:.3e}"
            )
        if int(area["n_face"]) != got:
            problems.append(
                f"zoom={zoom}: calculate_area n_face {area['n_face']} "
                f"disagrees with inspect_mesh {got}"
            )
        rows.append(
            {
                "zoom": zoom,
                "n_face": got,
                "expected_n_face": want,
                "total_area": total,
                "area_spread": spread,
            }
        )
    return {"zooms": rows, "problems": problems, "_provenance": mesh["_provenance"]}


def case_healpix_spec_parsing(ctx: Ctx) -> dict:
    """Malformed and case-variant specs must be handled consistently.

    Regression guard for three real bugs: a prefix-only ``startswith`` test
    hijacked ordinary files named ``healpix*``; local code accepted
    ``HEALPix:3`` while remote routing rejected it; and a bad zoom was
    silently coerced to a valid grid of the wrong size.
    """
    from uxarray_mcp.domain.mesh import is_healpix_spec, parse_healpix_zoom
    from uxarray_mcp.tools.remote_tools import _path_is_locally_reachable

    problems: list[str] = []

    # Case-insensitive: local loaders and remote routing must agree.
    for spec in ("healpix:3", "HEALPix:3", "HEALPIX:3"):
        if not is_healpix_spec(spec):
            problems.append(f"{spec!r} not recognized as a HEALPix spec")
        if not _path_is_locally_reachable(spec):
            problems.append(f"{spec!r} judged unreachable by remote routing")

    # Real files that merely start with "healpix" must NOT be hijacked.
    for path in ("healpix_z5_data.nc", "/scratch/healpix_out.nc", "healpix"):
        if is_healpix_spec(path):
            problems.append(f"{path!r} wrongly treated as a virtual HEALPix spec")

    # Malformed zoom must raise, not silently produce the wrong resolution.
    for bad in ("healpix:", "healpix:abc", "healpix:-1", "healpix:99"):
        try:
            zoom = parse_healpix_zoom(bad)
        except ValueError:
            continue
        problems.append(f"{bad!r} silently accepted as zoom={zoom}")

    return {"problems": problems, "_pure": True}


def case_healpix_zonal_mean(ctx: Ctx) -> dict:
    """Zonal mean on a HEALPix grid must return degrees, not indices."""
    from uxarray_mcp.tools import calculate_zonal_mean

    return calculate_zonal_mean(
        ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs
    )


def case_healpix_zonal_symmetry(ctx: Ctx) -> dict:
    """The synthetic field is symmetric in latitude, so the profile must be.

    ``temperature`` is built as ``288 - 40*sin(lat)^2 + 3*cos(2*lon)``.  The
    longitude term averages out over a full zonal band, leaving an even
    function of latitude -- a strong end-to-end check that binning assigns
    faces to the correct band.
    """
    import numpy as np

    from uxarray_mcp.tools import calculate_zonal_mean

    result = calculate_zonal_mean(
        ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs
    )
    lats = np.asarray(result.get("latitudes"), dtype="float64")
    vals = np.asarray(result.get("zonal_mean_values"), dtype="float64")

    problems: list[str] = []
    if vals.ndim == 1 and lats.size == vals.size:
        order = np.argsort(lats)
        lat_sorted, val_sorted = lats[order], vals[order]
        mirror = np.isclose(lat_sorted, -lat_sorted[::-1], atol=1e-6)
        if mirror.all():
            asym = np.nanmax(np.abs(val_sorted - val_sorted[::-1]))
            spread = np.nanmax(val_sorted) - np.nanmin(val_sorted)
            if spread > 0 and asym / spread > 0.02:
                problems.append(
                    f"zonal profile not symmetric: max asymmetry {asym:.4f} "
                    f"({100 * asym / spread:.1f}% of range)"
                )
    else:
        problems.append(
            f"cannot test symmetry: lats {lats.shape} vs values {vals.shape}"
        )

    result["problems"] = problems
    return result


def case_healpix_plot_variable(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import plot_variable

    return _unwrap_plot(
        plot_variable(ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs)
    )


def case_healpix_plot_zonal_mean(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import plot_zonal_mean

    return _unwrap_plot(
        plot_zonal_mean(ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs)
    )


def case_healpix_register_dataset(ctx: Ctx) -> dict:
    """A HEALPix spec must be registrable in a session (no file on disk)."""
    from uxarray_mcp.tools.stateful import create_session, register_dataset

    session_id = create_session()["session_id"]
    return register_dataset(session_id, ctx.grid_path, ctx.data_path)


def case_healpix_validate_dataset(ctx: Ctx) -> dict:
    from uxarray_mcp.tools.remote_tools import validate_dataset

    return validate_dataset(ctx.grid_path, ctx.data_path, **ctx.remote_kwargs)


def case_healpix_capabilities(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import get_capabilities

    return get_capabilities(ctx.grid_path, ctx.data_path, **ctx.remote_kwargs)


def case_healpix_azimuthal_mean(ctx: Ctx) -> dict:
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


def case_healpix_gradient(ctx: Ctx) -> dict:
    from uxarray_mcp.tools import calculate_gradient

    return calculate_gradient(
        ctx.grid_path, ctx.data_path, ctx.variable, **ctx.remote_kwargs
    )


#: Structural/cheap cases first, compute-heavy ones last.
HEALPIX_PIPELINE: list[tuple[str, Callable[[Ctx], Any]]] = [
    ("healpix_spec_parsing", case_healpix_spec_parsing),
    ("healpix_zoom_sweep", case_healpix_zoom_sweep),
    ("healpix_capabilities", case_healpix_capabilities),
    ("healpix_register_dataset", case_healpix_register_dataset),
    ("healpix_validate_dataset", case_healpix_validate_dataset),
    ("healpix_zonal_mean", case_healpix_zonal_mean),
    ("healpix_zonal_symmetry", case_healpix_zonal_symmetry),
    ("healpix_azimuthal_mean", case_healpix_azimuthal_mean),
    ("healpix_gradient", case_healpix_gradient),
    ("healpix_plot_zonal_mean", case_healpix_plot_zonal_mean),
    ("healpix_plot_variable", case_healpix_plot_variable),
]
