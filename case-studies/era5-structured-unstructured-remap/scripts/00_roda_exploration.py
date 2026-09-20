"""Ask AWS's RODA MCP server what it knows about ERA5.

This is the discovery step, and the reason the case study is framed around
RODA at all: the registry is a catalog, so it answers *which bucket, which
region, what layout* and nothing more. The bytes come from S3 afterwards
(``00_download_era5.py``).

Two things this script exists to record, both found the hard way:

- ``get_dataset_details`` takes ``slug``, not the ``dataset``/``name`` the
  obvious guesses suggest.
- ``preview_dataset`` caps its listing at 10 objects, which is why the real
  bucket layout had to be worked out against S3 directly rather than read
  off the registry.

The server is a separate install, not a dependency of this repo:

    uv venv /tmp/roda-venv
    uv pip install --python /tmp/roda-venv/bin/python awslabs-roda-mcp-server
    python scripts/00_roda_exploration.py

Set ``RODA_MCP_COMMAND`` if it lives somewhere else.
"""

import asyncio
import json  # noqa: F401  (kept: handy when inspecting raw tool payloads)
import os
import shutil

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_COMMAND = "/tmp/roda-venv/bin/awslabs.roda-mcp-server"
COMMAND = os.environ.get("RODA_MCP_COMMAND", DEFAULT_COMMAND)


async def main():
    if not (os.path.exists(COMMAND) or shutil.which(COMMAND)):
        raise SystemExit(
            f"RODA MCP server not found at {COMMAND}\n"
            "install it, or set RODA_MCP_COMMAND:\n"
            "  uv venv /tmp/roda-venv\n"
            "  uv pip install --python /tmp/roda-venv/bin/python "
            "awslabs-roda-mcp-server"
        )

    params = StdioServerParameters(command=COMMAND, args=[])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()

            for slug in ["nsf-ncar-era5", "ecmwf-era5"]:
                res = await session.call_tool("get_dataset_details", {"slug": slug})
                print(f"\n=== get_dataset_details({slug}) ===")
                for c in res.content:
                    print(getattr(c, "text", c)[:2500])

            res = await session.call_tool("preview_dataset", {"slug": "nsf-ncar-era5"})
            print("\n=== preview_dataset(nsf-ncar-era5) ===")
            for c in res.content:
                print(getattr(c, "text", c)[:3000])


asyncio.run(main())
