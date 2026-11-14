"""The surface clients receive: registry shape, schema bytes, MCP wire, CLI."""

from __future__ import annotations

import json

import pytest
from toolregistry_server.route_table import RouteTable

from tests.mcp_harness import connect, wire
from uxarray_mcp import __version__
from uxarray_mcp.server.app import make_registry
from uxarray_mcp.server.registry import TOOL_NAMES

#: Sent on every request; the old 33-tool surface was 36,271 bytes.
SPEC_BYTE_BUDGET = 16_000


@pytest.fixture(scope="module")
def routes():
    return RouteTable(make_registry()).list_routes()


def _spec(route) -> dict:
    return {
        "name": route.tool_name,
        "description": route.description,
        "parameters": route.parameters_schema,
    }


def test_exactly_the_documented_tools(routes):
    assert [r.tool_name for r in routes] == list(TOOL_NAMES)
    assert len(routes) == 13


def test_spec_stays_within_budget(routes):
    total = sum(len(json.dumps(_spec(r))) for r in routes)
    assert total <= SPEC_BYTE_BUDGET, f"{total} bytes"


def test_served_schema_is_trimmed(routes):
    for r in routes:
        props = r.parameters_schema.get("properties") or {}
        assert "toolcall_reason" not in props, r.tool_name
        assert not any("title" in v for v in props.values() if isinstance(v, dict)), (
            r.tool_name
        )
    plot = next(r for r in routes if r.tool_name == "plot")
    assert plot.parameters_schema["properties"]["title"]["type"] == "string"
    compute = next(r for r in routes if r.tool_name == "compute")
    assert (
        compute.parameters_schema["properties"]["lat_spec"]["anyOf"][1]["type"]
        == "array"
    )


def test_every_tool_has_a_description_that_names_its_choices(routes):
    for r in routes:
        assert r.description and len(r.description) > 40, r.tool_name


def test_tags_mark_writers_and_slow_tools():
    registry = make_registry()
    tags = {
        name: {t.value for t in registry.get_tool(name).metadata.tags}
        for name in TOOL_NAMES
    }
    assert "read_only" in tags["inspect_dataset"] and "read_only" not in tags["export"]
    assert "slow" in tags["remap"] and "slow" not in tags["list_datasets"]


async def test_mcp_wire_initialize_and_list_tools():
    async with connect() as (session, init):
        info = wire(init)
        assert info["serverInfo"]["name"] == "UXarray MCP"
        assert info["serverInfo"]["version"] == __version__
        listed = wire(await session.list_tools())
        names = [t["name"] for t in listed["tools"]]
        assert names == list(TOOL_NAMES)
        for tool in listed["tools"]:
            assert tool["inputSchema"]["type"] == "object"
            assert "readOnlyHint" in tool.get("annotations", {})


async def test_mcp_wire_call_returns_structured_result(state_dir):
    async with connect() as (session, _):
        res = wire(
            await session.call_tool(
                "compute",
                {
                    "statistic": "area",
                    "grid_path": "healpix:1",
                    "sphere_radius": 6371000.0,
                },
            )
        )
        assert not res.get("isError")
        payload = res.get("structuredContent") or json.loads(res["content"][0]["text"])
        assert payload["status"] == "complete" and payload["n_face"] == 48


async def test_mcp_wire_refusal_is_a_result_not_an_error(state_dir):
    async with connect() as (session, _):
        res = wire(
            await session.call_tool(
                "compute", {"statistic": "area", "grid_path": "healpix:1"}
            )
        )
        assert not res.get("isError")
        payload = res.get("structuredContent") or json.loads(res["content"][0]["text"])
        assert payload["outcome"] == "input_required"


async def test_mcp_wire_plot_returns_an_image(state_dir):
    async with connect() as (session, _):
        res = wire(
            await session.call_tool("plot", {"kind": "mesh", "grid_path": "healpix:1"})
        )
        types = [c["type"] for c in res["content"]]
        assert "image" in types and "text" in types


def test_openapi_exposes_every_tool_with_hints():
    from toolregistry_server.adapters.openapi.spec import build_openapi_schema

    spec = build_openapi_schema(RouteTable(make_registry()))
    paths = spec["paths"]
    assert {f"/tools/default/{n}" for n in TOOL_NAMES} <= set(paths)
    assert paths["/tools/default/export"]["post"]["x-read-only"] is False
    assert paths["/tools/default/inspect_dataset"]["post"]["x-read-only"] is True


def test_cli_parser_has_only_the_kept_commands():
    from uxarray_mcp.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    assert set(sub.choices) == {
        "serve",
        "openapi",
        "endpoints",
        "doctor",
        "install-claude",
    }
    assert parser.parse_args(["serve"]).transport == "stdio"


def test_cli_endpoints_list_without_config(capsys, tmp_path, monkeypatch):
    from uxarray_mcp.cli import main

    assert main(["endpoints", "list"]) == 0
    assert "No endpoints configured" in capsys.readouterr().out
