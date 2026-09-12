import asyncio, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command="/tmp/roda-venv/bin/awslabs.roda-mcp-server", args=[])
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
