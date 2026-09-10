"""Parse every configuration snippet the docs tell a new user to paste.

A snippet is the first thing a new user runs and the last thing anyone
tests. `docs/operating-an-endpoint.md` carried an `authentication_policy`
block shaped as a nested mapping for months; the field is typed
``UUID | str | None``, so the endpoint refused to start with two pydantic
errors and the user had no way to tell our mistake from theirs. Nothing in
the suite read that block, because nothing in the suite read any block.

These tests read them. They cannot check semantics the docs never state,
but they can check that what we publish parses, and that the keys whose
shape we have gotten wrong before still have the shape they need.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_FILES = sorted((REPO_ROOT / "docs").glob("*.md")) + [REPO_ROOT / "README.md"]

# A fenced block, with its language tag and its 1-based starting line.
_FENCE = re.compile(r"^```([A-Za-z0-9_+-]*)\s*$")

# Placeholders are the point of a snippet: `<your-uuid>` says "put yours
# here" more clearly than a plausible-looking fake would. They are not
# valid values, so a snippet carrying one is parsed and then excused from
# any check on what the value means.
_PLACEHOLDER = re.compile(r"<[^>]+>")


def _fenced_blocks(path: Path, language: str) -> list[tuple[int, str]]:
    """Return ``(line_number, body)`` for each fenced block in one language."""
    blocks: list[tuple[int, str]] = []
    inside: list[str] | None = None
    start = 0
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        match = _FENCE.match(line)
        if inside is None:
            if match and match.group(1).lower() == language:
                inside, start = [], lineno + 1
            continue
        if line.strip() == "```":
            blocks.append((start, "\n".join(inside)))
            inside = None
            continue
        inside.append(line)
    return blocks


def _all_blocks(language: str) -> list[tuple[Path, int, str]]:
    return [
        (path, lineno, body)
        for path in DOC_FILES
        if path.exists()
        for lineno, body in _fenced_blocks(path, language)
    ]


def test_every_documented_yaml_block_parses():
    """A snippet that is not YAML is not a snippet, it is a trap."""
    failures = []
    for path, lineno, body in _all_blocks("yaml"):
        if _PLACEHOLDER.search(body):
            # A placeholder inside a value is still valid YAML; one used as
            # a whole key or a flow sequence is not, and that is a doc
            # convention rather than an error. Parse it, and only report a
            # failure the placeholder cannot explain.
            try:
                yaml.safe_load(body)
            except yaml.YAMLError:
                continue
            continue
        try:
            yaml.safe_load(body)
        except yaml.YAMLError as exc:
            failures.append(f"{path.name}:{lineno}: {exc}")
    assert not failures, "documented YAML that does not parse:\n" + "\n".join(failures)


def test_every_documented_json_block_parses():
    """Client config blocks are pasted verbatim into a real config file."""
    failures = []
    for path, lineno, body in _all_blocks("json"):
        if _PLACEHOLDER.search(body):
            continue
        try:
            json.loads(body)
        except json.JSONDecodeError:
            # Some blocks quote one field of a larger response rather than a
            # whole document -- `"execution_venue": "hpc:ucar"` is clearer
            # than the object around it. Accept a fragment that completes to
            # an object, and nothing looser than that.
            try:
                json.loads("{" + body + "}")
            except json.JSONDecodeError as exc:
                failures.append(f"{path.name}:{lineno}: {exc}")
    assert not failures, "documented JSON that does not parse:\n" + "\n".join(failures)


# Endpoint config keys that Globus Compute's ``BaseConfig`` declares as a
# scalar. Writing any of them as a mapping is the failure this module was
# added for: the endpoint refuses to start and names pydantic, not us.
#
# ``authentication_policy`` is the UUID of a policy created in Globus Auth.
# The identity and domain restrictions people reach for live inside that
# policy object, which is exactly why the mapping looked plausible.
_SCALAR_ENDPOINT_KEYS = {
    "authentication_policy": (str,),
    "subscription_id": (str,),
    "high_assurance": (bool,),
    "display_name": (str, type(None)),
}


def test_endpoint_config_keys_are_documented_as_scalars():
    """The shape the endpoint daemon accepts, not the one that reads well."""
    failures = []
    for path, lineno, body in _all_blocks("yaml"):
        try:
            parsed = yaml.safe_load(body)
        except yaml.YAMLError:
            continue  # reported by the parse test, not here
        if not isinstance(parsed, dict):
            continue
        for key, allowed in _SCALAR_ENDPOINT_KEYS.items():
            if key not in parsed:
                continue
            value = parsed[key]
            if isinstance(value, str) and _PLACEHOLDER.search(value):
                continue
            if not isinstance(value, allowed):
                names = " or ".join(t.__name__ for t in allowed)
                failures.append(
                    f"{path.name}:{lineno}: {key} documented as "
                    f"{type(value).__name__}, must be {names}"
                )
    assert not failures, (
        "endpoint config documented in a shape the daemon rejects:\n"
        + "\n".join(failures)
    )


def test_documented_client_config_paths_match_the_code():
    """The path the docs name is the path the loader actually reads.

    Two files in this project are called ``config.yaml`` and a user who
    edits the wrong one gets no error, just an endpoint the client never
    finds. The docs name one of them; this pins that name to the constant.
    """
    from uxarray_mcp.remote.config import USER_CONFIG_PATH

    documented = "~/.config/uxarray-mcp/config.yaml"
    assert str(USER_CONFIG_PATH).endswith(documented.lstrip("~/")), (
        f"docs tell users to edit {documented}, loader reads {USER_CONFIG_PATH}"
    )

    readme = (REPO_ROOT / "README.md").read_text()
    assert documented in readme, (
        "the client config path is not named in README.md, so a user has "
        "nowhere to put the endpoint UUID they were told to save"
    )


@pytest.mark.parametrize(
    "snippet",
    [
        '{"mcpServers": {"uxarray": {"command": "uxarray-mcp", "args": ["serve"]}}}',
        '{"mcp": {"uxarray": {"type": "local", '
        '"command": ["uxarray-mcp", "serve"], "enabled": true}}}',
    ],
    ids=["claude-cursor", "opencode"],
)
def test_client_snippets_invoke_the_installed_entry_point(snippet):
    """Every client block launches the console script this package declares.

    The clients disagree about where the command goes -- a string under
    ``command`` for Claude and Cursor, the head of a ``command`` list for
    opencode -- and a snippet naming a module path or a stale script name
    would fail only on a user's machine.
    """
    from importlib.metadata import entry_points

    scripts = {ep.name for ep in entry_points(group="console_scripts")}
    assert "uxarray-mcp" in scripts, "the console script is not installed"

    config = json.loads(snippet)
    entry = next(iter(next(iter(config.values())).values()))
    command = entry["command"]
    argv = command if isinstance(command, list) else [command, *entry["args"]]
    assert argv[0] == "uxarray-mcp"
    assert argv[1] == "serve"
