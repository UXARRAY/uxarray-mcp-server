"""core/ must import on a worker that has only uxarray installed."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / "src" / "uxarray_mcp" / "core"
FORBIDDEN = (
    "mcp",
    "toolregistry",
    "pydantic",
    "uxarray_mcp.server",
    "uxarray_mcp.remote",
)


def test_core_imports_with_server_packages_blocked():
    modules = sorted(p.stem for p in CORE.glob("*.py") if p.stem != "__init__")
    imports = "\n".join(f"import uxarray_mcp.core.{m}" for m in modules)
    script = (
        textwrap.dedent(
            """
        import sys

        class Block:
            def find_spec(self, name, path=None, target=None):
                root = name.split(".")[0]
                if root in {"mcp", "toolregistry", "pydantic"} or name.startswith(
                    ("uxarray_mcp.server", "uxarray_mcp.remote")
                ):
                    raise ImportError("blocked: " + name)

        sys.meta_path.insert(0, Block())
        import uxarray_mcp
        from uxarray_mcp.core import ops
        """
        )
        + imports
        + "\nprint(len(ops.OPS))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert out.returncode == 0, out.stderr[-2000:]
    assert int(out.stdout.strip()) >= 25


def test_no_core_file_mentions_a_server_module():
    for path in CORE.glob("*.py"):
        text = path.read_text()
        for name in FORBIDDEN:
            assert f"import {name}" not in text and f"from {name}" not in text, (
                f"{path.name} imports {name}"
            )
