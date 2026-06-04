"""Update a conda-forge recipe version and source hash."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace(text: str, pattern: str, replacement: str) -> str:
    new_text = re.sub(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if new_text == text:
        raise RuntimeError(f"No replacement made for pattern: {pattern}")
    return new_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, default=Path("conda/recipe/meta.yaml"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    args = parser.parse_args()

    sha = _sha256(args.sdist)
    text = args.recipe.read_text()
    text = _replace(
        text,
        r'^{% set version = "[^"]+" %}$',
        f'{{% set version = "{args.version}" %}}',
    )
    text = _replace(text, r"^  sha256: [0-9a-f]+$", f"  sha256: {sha}")
    args.recipe.write_text(text)
    print(f"Updated {args.recipe} to version {args.version} with sha256 {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
