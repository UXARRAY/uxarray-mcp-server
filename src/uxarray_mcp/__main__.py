"""Run the UXarray MCP CLI as a module (``python -m uxarray_mcp``)."""

import sys

from uxarray_mcp.cli import main as cli_main


def main() -> None:
    """Default to ``serve`` when invoked without a subcommand for back-compat."""
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    raise SystemExit(cli_main())


if __name__ == "__main__":
    main()
