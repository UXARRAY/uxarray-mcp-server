"""Resolve which remapping engine a request means.

UXarray exposes two engines behind one accessor. Its own implements
``nearest_neighbor``, ``inverse_distance_weighted`` and ``bilinear``; YAC,
when its Python bindings are importable, adds ``nnn``, ``dnn``, ``average``
and ``conservative``. Conservative remapping is the one that matters for
fluxes, and it exists only on the YAC side.

A caller can say either ``backend="yac", yac_method="conservative"`` or the
shorter ``method="conservative"``; both mean the same call. This module turns
whichever was said into one canonical triple so the local and remote paths
dispatch identically. The remote payload in ``remote/compute_functions.py``
inlines the same rules, because the worker has no ``uxarray_mcp`` to import.
"""

from __future__ import annotations

from dataclasses import dataclass

#: UXarray's native accessor methods.
UXARRAY_METHODS = ("nearest_neighbor", "inverse_distance_weighted", "bilinear")

#: YAC interpolation stacks reachable through UXarray's ``backend="yac"``.
YAC_METHODS = ("nnn", "dnn", "average", "conservative")


@dataclass(frozen=True)
class RemapPlan:
    """One resolved remap request."""

    backend: str
    method: str
    yac_method: str | None

    @property
    def label(self) -> str:
        """Name reported in results: ``nearest_neighbor`` or ``yac:conservative``."""
        return f"yac:{self.yac_method}" if self.backend == "yac" else self.method

    @property
    def coverage_method(self) -> str:
        """The method name the coverage helpers should judge conservation by."""
        if self.backend == "yac" and self.yac_method is not None:
            return self.yac_method
        return self.method


def resolve_remap_plan(
    method: str = "nearest_neighbor",
    backend: str = "uxarray",
    yac_method: str | None = None,
) -> RemapPlan:
    """Normalise ``method``/``backend``/``yac_method`` into one plan.

    Raises
    ------
    ValueError
        For an unknown backend or method, or for ``yac_method`` given with
        ``backend="uxarray"``, which would otherwise be silently ignored.
    """
    method_l = (method or "nearest_neighbor").strip().lower()
    backend_l = (backend or "uxarray").strip().lower()
    yac_l = yac_method.strip().lower() if yac_method else None

    # ``method="conservative"`` is the natural thing to ask for; route it.
    if method_l in YAC_METHODS:
        if yac_l and yac_l != method_l:
            raise ValueError(
                f"method={method!r} and yac_method={yac_method!r} disagree; "
                "pass one or the other."
            )
        backend_l, yac_l = "yac", method_l

    if backend_l == "yac":
        yac_l = yac_l or "nnn"
        if yac_l not in YAC_METHODS:
            raise ValueError(
                f"Unsupported yac_method {yac_method!r}. Choose from "
                f"{', '.join(repr(m) for m in YAC_METHODS)}."
            )
        return RemapPlan(backend="yac", method=method_l, yac_method=yac_l)

    if backend_l != "uxarray":
        raise ValueError(
            f"Unsupported remap backend {backend!r}. Choose 'uxarray' or 'yac'."
        )
    if yac_l:
        raise ValueError(
            f"yac_method={yac_method!r} requires backend='yac'; with the "
            "uxarray backend it would be ignored."
        )
    if method_l not in UXARRAY_METHODS:
        raise ValueError(
            f"Unsupported remap method {method!r}. Choose from "
            f"{', '.join(repr(m) for m in UXARRAY_METHODS)} (uxarray backend) "
            f"or {', '.join(repr(m) for m in YAC_METHODS)} (YAC backend)."
        )
    return RemapPlan(backend="uxarray", method=method_l, yac_method=None)


def yac_unavailable_message(venue: str) -> str:
    """Explain a failed YAC import in terms of what the caller can do."""
    return (
        "backend='yac' was requested but the 'yac' Python package could not be "
        f"imported on the {venue}. Build YAC with Python bindings "
        "(scripts/build_yac_local.sh locally, scripts/hpc_build_yac.py on a "
        "worker) and put its site-packages on PYTHONPATH, or use "
        "backend='uxarray' with method='nearest_neighbor', "
        "'inverse_distance_weighted' or 'bilinear'."
    )
