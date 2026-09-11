"""Prepare version files for an automated release.

The script is intentionally small and dependency-free so it can run inside a
GitHub Actions release job before the package environment is installed.

Versions mirror upstream `uxarray`'s `year.month` and own the patch, so a
release says which upstream month it was built against without a second
lookup. The same call moves both ends of the uxarray pin, because a floor
raised without its ceiling is a package that cannot be installed beside the
next upstream month.
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

UPSTREAM_PACKAGE = "uxarray"
UPSTREAM_PYPI_URL = f"https://pypi.org/pypi/{UPSTREAM_PACKAGE}/json"

# The one line in pyproject.toml that pins upstream. Matched as a whole entry
# so the rewrite cannot land inside a different dependency that happens to
# contain the same substring.
UXARRAY_PIN_RE = re.compile(r'^(?P<indent>[ \t]*)"uxarray[^"]*",$', re.MULTILINE)


def _run(args: list[str]) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def _parse_version(version: str) -> tuple[int, int, int]:
    """Split `X.Y.Z` into integers, refusing anything PEP 440 would rewrite.

    Zero padding is rejected loudly rather than normalized. Upstream tags
    `v2026.09.0`, but PEP 440 strips the leading zero, so a dist built from a
    padded version publishes as `2026.9.0` and disagrees with its own git tag.
    Copying upstream's padding into our version files would reproduce that
    mismatch in a repository that has no reason to inherit it.
    """
    match = VERSION_RE.match(version)
    if not match:
        raise ValueError(f"Automated releases require X.Y.Z versions, got {version!r}")
    parts = match.groups()
    padded = [part for part in parts if len(part) > 1 and part.startswith("0")]
    if padded:
        unpadded = ".".join(str(int(part)) for part in parts)
        raise ValueError(
            f"Zero-padded component in {version!r}: PEP 440 strips the zero, so "
            f"this would publish as {unpadded} and disagree with tag v{version}. "
            f"Use {unpadded}."
        )
    year, month, patch = (int(part) for part in parts)
    return year, month, patch


def _fetch_pypi_json(url: str) -> dict:
    import json
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        return json.load(response)


def _latest_upstream(fetch=_fetch_pypi_json) -> str | None:
    """Newest published `uxarray`, read from PyPI rather than upstream's tags.

    Upstream's tags mix `v2026.09.0` and `v2026.4.0`; PyPI normalizes both, so
    it is the only source that answers "which month is upstream on" without a
    second parser for the padding. Releases whose files are all yanked are
    skipped, and anything that is not a plain `X.Y.Z` -- a prerelease, a
    post-release -- is not a month we mirror.

    Returns `None` when PyPI cannot be reached: an unreachable index must not
    decide a version number, so the caller falls back to a patch bump.
    """
    try:
        payload = fetch(UPSTREAM_PYPI_URL)
    except Exception as exc:  # network, JSON, HTTP -- all mean "do not know"
        print(f"Could not read {UPSTREAM_PACKAGE} from PyPI: {exc}")
        return None
    candidates: list[tuple[int, int, int]] = []
    for raw, files in (payload.get("releases") or {}).items():
        match = VERSION_RE.match(raw)
        if not match:
            continue
        if files and all(file.get("yanked") for file in files):
            continue
        candidates.append(tuple(int(part) for part in match.groups()))
    if not candidates:
        newest = (payload.get("info") or {}).get("version")
        if not newest or not VERSION_RE.match(newest):
            return None
        candidates.append(
            tuple(int(part) for part in VERSION_RE.match(newest).groups())
        )
    year, month, patch = max(candidates)
    return f"{year}.{month}.{patch}"


def _next_version(base: str, upstream: str) -> str:
    """Mirror upstream's `year.month`; own the patch.

    Same month as the version we last shipped means this is our second release
    within upstream's month, so only our patch moves. A month upstream has not
    had before resets the patch to 0. A `base` that predates the scheme --
    `0.3.1` -- simply never matches, so the first CalVer release lands on
    upstream's month with patch 0.
    """
    up_year, up_month, _ = _parse_version(upstream)
    base_year, base_month, base_patch = _parse_version(base)
    if (base_year, base_month) == (up_year, up_month):
        return f"{up_year}.{up_month}.{base_patch + 1}"
    return f"{up_year}.{up_month}.0"


def _uxarray_pin(upstream: str) -> str:
    """The pin a release against `upstream` should carry, both ends moved."""
    year, month, _ = _parse_version(upstream)
    ceiling = f"{year + 1}.1" if month == 12 else f"{year}.{month + 1}"
    return f"uxarray>={upstream},<{ceiling}"


def _current_uxarray_floor() -> str | None:
    match = re.search(r'"uxarray>=([^",<]+)', PYPROJECT.read_text())
    return match.group(1) if match else None


def _write_uxarray_pin(upstream: str) -> None:
    """Move the floor and the ceiling together.

    A release that raises only the floor is uninstallable alongside the next
    upstream month, because the ceiling it kept was written for the month
    before. The two ends are one decision, so they are one edit.
    """
    text = PYPROJECT.read_text()
    matches = UXARRAY_PIN_RE.findall(text)
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one uxarray dependency line in pyproject.toml, "
            f"found {len(matches)}; refusing to guess which one pins upstream."
        )
    pin = _uxarray_pin(upstream)
    PYPROJECT.write_text(UXARRAY_PIN_RE.sub(f'\\g<indent>"{pin}",', text, count=1))


def _latest_tag() -> str | None:
    tags = _run(["git", "tag", "--list", "v[0-9]*", "--sort=-v:refname"])
    return tags.splitlines()[0] if tags else None


def _current_version() -> str:
    match = re.search(r'^version = "([^"]+)"$', PYPROJECT.read_text(), re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find project version in pyproject.toml")
    return match.group(1)


def _bump_patch(version: str) -> str:
    major, minor, patch = _parse_version(version)
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
    parser.add_argument(
        "--upstream",
        default=None,
        help=f"Upstream {UPSTREAM_PACKAGE} version to mirror. Default: read PyPI.",
    )
    parser.add_argument(
        "--no-upstream",
        action="store_true",
        help="Ignore upstream entirely and patch-bump the latest tag.",
    )
    args = parser.parse_args()

    latest_tag = _latest_tag()
    commits = _commits_since(latest_tag)
    current = _current_version()

    if args.no_upstream:
        upstream = None
    else:
        upstream = args.upstream or _latest_upstream()

    floor = _current_uxarray_floor()
    upstream_is_new = bool(
        upstream and floor and _parse_version(upstream) > _parse_version(floor)
    )

    if commits == 0 and not args.force and not upstream_is_new:
        _github_output(
            release_needed="false",
            previous_tag=latest_tag or "",
            changed_commits=commits,
            version=current,
            tag=f"v{current}",
            upstream=upstream or "",
            upstream_is_new="false",
        )
        return 0

    if args.version:
        version = args.version
    elif upstream:
        version = _next_version(
            latest_tag.removeprefix("v") if latest_tag else current, upstream
        )
    elif latest_tag is None:
        version = current
    else:
        version = _bump_patch(latest_tag.removeprefix("v"))

    _parse_version(version)

    _write_version(version)
    if upstream:
        _write_uxarray_pin(upstream)
    _stamp_changelog_file(version)
    _relock(version)
    _github_output(
        release_needed="true",
        previous_tag=latest_tag or "",
        changed_commits=commits,
        version=version,
        tag=f"v{version}",
        upstream=upstream or "",
        upstream_is_new=str(upstream_is_new).lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
