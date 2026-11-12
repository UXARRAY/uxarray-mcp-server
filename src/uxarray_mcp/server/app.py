"""Serve the registry over MCP."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from toolregistry_server import ServerIdentity
from toolregistry_server.app import App

from uxarray_mcp import __version__
from uxarray_mcp.server.registry import build_registry
from uxarray_mcp.server.resources import attach_artifact_resources

if TYPE_CHECKING:
    from toolregistry import ToolRegistry

IDENTITY = ServerIdentity(
    name="UXarray MCP",
    version=__version__,
    description="Inspect, compute on, remap and plot unstructured climate meshes.",
)

#: tools/list cache hints: the surface is static for the life of the process.
LIST_TOOLS_TTL_MS = 300_000
LIST_TOOLS_CACHE_SCOPE = "public"


def _stamp_version(server: Any) -> Any:
    # Upstream constructs the SDK Server without a version; clients would see "".
    try:
        server.version = __version__
    except AttributeError:  # pragma: no cover
        pass
    return server


class UXarrayApp(App):
    def __init__(self) -> None:
        super().__init__(identity=IDENTITY)

    def prepare_registry(self, **kwargs: Any) -> ToolRegistry:
        return build_registry()

    def serve_mcp(self, **kwargs: Any) -> None:
        """Run the MCP adapter with cache hints and artifact resources attached."""
        from toolregistry_server.adapters.mcp import MCPAdapter

        route_table = self._make_route_table(self.prepare_registry())
        kwargs.pop("identity", None)
        adapter = MCPAdapter(
            route_table,
            name=kwargs.pop("name", IDENTITY.name),
            list_tools_ttl_ms=LIST_TOOLS_TTL_MS,
            list_tools_cache_scope=LIST_TOOLS_CACHE_SCOPE,
        )
        _stamp_version(adapter.server)
        attach_artifact_resources(adapter.server)
        adapter.run(**kwargs)


def make_registry() -> ToolRegistry:
    return build_registry()


def make_mcp_server() -> Any:
    """An MCP server object for in-process tests; same wiring as ``serve_mcp``."""
    from toolregistry_server.adapters.mcp import route_table_to_mcp_server
    from toolregistry_server.route_table import RouteTable

    server = route_table_to_mcp_server(
        RouteTable(make_registry()),
        IDENTITY.name,
        list_tools_ttl_ms=LIST_TOOLS_TTL_MS,
        list_tools_cache_scope=LIST_TOOLS_CACHE_SCOPE,
    )
    _stamp_version(server)
    return attach_artifact_resources(server)
