"""MCP typed results: outputSchema, resource_link, tools/list cache hints (#103)."""

from __future__ import annotations

import json

import pytest

from uxarray_mcp.app import (
    LIST_TOOLS_CACHE_SCOPE,
    LIST_TOOLS_TTL_MS,
    make_mcp_server,
    make_registry,
)
from uxarray_mcp.response_contract import (
    available_contracts,
    describe_response_contract,
)
from uxarray_mcp.typed_results import (
    INLINE_PAYLOAD_LIMIT_BYTES,
    declared_output_schemas,
    make_resource_link,
    output_schema_for,
    should_link_rather_than_inline,
    spill_png,
)


def _adapter_forwards_output_schema() -> bool:
    """Whether the installed adapter carries our schema through to a route.

    We publish the schema either way; only the hand-off to the MCP layer needs
    adapter support, which is not in the released version yet.
    """
    from toolregistry_server.route_table import RouteEntry

    return "output_schema" in getattr(RouteEntry, "__dataclass_fields__", {})


needs_schema_adapter = pytest.mark.skipif(
    not _adapter_forwards_output_schema(),
    reason="installed toolregistry-server does not forward output_schema yet",
)


class TestOutputSchema:
    def test_every_declared_contract_compiles(self):
        for operation in available_contracts():
            schema = output_schema_for(operation)
            assert schema is not None, operation
            assert schema["type"] == "object"
            # Additive by construction: a tool may grow fields without
            # breaking a client that validated against an older schema.
            assert schema["additionalProperties"] is True

    def test_undeclared_operation_returns_none_not_empty_schema(self):
        # "We never described this" and "this has no required fields" are
        # different claims and must not be conflated.
        assert output_schema_for("no_such_operation") is None

    def test_schema_matches_the_prose_contract(self):
        # One source of truth: the schema is compiled from the same table
        # describe_response_contract serves, so the two cannot drift.
        for operation in available_contracts():
            contract = describe_response_contract(operation)
            schema = output_schema_for(operation)
            for field in contract["fields"]:
                assert field["name"] in schema["properties"], (operation, field)
            assert set(schema["required"]) == set(contract["required"])

    def test_optional_fields_accept_null(self):
        # An honest abstention (units we refuse to invent) must validate.
        schema = output_schema_for("calculate_area")
        assert schema["properties"]["area_units"]["type"] == ["string", "null"]
        assert schema["properties"]["total_area"]["type"] == "number"

    def test_provenance_is_declared_on_every_schema(self):
        for operation, schema in declared_output_schemas().items():
            assert "_provenance" in schema["properties"], operation

    def test_aliases_resolve_to_the_same_schema(self):
        assert output_schema_for("area") == output_schema_for("calculate_area")

    def test_schemas_are_json_serializable(self):
        # They travel over the wire in tools/list.
        json.dumps(declared_output_schemas())


class TestAnalysisEnvelope:
    """The front-door envelope is the paper's result contract as a schema.

    The envelope belongs to ``run_analysis``: that is the tool that
    returns a ``outcome`` and can refuse with ``input_required``.
    ``analyze_dataset`` runs a multi-stage summary and has no such field,
    so it must not advertise this shape.
    """

    def test_refusal_is_advertised_as_a_reachable_shape(self):
        schema = output_schema_for("run_analysis")
        outcome = schema["properties"]["outcome"]
        assert set(outcome["enum"]) == {"complete", "input_required"}
        assert schema["required"] == ["outcome"]

    def test_contract_blocks_are_all_declared(self):
        props = output_schema_for("run_analysis")["properties"]
        for block in (
            "scientific_status",
            "preconditions",
            "postconditions",
            "_provenance",
        ):
            assert block in props

    def test_not_evaluated_is_distinct_from_failed(self):
        # #84: "we did not check" must not read as "the check passed".
        pre = output_schema_for("run_analysis")["properties"]["preconditions"]
        assert set(pre["properties"]["status"]["enum"]) == {
            "satisfied",
            "failed",
            "not_evaluated",
        }

    def test_interpretability_is_nullable(self):
        status = output_schema_for("run_analysis")["properties"]["scientific_status"]
        assert status["properties"]["physically_interpretable"]["type"] == [
            "boolean",
            "null",
        ]


class TestRegistryPublishesSchemas:
    @pytest.mark.parametrize("profile", ["core", "deferred-full"])
    def test_schema_reaches_tool_metadata(self, profile):
        registry = make_registry(profile=profile)
        published = {
            name
            for name in registry.list_tools()
            if "output_schema"
            in (getattr(registry.get_tool(name).metadata, "extra", None) or {})
        }
        assert "run_analysis" in published

    @pytest.mark.parametrize("profile", ["core", "deferred-full"])
    def test_multi_stage_summary_does_not_claim_the_envelope(self, profile):
        # analyze_dataset returns a stage summary, not a outcome
        # envelope. Declaring one made the server reject its own output as
        # invalid structured content the moment a client called it.
        registry = make_registry(profile=profile)
        extra = getattr(registry.get_tool("analyze_dataset").metadata, "extra", None)
        assert "output_schema" not in (extra or {})

    def test_deferred_profile_publishes_the_compute_tools(self):
        registry = make_registry(profile="deferred-full")
        published = {
            name
            for name in registry.list_tools()
            if "output_schema"
            in (getattr(registry.get_tool(name).metadata, "extra", None) or {})
        }
        assert "compute-calculate_area" in published
        assert "compute-calculate_zonal_mean" in published

    @needs_schema_adapter
    def test_schema_survives_the_route_table(self):
        from toolregistry_server.route_table import RouteTable

        table = RouteTable(make_registry(profile="core"))
        route = table.get_route("run_analysis")
        assert route.output_schema is not None
        assert "outcome" in route.output_schema["properties"]

    @needs_schema_adapter
    def test_tools_without_a_declared_shape_stay_silent(self):
        # Advertising a shape we have not committed to is worse than none.
        from toolregistry_server.route_table import RouteTable

        table = RouteTable(make_registry(profile="core"))
        assert table.get_route("get_capabilities").output_schema is None


class TestResourceLinks:
    def test_link_carries_uri_and_name_only_when_unspecified(self):
        link = make_resource_link("file:///tmp/a.png", "a.png")
        assert link == {"uri": "file:///tmp/a.png", "name": "a.png"}

    def test_optional_members_are_included_when_given(self):
        link = make_resource_link(
            "file:///tmp/a.png", "a.png", mime_type="image/png", size=10
        )
        assert link["mime_type"] == "image/png"
        assert link["size"] == 10

    def test_threshold_is_a_boundary_not_a_range(self):
        assert not should_link_rather_than_inline(INLINE_PAYLOAD_LIMIT_BYTES - 1)
        assert should_link_rather_than_inline(INLINE_PAYLOAD_LIMIT_BYTES)

    def test_small_png_stays_inline(self):
        assert spill_png(b"x" * 1024, plot_type="mesh") is None

    def test_large_png_is_written_and_linked(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UXARRAY_MCP_STATE_DIR", str(tmp_path))
        payload = b"x" * (INLINE_PAYLOAD_LIMIT_BYTES + 1)
        link = spill_png(payload, plot_type="mesh")
        assert link is not None
        assert link["mime_type"] == "image/png"
        assert link["size"] == len(payload)
        assert link["uri"].startswith("file://")
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        written = url2pathname(urlparse(link["uri"]).path)
        with open(written, "rb") as handle:
            assert handle.read() == payload

    def test_spill_degrades_to_inline_when_store_unwritable(self, monkeypatch):
        # Failing to spill must never fail the call: inlining is still correct.
        from uxarray_mcp import state

        monkeypatch.setattr(
            state, "_artifacts_dir", lambda: (_ for _ in ()).throw(OSError("read-only"))
        )
        assert spill_png(b"x" * (INLINE_PAYLOAD_LIMIT_BYTES + 1), plot_type="m") is None


class TestListToolsCacheHints:
    def test_server_builds_with_cache_hints(self):
        assert make_mcp_server(profile="core") is not None

    def test_the_handler_actually_emits_the_hints(self):
        # Asserting the constants only proves we chose a number. This calls
        # the registered tools/list handler and checks the hints are on the
        # result -- and that they are in `model_fields_set`, because the SDK
        # overwrites any field the handler did not explicitly set.
        import asyncio

        server = make_mcp_server(profile="core")
        handlers = getattr(server, "_request_handlers", None)
        entry = (handlers or {}).get("tools/list")
        if entry is None:  # pragma: no cover - SDK internals moved
            pytest.skip("SDK exposes no tools/list handler to call")

        result = asyncio.run(entry.handler(None, None))
        assert result.ttl_ms == LIST_TOOLS_TTL_MS
        assert result.cache_scope == LIST_TOOLS_CACHE_SCOPE
        assert {"ttl_ms", "cache_scope"} <= result.model_fields_set

    def test_ttl_is_bounded_and_scope_is_shared(self):
        # The surface is fixed by the profile at startup, so a shared entry
        # is correct; the TTL bounds staleness if that ever changes.
        assert 0 < LIST_TOOLS_TTL_MS <= 600_000
        assert LIST_TOOLS_CACHE_SCOPE in {"public", "private"}


class TestDeclaredShapeMatchesRealOutput:
    """A declared schema is a promise; these check we actually keep it."""

    def test_contracted_results_carry_the_operation_they_declare(self):
        # Every contract-derived schema requires `operation`, but nothing
        # emitted it, so a validating client saw a malformed envelope on
        # results that were in fact fine.
        from uxarray_mcp.provenance import attach_provenance

        result = attach_provenance({}, tool="inspect_mesh", inputs={})
        assert result["operation"] == "inspect_mesh"

    def test_uncontracted_results_do_not_invent_one(self):
        from uxarray_mcp.provenance import attach_provenance

        result = attach_provenance({}, tool="get_capabilities", inputs={})
        assert "operation" not in result

    def test_run_analysis_output_validates_against_its_own_schema(self):
        jsonschema = pytest.importorskip("jsonschema")

        jsonschema.validate(
            {
                "outcome": "complete",
                "scientific_status": {"physically_interpretable": None},
                "preconditions": {"status": "not_evaluated"},
                "postconditions": {"status": "not_evaluated"},
                "_provenance": {},
            },
            output_schema_for("run_analysis"),
        )


class TestEveryResultValidatesAgainstItsPublishedSchema:
    """Run the real operations and hold each answer to its own promise.

    The hand-built dict above proves the schema is well formed; it cannot
    prove we honour it, because the fixture and the schema were written to
    match. These drive the actual front door and validate whatever comes
    back. That is the only version of this check that catches drift -- and
    drift is not hypothetical: every contract-derived schema required
    ``operation`` for a release while nothing emitted it, so results that
    were scientifically correct failed their own published envelope.
    """

    def _validate(self, result, operation="run_analysis"):
        import jsonschema

        schema = output_schema_for(operation)
        assert schema is not None, f"{operation} publishes no outputSchema"
        jsonschema.validate(result, schema)
        return result

    @pytest.fixture(autouse=True)
    def _needs_jsonschema(self):
        pytest.importorskip("jsonschema")

    def test_a_completed_analysis_carries_its_own_interpretation(
        self, synthetic_mesh_with_data
    ):
        from uxarray_mcp.tools.frontdoor import run_analysis

        grid_file, data_file = synthetic_mesh_with_data
        result = run_analysis(
            "calculate_area", grid_path=grid_file, data_path=data_file
        )

        self._validate(result)
        assert result["outcome"] == "complete"
        # The branch condition is the point: a number never travels without
        # the judgment of whether it means anything.
        assert "physically_interpretable" in result["scientific_status"]

    def test_a_refusal_carries_the_repair_that_would_lift_it(
        self, synthetic_mesh_with_data
    ):
        from uxarray_mcp.tools.frontdoor import run_analysis

        grid_file, data_file = synthetic_mesh_with_data
        result = run_analysis(
            "curl",
            grid_path=grid_file,
            data_path=data_file,
            u_variable="temperature",
            v_variable="pressure",
            scale_by_radius=False,
        )

        self._validate(result)
        assert result["outcome"] == "input_required"
        assert result["refusal"]["repairs"]

    @pytest.mark.parametrize(
        "operation, kwargs",
        [
            ("inspect_mesh", {}),
            ("validate_dataset", {}),
            ("calculate_area", {}),
            ("inspect_variable", {"variable_name": "temperature"}),
        ],
    )
    def test_each_operation_keeps_the_envelope_it_publishes(
        self, synthetic_mesh_with_data, operation, kwargs
    ):
        from uxarray_mcp.tools.frontdoor import run_analysis

        grid_file, data_file = synthetic_mesh_with_data
        result = run_analysis(
            operation, grid_path=grid_file, data_path=data_file, **kwargs
        )

        self._validate(result)

    def test_a_comparison_keeps_the_envelope_too(self, comparison_mesh_with_data):
        from uxarray_mcp.tools.frontdoor import run_analysis

        grid_file, data_a, data_b = comparison_mesh_with_data
        result = run_analysis(
            "bias",
            grid_path=grid_file,
            data_path_a=data_a,
            data_path_b=data_b,
            variable_name="temperature",
        )

        self._validate(result)

    def test_a_complete_result_missing_its_status_is_rejected(self):
        """The schema must actually fail the shape it exists to forbid.

        A conformance suite that only feeds it valid results proves nothing
        about what it rejects, and a branch condition that accidentally
        matched no result would pass every test above.
        """
        import jsonschema

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"outcome": "complete", "_provenance": {}},
                output_schema_for("run_analysis"),
            )

    def test_a_refusal_without_a_repair_path_is_rejected(self):
        import jsonschema

        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(
                {"outcome": "input_required"},
                output_schema_for("run_analysis"),
            )


class TestPlotContentBlocks:
    """Plot results must stay real content blocks, inline or linked."""

    def _contents(self, png_b64, **extra):
        from uxarray_mcp.tools.remote_tools import _plot_result_to_mcp_contents

        return _plot_result_to_mcp_contents({"png_b64": png_b64, **extra})

    def test_small_figure_is_an_inline_image(self):
        blocks = self._contents("aGk=")
        assert [b["type"] for b in blocks] == ["image", "text"]
        assert blocks[0]["source"]["data"] == "aGk="
        assert blocks[0]["source"]["media_type"] == "image/png"

    def test_spilled_figure_becomes_a_resource_link(self):
        # A spilled plot has no bytes to inline. Building an image block
        # from the missing payload failed validation outright, so the
        # largest meshes -- the ones worth spilling -- returned an error.
        blocks = self._contents(
            None, image_uri="file:///tmp/plot_abc.png", image_size_bytes=999
        )
        assert [b["type"] for b in blocks] == ["resource_link", "text"]
        assert blocks[0]["uri"] == "file:///tmp/plot_abc.png"
        assert blocks[0]["name"] == "plot_abc.png"

    def test_metadata_survives_either_delivery(self):
        for b64, extra in (("aGk=", {}), (None, {"image_uri": "file:///t/p.png"})):
            text = self._contents(b64, grid_info={"n_face": 8}, **extra)[-1]
            assert json.loads(text["text"])["grid_info"] == {"n_face": 8}
            assert "png_b64" not in json.loads(text["text"])

    def test_no_bytes_and_no_uri_still_returns_metadata(self):
        blocks = self._contents(None)
        assert [b["type"] for b in blocks] == ["text"]

    def test_blocks_survive_the_adapter_gate(self):
        # The regression this guards: pydantic ``mcp.types`` models fail the
        # adapter's dict-only check, so a figure reached the client as a JSON
        # array of Python repr() strings instead of an image. Assert against
        # the adapter itself rather than our own idea of the wire shape.
        from toolregistry.llm.content_blocks import is_content_block_list

        assert is_content_block_list(self._contents("aGk="))
        assert is_content_block_list(
            self._contents(None, image_uri="file:///tmp/plot_abc.png")
        )

    def test_adapter_keeps_the_image_as_its_own_block(self):
        adapter = pytest.importorskip("toolregistry_server.adapters.mcp.adapter")
        to_content = getattr(adapter, "_result_to_mcp_content", None)
        if to_content is None:  # pragma: no cover - adapter internals moved
            pytest.skip("adapter has no _result_to_mcp_content")

        contents = to_content(self._contents("aGk="))
        assert [type(c).__name__ for c in contents] == ["ImageContent", "TextContent"]
