"""What of UXarray this server reaches, and what it deliberately does not.

The server is intent-shaped rather than a binding layer, so it was never
going to expose every UXarray method and should not try. The risk is not
incompleteness; it is incompleteness nobody decided on. A method appears
upstream, no one notices, and the gap is discovered by a user whose
notebook does the obvious thing.

:data:`SURFACE` is that decision written down. Every UXarray-specific
science method is listed once, with either the operation that reaches it
or the reason it is out of scope. ``tests/test_uxarray_surface.py`` holds
the list to the installed library: a new method upstream fails the test
until someone records a verdict, and a renamed one fails it the day the
rename lands rather than the next time a user tries it.

Deliberately *not* a count. A test asserting "we expose N of M methods"
goes red on every upstream release for reasons nobody can act on, and the
fix is to edit the number -- which teaches people to stop reading it.
"""

from __future__ import annotations

from typing import Literal

#: Why a method is not reachable. Narrow on purpose: if a gap does not fit
#: one of these, it probably has not been thought about yet.
Verdict = Literal[
    "exposed",
    # Reachable, but the server spells it differently -- usually because
    # the intent, not the method, is what a caller names.
    "exposed-aliased",
    # A deliberate omission, with the reason in the second field.
    "out-of-scope",
    # Known gap we intend to close. Kept distinct from out-of-scope so the
    # backlog is visible rather than quietly accepted.
    "gap",
]

#: method -> (verdict, how it is reached, or why it is not)
#:
#: Keys are attribute names on ``UxDataArray``/``UxDataset`` (minus what
#: they inherit from xarray) and on the ``subset`` accessor. The xarray
#: surface is excluded on purpose: ~150 inherited methods would swamp the
#: list and none of them are UXarray's to change.
SURFACE: dict[str, tuple[Verdict, str]] = {
    # -- selection ---------------------------------------------------
    "subset": (
        "out-of-scope",
        "the accessor object itself; its methods are listed individually",
    ),
    "subset.bounding_box": ("exposed", "run_analysis(operation='subset_bbox')"),
    "subset.bounding_circle": (
        "exposed",
        "subset_advanced(selection='circle')",
    ),
    "subset.nearest_neighbor": (
        "exposed",
        "subset_advanced(selection='nearest')",
    ),
    "subset.constant_latitude": (
        "exposed-aliased",
        "run_analysis(operation='cross_section', latitude=...)",
    ),
    "subset.constant_longitude": (
        "exposed-aliased",
        "run_analysis(operation='cross_section', longitude=...)",
    ),
    "subset.constant_latitude_interval": (
        "gap",
        (
            "a latitude band; subset_bbox spanning all longitudes is close but "
            "selects by face bounds rather than by band membership"
        ),
    ),
    "subset.constant_longitude_interval": (
        "gap",
        "a longitude band; same reasoning as the latitude interval",
    ),
    # -- reductions and calculus -------------------------------------
    "zonal_mean": ("exposed", "run_analysis(operation='calculate_zonal_mean')"),
    "zonal_average": ("exposed-aliased", "alias of zonal_mean upstream"),
    "zonal_anomaly": ("exposed", "run_analysis(operation='zonal_anomaly')"),
    "azimuthal_mean": ("exposed", "run_analysis(operation='azimuthal_mean')"),
    "azimuthal_average": ("exposed-aliased", "alias of azimuthal_mean upstream"),
    "gradient": ("exposed", "run_analysis(operation='gradient')"),
    "curl": ("exposed", "run_analysis(operation='curl')"),
    "divergence": ("exposed", "run_analysis(operation='divergence')"),
    "difference": ("exposed-aliased", "run_analysis(operation='compare_fields')"),
    "remap": ("exposed", "run_analysis(operation='remap_variable', method=...)"),
    "cross_section": ("exposed", "run_analysis(operation='cross_section')"),
    # -- node/edge/face transfer -------------------------------------
    "topological_mean": (
        "exposed",
        (
            "regrid_elements(statistic='mean'); also the repair named when a "
            "face-centered operation is handed node-centered data"
        ),
    ),
    "topological_min": ("exposed", "regrid_elements(statistic='min')"),
    "topological_max": ("exposed", "regrid_elements(statistic='max')"),
    "topological_sum": ("exposed", "regrid_elements(statistic='sum')"),
    "topological_std": ("exposed", "regrid_elements(statistic='std')"),
    "topological_var": ("exposed", "regrid_elements(statistic='var')"),
    "topological_median": ("exposed", "regrid_elements(statistic='median')"),
    "topological_prod": (
        "out-of-scope",
        (
            "a product over neighbouring elements has no physical reading for "
            "a geophysical field; the other reductions do"
        ),
    ),
    "topological_any": (
        "out-of-scope",
        "boolean reduction; the server's operations are all on float fields",
    ),
    "topological_all": (
        "out-of-scope",
        "boolean reduction; see topological_any",
    ),
    # -- known gaps ---------------------------------------------------
    "weighted_mean": (
        "gap",
        (
            "area-weighted field mean. calculate_area reports the areas and "
            "several operations weight internally, but a caller cannot ask for "
            "the weighted mean of a field on its own"
        ),
    ),
    "neighborhood": (
        "gap",
        (
            "neighbourhood filtering, used by the cyclone-tracking notebook in "
            "UXARRAY/uxarray-community"
        ),
    ),
    "to_raster": (
        "gap",
        (
            "rasterization. plot_dataset renders images; this returns the array "
            "behind one, which is a different request"
        ),
    ),
    # -- out of scope -------------------------------------------------
    "get_dual": (
        "out-of-scope",
        (
            "constructs the dual mesh -- a mesh-authoring operation, not an "
            "analysis of a field the caller already has"
        ),
    ),
    "scalardotgradient": (
        "out-of-scope",
        (
            "a composition of gradient and a dot product; both parts are "
            "reachable and the composition is the caller's to make"
        ),
    ),
    # -- plumbing, never exposed -------------------------------------
    "uxgrid": ("out-of-scope", "attribute access, not an operation"),
    "to_xarray": ("out-of-scope", "type conversion"),
    "from_xarray": ("out-of-scope", "type conversion"),
    "from_healpix": ("out-of-scope", "constructor; grid_path='healpix:<zoom>'"),
    "from_structured": ("out-of-scope", "constructor"),
    "to_geodataframe": ("out-of-scope", "type conversion"),
    "to_polycollection": ("out-of-scope", "type conversion, matplotlib-specific"),
    "data_mapping": ("out-of-scope", "attribute access"),
    "source_datasets": ("out-of-scope", "attribute access"),
}

#: Verdicts that mean a caller can actually run the thing.
REACHABLE: frozenset[str] = frozenset({"exposed", "exposed-aliased"})


def unreachable() -> dict[str, tuple[Verdict, str]]:
    """The part of UXarray a caller cannot get to through this server."""
    return {k: v for k, v in SURFACE.items() if v[0] not in REACHABLE}


def gaps() -> dict[str, str]:
    """Known gaps we mean to close, as ``name -> reason``."""
    return {k: v[1] for k, v in SURFACE.items() if v[0] == "gap"}
