"""Shared scientific computation layer for UXarray MCP Server.

Functions here contain the pure domain logic used by both local tools
(inspection.py) and remote HPC functions (compute_functions.py).
"""

from .area import compute_area_stats
from .mesh import (
    attach_grid,
    is_healpix_spec,
    is_kerchunk_reference,
    is_opendap_uri,
    is_remote_uri,
    is_scrip_weights,
    load_dataset,
    load_grid,
    open_grid_object,
    open_remote_store,
    parse_healpix_zoom,
    scrip_grid_from_weights,
)
from .mesh_coverage import (
    compute_mesh_coverage,
    mesh_coverage_warning_codes,
    mesh_is_closed,
)
from .profile_coverage import (
    compute_profile_coverage,
    profile_coverage_warning_codes,
)
from .remap_coverage import (
    compute_scattered_coverage,
    compute_target_coverage,
    method_is_conservative,
)
from .variable import compute_variable_info
from .vector_calc import (
    compute_azimuthal_mean,
    compute_curl,
    compute_divergence,
    compute_gradient,
)
from .zonal import compute_zonal_anomaly_stats, compute_zonal_mean_stats

__all__ = [
    "load_grid",
    "load_dataset",
    "is_healpix_spec",
    "is_remote_uri",
    "is_opendap_uri",
    "is_kerchunk_reference",
    "open_remote_store",
    "is_scrip_weights",
    "scrip_grid_from_weights",
    "open_grid_object",
    "attach_grid",
    "parse_healpix_zoom",
    "compute_area_stats",
    "compute_mesh_coverage",
    "mesh_coverage_warning_codes",
    "mesh_is_closed",
    "compute_profile_coverage",
    "profile_coverage_warning_codes",
    "compute_target_coverage",
    "compute_scattered_coverage",
    "method_is_conservative",
    "compute_variable_info",
    "compute_zonal_mean_stats",
    "compute_zonal_anomaly_stats",
    "compute_gradient",
    "compute_curl",
    "compute_divergence",
    "compute_azimuthal_mean",
]
