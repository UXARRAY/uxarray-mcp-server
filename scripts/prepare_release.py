"""Prepare version files for an automated release.

The script is intentionally small and dependency-free so it can run inside a
GitHub Actions release job before the package environment is installed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "uxarray_mcp" / "__init__.py"
CONDA_RECIPE = ROOT / "conda" / "recipe" / "meta.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
LOCKFILE = ROOT / "uv.lock"

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
        r'^\{%\s*set version = "[^"]+"\s*%\}$',
        f'{{% set version = "{version}" %}}',
    )


def stamp_changelog(text: str, version: str, today: str) -> str:
    """Close the `Unreleased` section under a heading for this release.

    Everything that was accumulating under `## Unreleased` becomes the notes
    for `version`, and an empty `## Unreleased` is left behind for the next
    cycle. Without this a tag ships with its own changes still filed as
    unreleased, so the published release has no notes and the next one
    inherits them.

    Idempotent: a changelog that already carries this version is returned
    unchanged, so a re-run of the release job cannot stack two headings.
    """
    if re.search(rf"^## {re.escape(version)} ", text, flags=re.MULTILINE):
        return text
    if not re.search(r"^## Unreleased\s*$", text, flags=re.MULTILINE):
        raise RuntimeError(
            "CHANGELOG.md has no '## Unreleased' heading to close; refusing to "
            "guess where the notes for this release begin."
        )
    return re.sub(
        r"^## Unreleased\s*$",
        f"## Unreleased\n\n## {version} — {today}",
        text,
        count=1,
        flags=re.MULTILINE,
    )


def _stamp_changelog_file(version: str) -> None:
    today = date_cls.today().isoformat()
    CHANGELOG.write_text(stamp_changelog(CHANGELOG.read_text(), version, today))


def _relock(version: str) -> None:
    """Bring `uv.lock` onto the new version, or say why it could not.

    The lockfile records the project's own version, so a bump leaves it
    describing the previous release. Nothing in CI passes `--locked`, so the
    mismatch is invisible here and surfaces for whoever checks out the tag and
    runs `uv sync --locked`. `uv` is not guaranteed to be on PATH at this
    point -- the script is meant to run before the environment exists -- so a
    missing binary is reported rather than fatal, and the workflow relocks in
    its own step once uv is installed.
    """
    if not LOCKFILE.exists():
        return
    try:
        subprocess.run(
            ["uv", "lock", "--offline"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("uv not on PATH; the workflow relocks uv.lock in a later step.")
    except subprocess.CalledProcessError as exc:
        print(f"uv lock failed, leaving uv.lock at its old version: {exc.stderr}")
    else:
        print(f"Relocked uv.lock at {version}.")


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
    _stamp_changelog_file(version)
    _relock(version)
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
