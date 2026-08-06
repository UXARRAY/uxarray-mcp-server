"""Guard the ``domain/`` boundary.

Pure computation in ``uxarray_mcp.domain`` must stay importable without any
server dependency installed. Two things depend on that property:

* Remote execution — ``AllCodeStrategies`` ships these functions to a Globus
  Compute worker that has ``uxarray`` but not ``toolregistry`` or ``mcp``.
* Portability — the server layer is a third-party dependency, so keeping the
  science free of it means a protocol change never reaches ``domain/``.

An accidental ``from toolregistry import ...`` in a domain module would only
surface as a worker-side ``ModuleNotFoundError`` at job runtime, which is an
expensive place to learn about it.
"""

from __future__ import annotations

import ast
import pkgutil
from pathlib import Path

import pytest

import uxarray_mcp.domain as domain_pkg

FORBIDDEN_ROOTS = {"toolregistry", "toolregistry_server", "mcp", "fastapi"}

DOMAIN_DIR = Path(domain_pkg.__file__).parent


def _domain_modules() -> list[Path]:
    return sorted(p for p in DOMAIN_DIR.glob("*.py") if p.name != "__pycache__")


def _imported_roots(tree: ast.AST) -> set[str]:
    """Collect top-level package names imported anywhere in the module."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Relative imports have no module root to check.
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("path", _domain_modules(), ids=lambda p: p.name)
def test_domain_module_has_no_server_imports(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = _imported_roots(tree) & FORBIDDEN_ROOTS
    assert not offenders, (
        f"{path.name} imports {sorted(offenders)}; domain/ must stay free of "
        "server and protocol dependencies so it can run on an HPC worker."
    )


def test_domain_package_is_non_empty() -> None:
    """Fail loudly if the glob above silently stops matching."""
    modules = [p for p in _domain_modules() if p.name != "__init__.py"]
    assert len(modules) >= 5, (
        f"expected the domain package to be populated, saw {modules}"
    )


def test_every_domain_submodule_is_covered() -> None:
    """Every importable submodule must be seen by the AST scan."""
    discovered = {name for _, name, _ in pkgutil.iter_modules([str(DOMAIN_DIR)])}
    scanned = {p.stem for p in _domain_modules()}
    missing = discovered - scanned
    assert not missing, (
        f"domain submodules not covered by the import guard: {sorted(missing)}"
    )
