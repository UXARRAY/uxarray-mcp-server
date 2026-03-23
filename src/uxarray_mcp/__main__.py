"""Run the UXarray MCP Server as a module."""

from uxarray_mcp.server import mcp


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
