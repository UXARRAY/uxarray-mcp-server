#!/usr/bin/env python3
"""Legacy entry point — prefer ``uxarray-mcp doctor``.

Kept as a thin shim so older docs/notebooks that call this script continue
to work. New code should use the CLI subcommand directly.
"""

from __future__ import annotations

import sys

from uxarray_mcp.cli import main as cli_main


def main() -> int:
    return cli_main(["doctor", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
