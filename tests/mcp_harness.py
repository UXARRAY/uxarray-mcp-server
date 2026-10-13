"""Drive the real server over the MCP wire, in process.

Every other test in this suite calls a tool function directly, or inspects a
registry object. That is a layer below where clients live. It cannot see a
response that fails to serialise, a schema the SDK rejects, a capability we
forgot to advertise, or a field that silently became empty -- all of which are
things a client experiences and no amount of unit testing notices.

``connect()`` runs ``make_mcp_server()`` -- the same builder the CLI serves --
against an in-memory stream pair and hands back an initialised
``ClientSession``. No subprocess, no stdio, no network: the transport is
``create_client_server_memory_streams`` from the SDK's own test support, so
the bytes still go through the SDK's framing, validation and error mapping
exactly as they would over a pipe.

Assert on **wire JSON** (:func:`wire`) rather than on Python attributes where
the shape is what matters. The SDK renames attributes between majors --
``serverInfo`` became ``server_info`` in mcp 2.x, and that rename is precisely
the kind of break this harness exists to catch -- but the JSON key a client
reads stays ``serverInfo`` either way. A test written against the attribute
name passes or fails for reasons that have nothing to do with our behaviour.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import InitializeResult

from uxarray_mcp.app import make_mcp_server

#: Default profile for harness tests. ``core`` is what a first-run user gets
#: and is a third of the size of ``deferred-full``, so the suite stays quick
#: while still covering the path everyone actually takes.
DEFAULT_PROFILE = "core"


def wire(model: Any) -> Any:
    """Serialise a pydantic model exactly as it goes out on the wire.

    ``by_alias=True`` is the whole point: it produces ``serverInfo``,
    ``inputSchema``, ``structuredContent`` -- the camelCase keys the protocol
    specifies -- rather than the snake_case Python attribute names, which are
    an SDK implementation detail and have already changed once.
    """
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


@asynccontextmanager
async def connect(
    *, profile: str = DEFAULT_PROFILE
) -> AsyncIterator[tuple[ClientSession, InitializeResult]]:
    """Run the real MCP server in-process; yield a connected client session.

    The server is driven through ``Server.run`` with the same initialisation
    options the stdio entry point builds, so the ``tools/list`` cache hints
    and the tools-changed notification options are the ones users get.
    """
    from toolregistry_server.adapters.mcp._compat import (
        tools_changed_notification_options,
    )

    server = make_mcp_server(profile=profile)

    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        read_server, write_server = server_streams

        async with anyio.create_task_group() as tg:

            async def _serve() -> None:
                await server.run(
                    read_server,
                    write_server,
                    server.create_initialization_options(
                        notification_options=tools_changed_notification_options(),
                    ),
                )

            tg.start_soon(_serve)
            async with ClientSession(*client_streams) as session:
                init = await session.initialize()
                yield session, init
            tg.cancel_scope.cancel()
