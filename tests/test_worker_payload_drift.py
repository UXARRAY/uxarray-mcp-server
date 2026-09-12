"""The inlined worker copies must stay identical to each other.

``remote/compute_functions.py:12-17`` explains why the duplication is there:
Globus Compute ships each function's source, the worker has no ``uxarray_mcp``
to import from, and closures over module helpers do not survive serialization.
So the same few blocks are hand-copied into every remote function, and the
comment ends "If you change one, change them all" -- which nothing enforced.

These tests enforce it by comparing the copies against each other, normalized
for the names that legitimately differ -- whether the path parameter is called
``file_path``, ``grid_path`` or ``gp``. They do not deduplicate anything, and
they must not: removing a copy breaks the wire contract.

What is compared is chosen per block, because the copies are not textually
interchangeable and demanding that they were would only invite someone to
delete the test. The surrounding dispatch has real structural variety -- some
copies also derive ``grid_format``, some ``return`` from a nested helper --
so what is pinned is the zoom argument inside it, the branch kinds it offers,
and the key list of the runtime envelope. Each is a thing that going wrong
changes an answer.

Where a domain twin exists under ``domain/``, the local implementation is the
reference and the drift that matters is local-versus-remote, not copy-versus-
copy. The HEALPix dispatch had already drifted that way before these were
written.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import textwrap

import pytest

from uxarray_mcp.remote import compute_functions as cf

#: Parameter names that mean the same thing in different remote functions.
#: The short ones are the nested ``_open_grid(gp, dp)`` helpers in the two
#: remap functions; the long ones are top-level parameters.
_PATH_ALIASES = ("file_path", "grid_path", "target_grid_path", "gp")
_DATA_ALIASES = ("data_path", "dp")


def _remote_functions() -> list[tuple[str, ast.FunctionDef]]:
    """Every ``remote_*`` function in the payload module, parsed."""
    found = []
    for name in sorted(dir(cf)):
        if not name.startswith("remote_"):
            continue
        obj = getattr(cf, name)
        if not callable(obj):
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
        found.append((name, tree.body[0]))
    assert found, "no remote_* functions discovered"
    return found


def _normalize(node: ast.AST) -> str:
    """Source text with the interchangeable path parameter names folded away.

    Whole identifiers only: ``gp`` is two characters and would otherwise
    rewrite the middle of unrelated names.
    """
    text = ast.unparse(node)
    for aliases, stand_in in ((_PATH_ALIASES, "PATH"), (_DATA_ALIASES, "DATA")):
        text = re.sub(rf"\b(?:{'|'.join(aliases)})\b", stand_in, text)
    return text


def _healpix_zoom_calls(fn: ast.FunctionDef) -> list[ast.Call]:
    """Every ``Grid.from_healpix(...)`` call in a function.

    The surrounding dispatch is not comparable as text and should not be: some
    copies also derive ``grid_format``, some are nested ``_open_grid`` helpers
    that ``return`` instead of assigning, and ``remote_grid_facts`` reuses a
    grid it already opened. What must be identical is the argument -- how the
    zoom is dug out of the spec -- because that is the part with a local twin
    it has drifted from.
    """
    return [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "from_healpix"
    ]


def _dispatch_input_kinds(fn: ast.FunctionDef) -> tuple[bool, bool]:
    """Whether a function's dispatch offers the HEALPix and shapefile kinds.

    Read from the syntax tree, not from the source text. An earlier version
    counted the substrings ``startswith("healpix:")`` and ``".shp",
    ".geojson"`` and asserted the two counts were equal, which tied the guard
    to formatting rather than to behaviour: a dispatch whose extension list the
    formatter wrapped over three lines read as zero shapefile branches, and a
    nested ``if`` that names the HEALPix prefix twice read as two HEALPix
    branches. Neither is drift.

    What the guard is for is that both kinds are offered *at all*, so that is
    what is returned. How many times a function spells either one is its own
    business.
    """
    healpix = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "startswith"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "healpix:"
        for node in ast.walk(fn)
    )
    shapefile = any(
        isinstance(node, ast.Constant) and node.value in (".shp", ".geojson")
        for node in ast.walk(fn)
    )
    return healpix, shapefile


def _assigned_literal(fn: ast.FunctionDef, name: str):
    """The value assigned to a local constant, if the function defines one.

    The dimension helpers are inlined as statement blocks rather than nested
    functions, and their local variable names differ between copies, so the
    blocks cannot be compared as text. Their classification constants can, and
    those are the part that has drifted before -- the comment at
    ``compute_functions.py:1632`` records an earlier round of exactly that.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    return None


def _worker_runtime_dicts(fn: ast.FunctionDef) -> list[ast.Dict]:
    """Every dict literal stored under a ``_worker_runtime`` key."""
    found = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "_worker_runtime"
                and isinstance(value, ast.Dict)
            ):
                found.append(value)
    return found


def _assert_one_shape(blocks: dict[str, str], what: str, expected: int) -> None:
    """Every copy of ``what`` must normalize to the same text."""
    assert len(blocks) == expected, (
        f"expected {expected} copies of {what}, found {len(blocks)}: "
        f"{sorted(blocks)}. Update the count deliberately -- a copy that "
        f"disappeared is drift too."
    )
    variants: dict[str, list[str]] = {}
    for owner, text in blocks.items():
        variants.setdefault(text, []).append(owner)
    if len(variants) > 1:
        report = "\n\n".join(
            f"--- {sorted(owners)} ---\n{text}" for text, owners in variants.items()
        )
        pytest.fail(f"{len(variants)} versions of {what} are in the tree:\n{report}")


def _each(collect):
    """Every copy the collector finds, keyed by owning function and position.

    Several functions carry more than one copy, so the key has to say which:
    keying by function name alone silently collapsed three of them.
    """
    for name, fn in _remote_functions():
        for position, node in enumerate(collect(fn)):
            yield f"{name}[{position}]", node


def _all_blocks(collect, label: str) -> dict[str, str]:
    """Normalized source for every copy, keyed by owner and position."""
    blocks = {key: _normalize(node) for key, node in _each(collect)}
    assert blocks, f"no copies of {label} found"
    return blocks


class TestInlinedCopiesAgree:
    def test_the_zoom_is_extracted_the_same_way_everywhere(self):
        """One spelling of the zoom argument across every copy.

        Twenty-one call sites, and a worker that read the zoom differently
        from the other twenty would answer the same request with a different
        mesh. The count is asserted too: a copy that vanished is drift.
        """
        blocks = _all_blocks(_healpix_zoom_calls, "the HEALPix zoom argument")
        _assert_one_shape(blocks, "the HEALPix zoom argument", 21)

    def test_every_dispatch_offers_the_same_input_kinds(self):
        """A path the worker can open in one tool must open in all of them.

        The three kinds are a HEALPix spec, a shapefile or GeoJSON read
        through geopandas, and everything ``ux.open_grid`` handles. Nothing
        made them travel together, so a tool added with only the HEALPix
        branch would reject a shapefile that every neighbouring tool accepts.

        A function that dispatches on neither is not in scope: the smoke and
        probe payloads build their own grids and never take a path.
        """
        offenders = {
            name: {"healpix": kinds[0], "shapefile": kinds[1]}
            for name, fn in _remote_functions()
            if (kinds := _dispatch_input_kinds(fn))[0] != kinds[1]
        }
        assert not offenders, (
            "these remote functions offer the HEALPix input kind without the "
            f"shapefile kind, or the reverse: {offenders}"
        )

    def test_the_input_kind_guard_would_notice_a_missing_branch(self):
        """The test above passing is only worth something if this one does.

        Its predecessor counted substrings, so it reported a wrapped
        extension list as no shapefile branch at all and a nested ``if`` as
        two HEALPix branches -- it failed on formatting and would equally
        have passed on a real omission that happened to balance. Both cases
        are pinned here: the payload that genuinely drops the shapefile read
        is caught, and the two spellings of the extension test that the
        formatter chooses between are read the same way.
        """

        def parse(src: str) -> ast.FunctionDef:
            return ast.parse(textwrap.dedent(src)).body[0]

        dropped_the_shapefile_read = parse(
            """
            def remote_example(grid_path):
                if grid_path.lower().startswith("healpix:"):
                    grid = ux.Grid.from_healpix(int(grid_path.split(":")[1]))
                else:
                    grid = ux.open_grid(grid_path)
            """
        )
        assert _dispatch_input_kinds(dropped_the_shapefile_read) == (True, False)

        on_one_line = parse(
            """
            def remote_example(grid_path):
                if grid_path.lower().startswith("healpix:"):
                    grid = None
                elif os.path.splitext(grid_path.lower())[1] in [".shp", ".geojson"]:
                    grid = None
            """
        )
        wrapped_by_the_formatter = parse(
            """
            def remote_example(grid_path):
                if grid_path.lower().startswith("healpix:") or os.path.splitext(
                    grid_path.lower()
                )[1] in [
                    ".shp",
                    ".geojson",
                ]:
                    if grid_path.lower().startswith("healpix:"):
                        grid = None
            """
        )
        assert _dispatch_input_kinds(on_one_line) == (True, True)
        assert _dispatch_input_kinds(wrapped_by_the_formatter) == (True, True)

    def test_the_worker_runtime_envelope_reports_the_same_keys(self):
        """Presence was already guarded; shape was not.

        ``test_hpc_safety.py`` asserts the string ``_worker_runtime`` appears
        in each function's source, so a copy that reported four of the six
        keys, or spelled ``uxarray_version`` differently, passed.

        Keys, not values: three copies reach the same six facts by a different
        route -- ``remote_runtime_probe`` has already imported ``socket`` and
        ``platform`` at the top, ``remote_subset_bbox_plot`` bound
        ``ux_version`` earlier -- and rewriting them to match the other
        seventeen character for character would change no behaviour.
        """
        blocks = {
            key: repr([ast.literal_eval(k) for k in node.keys])
            for key, node in _each(_worker_runtime_dicts)
        }
        _assert_one_shape(blocks, "the _worker_runtime key list", 21)

    @pytest.mark.parametrize("constant", ["_LEVEL_EXACT", "_LEVEL_SUBSTR"])
    def test_the_dimension_classification_is_one_policy(self, constant):
        blocks = {
            name: repr(sorted(value))
            for name, fn in _remote_functions()
            if (value := _assigned_literal(fn, constant)) is not None
        }
        _assert_one_shape(blocks, f"the inlined {constant}", 8)


class TestInlinedHelpersMatchTheirDomainTwin:
    """Copy-versus-copy agreement is not enough when a local twin exists.

    A worker that classifies ``n_level`` as "other" pins it to index 0 while
    the local path honours ``level_index`` -- the same request answered
    differently depending on where it ran, with nothing in either result
    saying which happened.
    """

    @pytest.mark.parametrize(
        ("constant", "twin"),
        [
            ("_LEVEL_EXACT", "LEVEL_DIM_NAMES"),
            ("_LEVEL_SUBSTR", "LEVEL_DIM_SUBSTRINGS"),
        ],
    )
    def test_the_worker_constant_matches_the_domain_constant(self, constant, twin):
        from uxarray_mcp.domain import dims

        worker_values = [
            (name, value)
            for name, fn in _remote_functions()
            if (value := _assigned_literal(fn, constant)) is not None
        ]
        assert worker_values, f"no worker copy of {constant} found"

        local = set(getattr(dims, twin))
        for name, value in worker_values:
            assert set(value) == local, (
                f"{name} classifies dimensions by {sorted(value)}, "
                f"domain.dims.{twin} says {sorted(local)}"
            )

    def test_a_level_dimension_is_reduced_the_same_way_by_both_venues(self):
        """The behavioural half: the constants agreeing is not the outcome."""
        from uxarray_mcp.domain.dims import classify_dim

        for dim in ("n_level", "nlev", "num_levels", "nVertLevels", "plev"):
            assert classify_dim(dim) == "level", dim
        assert classify_dim("time_counter") == "time"
        assert classify_dim("ncol") == "other"


class TestHealpixValidationIsTheSameLocallyAndRemotely:
    """A zoom the local loader refuses must not reach an HPC node.

    ``domain/mesh.py`` caps the zoom at ``MAX_HEALPIX_ZOOM`` because zoom 14 is
    over three billion faces; the worker copies call ``Grid.from_healpix`` on
    whatever integer they are handed. The check now happens once at the venue
    boundary instead of in 21 payload copies.
    """

    @pytest.mark.parametrize("spec", ["healpix:99", "healpix:-1", "healpix:zoom"])
    def test_a_bad_zoom_is_refused_before_dispatch(self, spec):
        from uxarray_mcp.tools import remote_tools

        def _must_not_run():  # pragma: no cover - the point is that it does not
            raise AssertionError("dispatch happened on an invalid HEALPix spec")

        with pytest.raises(ValueError):
            remote_tools._run_with_optional_hpc(
                tool_name="inspect_mesh",
                use_remote=True,
                path_hint=spec,
                session_id=None,
                local_call=_must_not_run,
                remote_call=lambda _agent: _must_not_run(),
            )

    def test_a_good_zoom_still_gets_through(self):
        from uxarray_mcp.tools import remote_tools

        result = remote_tools._run_with_optional_hpc(
            tool_name="inspect_mesh",
            use_remote=False,
            path_hint="healpix:2",
            session_id=None,
            local_call=lambda: {"_provenance": {}},
            remote_call=lambda _agent: {"_provenance": {}},
        )

        assert "_provenance" in result


class TestYacPrefixOverride:
    """The prefix-repointing branch added with the YAC smoke test.

    It had no coverage at all: the one caller in the suite invoked
    ``remote_yac_remap_smoke()`` with no arguments, so neither the path
    rewriting nor the ``yac_prefix_override`` key was ever exercised.
    """

    def test_an_explicit_prefix_displaces_every_other_yac_on_both_paths(
        self, tmp_path, monkeypatch
    ):
        prefix = tmp_path / "yac-3.20.2"
        site = prefix / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True)
        stale = f"/opt/yac-3.18/lib{os.pathsep}/usr/lib"
        monkeypatch.setenv("PYTHONPATH", "/opt/yac-3.18/lib/python3.11/site-packages")
        monkeypatch.setenv("LD_LIBRARY_PATH", stale)

        result = cf.remote_yac_remap_smoke(yac_prefix=str(prefix))

        override = result["yac_prefix_override"]
        assert override["exists"] is True
        assert override["site_packages"] == [str(site)]
        # Prepending is not enough -- the old libyac would still be findable.
        assert "yac-3.18" not in override["pythonpath"]
        assert "yac-3.18" not in override["ld_library_path"]
        assert override["ld_library_path"].split(os.pathsep) == [
            str(prefix / "lib"),
            "/usr/lib",
        ]

    def test_no_prefix_leaves_the_environment_alone(self):
        result = cf.remote_yac_remap_smoke()

        assert result["yac_prefix_override"] is None
