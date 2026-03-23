"""Remote execution support for UXarray MCP server via Globus Compute and Academy."""

from .agent import UXarrayComputeAgent
from .config import load_config

__all__ = ["load_config", "UXarrayComputeAgent"]
