"""Shared scientific computation layer for UXarray MCP Server.

Functions here contain the pure domain logic used by both local tools
(inspection.py) and remote HPC functions (compute_functions.py).
"""

from .area import compute_area_stats
from .mesh import load_grid
from .variable import compute_variable_info
from .zonal import compute_zonal_mean_stats

__all__ = [
    "load_grid",
    "compute_area_stats",
    "compute_variable_info",
    "compute_zonal_mean_stats",
]
