"""Prepare version files for an automated release.

The script is intentionally small and dependency-free so it can run inside a
GitHub Actions release job before the package environment is installed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "uxarray_mcp" / "__init__.py"
CONDA_RECIPE = ROOT / "conda" / "recipe" / "meta.yaml"

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _run(args: list[str]) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def _latest_tag() -> str | None:
    tags = _run(["git", "tag", "--list", "v[0-9]*", "--sort=-v:refname"])
    return tags.splitlines()[0] if tags else None


def _current_version() -> str:
    match = re.search(r'^version = "([^"]+)"$', PYPROJECT.read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find project version in pyproject.toml")
    return match.group(1)


def _bump_patch(version: str) -> str:
    match = VERSION_RE.match(version)
    if not match:
        raise ValueError(f"Automated releases require X.Y.Z versions, got {version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def _commits_since(tag: str | None) -> int:
    if tag is None:
        return int(_run(["git", "rev-list", "--count", "HEAD"]))
    return int(_run(["git", "rev-list", "--count", f"{tag}..HEAD"]))


def _replace(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text()
    new_text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
    path.write_text(new_text)


def _write_version(version: str) -> None:
    _replace(PYPROJECT, r'^version = "[^"]+"$', f'version = "{version}"')
    _replace(INIT, r'^__version__ = "[^"]+"$', f'__version__ = "{version}"')
    _replace(
        CONDA_RECIPE,
        r'^{% set version = "[^"]+" %}$',
        f'{{% set version = "{version}" %}}',
    )


def _github_output(**values: str | int | bool | None) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    lines = [f"{key}={value}" for key, value in values.items()]
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=None, help="Explicit version to release")
    parser.add_argument(
        "--force", action="store_true", help="Release even with no changes"
    )
    args = parser.parse_args()

    latest_tag = _latest_tag()
    commits = _commits_since(latest_tag)
    current = _current_version()

    if commits == 0 and not args.force:
        _github_output(
            release_needed="false",
            previous_tag=latest_tag or "",
            changed_commits=commits,
            version=current,
            tag=f"v{current}",
        )
        return 0

    if args.version:
        version = args.version
    elif latest_tag is None:
        version = current
    else:
        version = _bump_patch(latest_tag.removeprefix("v"))

    if not VERSION_RE.match(version):
        raise ValueError(f"Invalid release version {version!r}; expected X.Y.Z")

    _write_version(version)
    _github_output(
        release_needed="true",
        previous_tag=latest_tag or "",
        changed_commits=commits,
        version=version,
        tag=f"v{version}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
