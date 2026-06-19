"""UXarray MCP Server — multi-protocol tool surface powered by toolregistry.

Replaces the previous FastMCP-based server with ``toolregistry`` +
``toolregistry-server``.  The same tool functions from
``uxarray_mcp.tools`` are exposed, now with:

- Namespace grouping (session/, hpc/, prompt/, compute/, ...)
- Two profiles: ``core`` (conservative default) and ``deferred-full``
  (complete pool with BM25 discovery)
- Policy tags on every tool from day one
- Multi-transport MCP (stdio / SSE / streamable HTTP)
- Optional OpenAPI / REST surface from the same process

Backward compatibility:

- ``python -m uxarray_mcp`` and ``uxarray-mcp serve`` still start an
  MCP stdio server with the same default tool surface.
- Claude Desktop ``mcpServers`` snippets continue to work unchanged.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from toolregistry_server import RouteTable
from toolregistry_server.mcp import (
    create_mcp_server,
    run_sse,
    run_stdio,
    run_streamable_http,
)

from uxarray_mcp.registry import Profile, build_registry

if TYPE_CHECKING:
    from mcp.server.lowlevel import Server
    from toolregistry import ToolRegistry

Transport = Literal["stdio", "sse", "http"]


def make_registry(
    *,
    profile: Profile = "core",
) -> "ToolRegistry":
    """Build the tool registry for the requested profile.

    This is the single source of truth for the tool surface. CLI,
    server entry points, and tests all call through here.
    """
    return build_registry(profile=profile)


def make_mcp_server(
    *,
    profile: Profile = "core",
) -> "Server":
    """Build a configured MCP server ready for any transport."""
    registry = make_registry(profile=profile)
    route_table = RouteTable(registry)
    return create_mcp_server(route_table, name="uxarray-mcp-server")


def run(
    *,
    profile: Profile = "core",
    transport: Transport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8001,
) -> None:
    """Run the MCP server on the requested transport.

    Args:
        profile: Tool surface profile (``"core"`` or ``"deferred-full"``).
        transport: MCP transport (``"stdio"``, ``"sse"``, or ``"http"``).
        host: Bind address for SSE / HTTP transports.
        port: Port for SSE / HTTP transports.
    """
    server = make_mcp_server(profile=profile)
    if transport == "stdio":
        asyncio.run(run_stdio(server))
    elif transport == "sse":
        asyncio.run(run_sse(server, host=host, port=port))
    elif transport == "http":
        asyncio.run(run_streamable_http(server, host=host, port=port))
    else:
        raise ValueError(f"unknown transport {transport!r}")


if __name__ == "__main__":
    run()
