#!/usr/bin/env python3
"""Verify a clean uxarray-mcp install over the real stdio MCP transport."""

from __future__ import annotations

import argparse
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _check(command: str) -> None:
    server = StdioServerParameters(command=command, args=["serve", "--profile", "core"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            required = {"get_capabilities", "run_analysis"}
            if not required.issubset(names):
                raise RuntimeError(
                    f"Missing required tools: {sorted(required - names)}"
                )
            result = await session.call_tool(
                "get_capabilities", {"grid_path": "healpix:1"}
            )
            if result.is_error:
                raise RuntimeError(f"get_capabilities failed: {result.content}")
            print(
                f"MCP handshake passed: {initialized.server_info.name} "
                f"with {len(listed.tools)} tools"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", default="uxarray-mcp")
    args = parser.parse_args()
    asyncio.run(_check(args.command))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
