"""Remote execution support for UXarray MCP server via Globus Compute and Academy."""

from .config import load_config
from .agent import UXarrayComputeAgent

__all__ = ["load_config", "UXarrayComputeAgent"]
