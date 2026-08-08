"""UXarray application — subclass of toolregistry_server.App.

Provides :class:`UXarrayApp`, the central server application that builds
the UXarray tool registry and dispatches to protocol adapters (MCP, OpenAPI).

Identity (product name, version, description) flows automatically to
MCP server name, OpenAPI title, and CLI banner.

Example::

    from uxarray_mcp.app import UXarrayApp

    app = UXarrayApp()
    app.serve_mcp(transport="stdio", profile="core")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from toolregistry_server import ServerIdentity
from toolregistry_server.app import App

from . import __version__
from .registry import Profile

if TYPE_CHECKING:
    from toolregistry import ToolRegistry

UXARRAY_IDENTITY = ServerIdentity(
    name="UXarray MCP",
    version=__version__,
    description="Mesh analysis tools for AI agents",
)


class UXarrayApp(App):
    """UXarray-specific server application.

    Overrides :meth:`prepare_registry` to build the UXarray tool
    registry with profile-based tool surface selection.
    """

    def __init__(self, identity: ServerIdentity | None = None) -> None:
        super().__init__(identity=identity or UXARRAY_IDENTITY)

    def prepare_registry(self, **kwargs) -> ToolRegistry:
        """Build the UXarray tool registry.

        Keyword Args:
            profile: Tool surface profile (``"core"`` or
                ``"deferred-full"``). Defaults to ``"core"``.
        """
        from .registry import build_registry

        profile = kwargs.get("profile", "core")
        return build_registry(profile=profile)


# ---------------------------------------------------------------------------
# Convenience helpers for tests and scripts
# ---------------------------------------------------------------------------


def make_registry(*, profile: Profile = "core") -> ToolRegistry:
    """Build the tool registry for the requested profile."""
    return UXarrayApp().prepare_registry(profile=profile)


#: How long a client may cache our ``tools/list`` response, in milliseconds.
#: The tool surface is fixed at startup by the profile and does not change
#: while the server runs, so re-listing on every turn is pure overhead --
#: the catalog was measured at 74% of the payload on short conversations.
#: Five minutes bounds how long a client can hold a stale surface if a
#: future version does start mutating the registry at runtime.
LIST_TOOLS_TTL_MS = 300_000

#: The surface depends only on the profile, not on the user or session, so
#: a shared cache entry is correct.
LIST_TOOLS_CACHE_SCOPE = "public"


def make_mcp_server(*, profile: Profile = "core"):
    """Build a configured MCP server ready for any transport."""
    from toolregistry_server.adapters.mcp import route_table_to_mcp_server
    from toolregistry_server.route_table import RouteTable

    registry = make_registry(profile=profile)
    route_table = RouteTable(registry)
    return route_table_to_mcp_server(
        route_table,
        name="UXarray MCP",
        list_tools_ttl_ms=LIST_TOOLS_TTL_MS,
        list_tools_cache_scope=LIST_TOOLS_CACHE_SCOPE,
    )
