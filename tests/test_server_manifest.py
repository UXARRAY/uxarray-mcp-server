"""``server.json``: the MCP registry listing.

The manifest is not imported, not installed and not exercised by the build,
so nothing else in this repository would notice it going stale. It is also
the first thing a prospective user reads, and it advertises a version and an
install command that have to be true.

The schema itself is fetched over the network by one test, which is skipped
offline; everything that can be checked without the network is checked
without it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "server.json"
SCHEMA_URL = (
    "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def _pyproject_field(name: str) -> str:
    import re

    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(rf'^{name} = "([^"]+)"$', text, re.MULTILINE)
    assert match, f"{name} not found in pyproject.toml"
    return match.group(1)


class TestTheManifestStaysTrue:
    def test_the_version_matches_the_package(self, manifest):
        """A listing advertising a version PyPI lacks is worse than none."""
        assert manifest["version"] == _pyproject_field("version")

    def test_the_pypi_package_version_matches_too(self, manifest):
        """The manifest carries the version twice; both have to move."""
        pypi = [p for p in manifest["packages"] if p.get("registryType") == "pypi"]
        assert pypi, "expected a pypi package entry"
        for package in pypi:
            assert package["version"] == _pyproject_field("version")

    def test_it_points_at_the_distribution_we_publish(self, manifest):
        identifiers = {p["identifier"] for p in manifest["packages"]}
        assert _pyproject_field("name") in identifiers

    def test_the_declared_entry_point_is_the_one_we_ship(self, manifest):
        """``uvx ... uxarray-mcp serve`` has to name a real console script."""
        pyproject = (ROOT / "pyproject.toml").read_text()
        assert "uxarray-mcp = " in pyproject

        args = [
            a.get("value")
            for p in manifest["packages"]
            for a in p.get("runtimeArguments", [])
        ]
        assert "uxarray-mcp" in args
        assert "serve" in args

    def test_the_advertised_profile_exists(self, manifest):
        """``--profile core`` must still be a profile the CLI accepts."""
        from uxarray_mcp.registry import Profile

        valid = set(getattr(Profile, "__args__", ()))
        advertised = [
            a.get("value")
            for p in manifest["packages"]
            for a in p.get("packageArguments", [])
            if a.get("name") == "--profile"
        ]
        assert advertised, "expected a --profile argument in the manifest"
        for value in advertised:
            assert value in valid, f"{value!r} is not one of {sorted(valid)}"

    def test_stdio_is_the_advertised_transport(self, manifest):
        """A desktop client spawns a subprocess; that is the stdio path."""
        transports = {p["transport"]["type"] for p in manifest["packages"]}
        assert transports == {"stdio"}


class TestTheManifestIsWellFormed:
    def test_the_required_fields_are_present(self, manifest):
        for field in ("name", "description", "version"):
            assert manifest.get(field), f"{field} is required by the schema"

    def test_the_description_fits_the_registry_limit(self, manifest):
        """The schema caps this at 100 characters; a long one is rejected."""
        assert 1 <= len(manifest["description"]) <= 100

    def test_the_name_is_namespaced_to_our_repository(self, manifest):
        assert manifest["name"] == "io.github.UXARRAY/uxarray-mcp-server"

    @pytest.mark.slow
    def test_it_validates_against_the_published_schema(self, manifest):
        """The real check, when the network allows it.

        Skipped rather than failed offline: a CI runner without egress should
        not turn a green suite red over a schema it cannot fetch.
        """
        import urllib.error
        import urllib.request

        jsonschema = pytest.importorskip("jsonschema")

        try:
            with urllib.request.urlopen(SCHEMA_URL, timeout=30) as response:
                schema = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover
            pytest.skip(f"cannot reach the MCP schema: {exc}")

        jsonschema.validate(manifest, schema)


class TestTheReleaseScriptMovesIt:
    def test_prepare_release_rewrites_both_versions(self, tmp_path, monkeypatch):
        """Without this the manifest silently keeps the previous release.

        ``server.json`` is not imported or installed, so a release that forgot
        it would publish a registry entry pointing at a version that does not
        exist yet -- and no other test would notice.
        """
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import prepare_release

        target = tmp_path / "server.json"
        target.write_text(
            json.dumps(
                {
                    "name": "io.github.UXARRAY/uxarray-mcp-server",
                    "version": "1.0.0",
                    "packages": [
                        {
                            "registryType": "pypi",
                            "identifier": "uxarray-mcp",
                            "version": "1.0.0",
                        },
                        {
                            "registryType": "oci",
                            "identifier": "other",
                            "version": "keep-me",
                        },
                    ],
                },
                indent=2,
            )
        )
        monkeypatch.setattr(prepare_release, "SERVER_JSON", target)

        prepare_release._write_server_json_version("2026.12.0")

        written = json.loads(target.read_text())
        assert written["version"] == "2026.12.0"
        assert written["packages"][0]["version"] == "2026.12.0"
        # Only the PyPI entry is ours to move.
        assert written["packages"][1]["version"] == "keep-me"
