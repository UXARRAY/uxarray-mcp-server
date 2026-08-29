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


#: How long a client may cache our ``tools/list`` response, in milliseconds.
#: The tool surface is fixed at startup by the profile and does not change
#: while the server runs, so re-listing on every turn is pure overhead --
#: the catalog was measured at 74% of the payload on short conversations.
#: Five minutes bounds how long a client can hold a stale surface if a
#: future version does start mutating the registry at runtime.
#:
#: ``ttlMs`` and ``cacheScope`` are MCP spec 2026-07-28 fields and they do
#: reach the wire on the modern transport: ``mcp`` 2.1.1 has
#: ``MODERN_PROTOCOL_VERSIONS == ("2026-07-28",)`` and ``ListToolsResult``
#: inherits ``CacheableResult``, so a client sending the modern
#: ``MCP-Protocol-Version`` header sees them serialized. Only the legacy
#: ``initialize`` handshake caps out earlier (``LATEST_HANDSHAKE_VERSION`` is
#: 2025-11-25); on that path the SDK strips fields the negotiated era does
#: not define, and the hints simply cost nothing.
LIST_TOOLS_TTL_MS = 300_000

#: The surface depends only on the profile, not on the user or session, so
#: a shared cache entry is correct.
LIST_TOOLS_CACHE_SCOPE = "public"


class UXarrayApp(App):
    """UXarray-specific server application.

    Overrides :meth:`prepare_registry` to build the UXarray tool
    registry with profile-based tool surface selection, and
    :meth:`serve_mcp` so the ``tools/list`` cache hints survive to the wire.
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

    def serve_mcp(self, **kwargs) -> None:
        """Start an MCP server that actually advertises our cache hints.

        The inherited path (``App.serve`` -> ``MCPAdapter.create_and_run``)
        constructs the adapter itself and does not forward
        ``list_tools_ttl_ms`` / ``list_tools_cache_scope``; they fall into
        ``run(**kwargs)`` and are dropped without an error. A server started
        that way advertises the SDK default of ``ttlMs=0``, i.e. immediately
        stale, so every turn re-lists the whole catalog. Constructing the
        adapter here is the only way the hints reach the wire on the CLI
        path, which is the one users actually run.
        """
        from toolregistry_server.adapters.mcp import MCPAdapter

        kwargs.setdefault("identity", self.identity)
        registry = self.prepare_registry(**kwargs)
        route_table = self._make_route_table(registry)

        identity = kwargs.pop("identity")
        name = kwargs.pop("name", identity.name)
        kwargs.pop("profile", None)

        MCPAdapter(
            route_table,
            name=name,
            list_tools_ttl_ms=LIST_TOOLS_TTL_MS,
            list_tools_cache_scope=LIST_TOOLS_CACHE_SCOPE,
        ).run(**kwargs)


# ---------------------------------------------------------------------------
# Convenience helpers for tests and scripts
# ---------------------------------------------------------------------------


def make_registry(*, profile: Profile = "core") -> ToolRegistry:
    """Build the tool registry for the requested profile."""
    return UXarrayApp().prepare_registry(profile=profile)


def make_mcp_server(*, profile: Profile = "core"):
    """Build a configured MCP server ready for any transport.

    Carries the same ``tools/list`` cache hints as :meth:`UXarrayApp.serve_mcp`
    so tests and scripts exercise the surface the CLI actually serves.
    """
    from toolregistry_server.adapters.mcp import route_table_to_mcp_server
    from toolregistry_server.route_table import RouteTable

    registry = make_registry(profile=profile)
    return route_table_to_mcp_server(
        RouteTable(registry),
        "UXarray MCP",
        list_tools_ttl_ms=LIST_TOOLS_TTL_MS,
        list_tools_cache_scope=LIST_TOOLS_CACHE_SCOPE,
    )
