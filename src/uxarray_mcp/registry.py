"""Build a ``toolregistry.ToolRegistry`` from ``uxarray_mcp.tools``.

Two profiles are supported:

* ``"core"`` (default, 33 tools) — small, predictable surface visible
  to LLMs.  Mirrors the original MCP server's 11 front-door tools, adds
  12 control/status tools, the ``list_datasets`` discovery helper, two
  response-contract helpers, and seven prompt-as-tool helpers (former
  ``@mcp.prompt()`` decorators).
* ``"deferred-full"`` (67 tools) — loads every public function with the
  core set enabled and 33 raw implementation tools marked ``defer=True``.
  Includes ``discover_tools`` (BM25 search) so LLMs find deferred
  tools by intent.

Policy tags (``ToolTag`` + custom strings) are attached from day one
so downstream policy code has concrete metadata to key off.

Nothing in ``uxarray_mcp.tools``, ``uxarray_mcp.domain``, or
``uxarray_mcp.remote`` is modified.
"""

from __future__ import annotations

import functools
import inspect
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal

from toolregistry import ToolRegistry
from toolregistry.tool import ToolTag

import uxarray_mcp.tools as _tools_mod
from uxarray_mcp.json_safe import json_safe

if TYPE_CHECKING:
    pass

Profile = Literal["core", "deferred-full"]


# ---------------------------------------------------------------------------
# Tool inventory
# ---------------------------------------------------------------------------

# The 11 original MCP front-door tools from the pre-rewrite server.py.
# These are the "gateway" tools — intent-shaped dispatchers that fan out
# to the implementation pool.  Kept as an explicit frozenset because the
# set is a design decision agreed with upstream, not something to be
# auto-discovered at runtime.
FRONTDOOR_NAMES: frozenset[str] = frozenset(
    {
        "get_capabilities",
        "analyze_dataset",
        "run_analysis",
        "plot_dataset",
        "diagnose_endpoint",
        "probe_path_access",
        "run_workflow",
        "resume_workflow",
        "get_status",
        "get_result",
        "manage_session",
    }
)


# 12 control/status tools — session + HPC infrastructure.
_CONTROL_TOOLS: dict[str, tuple[str, ...]] = {
    "session": (
        "create_session",
        "register_dataset",
        "get_session_state",
        "reset_session_state",
        "get_result_handle",
        "get_operation_status",
        "list_operations",
        "get_workflow_status",
    ),
    "hpc": (
        "endpoint_status",
        "get_execution_mode",
        "set_execution_mode",
        "validate_hpc_setup",
    ),
}

# Core-extra: tools with no front-door equivalent that are read-only.
_CORE_EXTRA_TOOLS: dict[str, tuple[str, ...]] = {
    "io": ("list_datasets",),
    # #91: the declared response shape is served on request, never bundled
    # into every result -- that would repeat the payload mistake #83 tracks.
    "contract": ("describe_response_contract", "validate_response"),
}

# Deferred pool — loaded only in ``deferred-full``.
_DEFERRED_TOOLS: dict[str, tuple[str, ...]] = {
    "compute": (
        "calculate_gradient",
        "calculate_curl",
        "calculate_divergence",
        "calculate_azimuthal_mean",
        "calculate_bias",
        "calculate_rmse",
        "calculate_pattern_correlation",
        "compare_fields",
        "calculate_temporal_mean",
        "calculate_anomaly",
        "calculate_ensemble_mean",
        "calculate_ensemble_spread",
        "calculate_area",
        "calculate_zonal_mean",
        "calculate_zonal_anomaly",
    ),
    "shape": (
        "subset_bbox",
        "subset_polygon",
        "extract_cross_section",
        "remap_variable",
        "regrid_dataset",
        "remap_to_rectilinear",
    ),
    "inspect": (
        "inspect_mesh",
        "inspect_variable",
        "validate_dataset",
    ),
    "plot": (
        "plot_mesh",
        "plot_mesh_geo",
        "plot_variable",
        "plot_zonal_mean",
    ),
    "io": (
        "export_to_netcdf",
        "export_to_csv",
        "write_result",
    ),
    "agent": ("run_scientific_agent",),
    "hpc": ("check_remote_yac",),
}

# Deferred too, but only when some endpoint declares a ``globus_transfer``
# block. An install that moves no files should show no sign of these: a tool
# whose only possible answer is "not configured" is still a tool the model can
# call, and calling it is the wrong lesson to have taught it.
_CONDITIONAL_TOOLS: dict[str, tuple[str, ...]] = {
    "transfer": (
        "transfer_ls",
        "transfer_put",
        "transfer_get",
        "transfer_status",
    ),
}

_CONDITIONAL_NAMES: frozenset[str] = frozenset(
    name for names in _CONDITIONAL_TOOLS.values() for name in names
)


def _transfers_are_configured() -> bool:
    """Whether any endpoint says where its files live.

    Wrapped rather than imported at module scope so building a registry never
    depends on config being readable, and so a test can decide the answer
    without writing a config file.
    """
    from uxarray_mcp.tools.transfer_tools import transfers_are_configured

    return transfers_are_configured()


# ---------------------------------------------------------------------------
# Prompt-as-tool helpers (formerly @mcp.prompt() decorators)
# ---------------------------------------------------------------------------


def first_look(path: str) -> str:
    """Generate a step-by-step prompt for first-look mesh/dataset analysis.

    Returns a text plan instructing the LLM to call ``get_capabilities``
    and ``analyze_dataset`` in sequence and summarise the results.

    Args:
        path: Path to the mesh or dataset file.

    Returns:
        Multi-step analysis prompt as a string.
    """
    return (
        f"Run a complete first-look analysis on `{path}`.\n\n"
        "Steps:\n"
        f'1. Call `get_capabilities` with `grid_path="{path}"` to discover '
        "what operations apply.\n"
        f'2. Call `analyze_dataset` with `grid_path="{path}"` to run the full '
        "first-look pipeline.\n"
        "3. Summarise topology, data quality issues, selected variable, area "
        "statistics, zonal mean, plots, and recommended next steps."
    )


def vorticity_analysis(grid_path: str, data_path: str, u_var: str, v_var: str) -> str:
    """Generate a multi-step analysis plan for rotation and divergence fields.

    Returns instructional text (not results) that guides the LLM through
    calling ``run_analysis`` twice and interpreting the output.  Use this
    when you need a structured walkthrough rather than a single operation.

    Args:
        grid_path: Path to the mesh grid file.
        data_path: Path to the data file with vector components.
        u_var: Zonal (east-west) component variable name.
        v_var: Meridional (north-south) component variable name.

    Returns:
        Multi-step analysis plan as a string.
    """
    return (
        f"Analyse vorticity and divergence for `{data_path}`.\n\n"
        "1. Call `run_analysis` with "
        f'operation="curl", grid_path="{grid_path}", data_path="{data_path}", '
        f'u_variable="{u_var}", v_variable="{v_var}".\n'
        "2. Call `run_analysis` with "
        f'operation="divergence", grid_path="{grid_path}", '
        f'data_path="{data_path}", u_variable="{u_var}", '
        f'v_variable="{v_var}".\n'
        "3. Interpret the min/max/mean/std values and identify follow-up "
        "plots or regional subsets."
    )


def cyclone_structure(
    grid_path: str,
    data_path: str,
    variable_name: str,
    center_lon: float,
    center_lat: float,
    u_var: str = "",
    v_var: str = "",
    outer_radius: float = 10.0,
) -> str:
    """Generate a guided plan to characterise a cyclone / vortex structure.

    Builds a radial picture of a storm or vortex around a centre point using the
    azimuthal (radial) mean, optionally adding the rotational field. Returns
    instructional text — the LLM runs the operations and interprets them.

    Args:
        grid_path: Path to the mesh grid file.
        data_path: Path to the data file.
        variable_name: Field to profile radially (e.g. wind speed, pressure).
        center_lon: Longitude of the storm centre (degrees).
        center_lat: Latitude of the storm centre (degrees).
        u_var: Optional zonal wind component for a vorticity check.
        v_var: Optional meridional wind component for a vorticity check.
        outer_radius: Maximum radius in great-circle degrees.

    Returns:
        Multi-step cyclone-structure analysis plan as a string.
    """
    steps = [
        "1. Call `run_analysis` with "
        f'operation="azimuthal_mean", grid_path="{grid_path}", '
        f'data_path="{data_path}", variable_name="{variable_name}", '
        f"center_lon={center_lon}, center_lat={center_lat}, "
        f"outer_radius={outer_radius}, radius_step=0.5 to build the radial "
        "profile.",
        "2. Call `run_analysis` with "
        f'operation="subset_bbox", grid_path="{grid_path}", '
        f'data_path="{data_path}", variable_name="{variable_name}", '
        f"lon_bounds=[{center_lon - outer_radius}, {center_lon + outer_radius}], "
        f"lat_bounds=[{center_lat - outer_radius}, {center_lat + outer_radius}] "
        "to isolate the storm region.",
    ]
    if u_var and v_var:
        steps.append(
            "3. Call `run_analysis` with "
            f'operation="curl", grid_path="{grid_path}", data_path="{data_path}", '
            f'u_variable="{u_var}", v_variable="{v_var}" to confirm the '
            "rotational signature (relative vorticity)."
        )
    steps.append(
        f"{len(steps) + 1}. Interpret the radial profile: locate the radius of "
        "maximum wind / minimum pressure, the storm's radial extent, and any "
        'asymmetry. Plot the subset with `plot_dataset(plot_type="variable")`.'
    )
    return (
        f"Characterise the cyclone/vortex near ({center_lon}, {center_lat}) in "
        f"`{data_path}`.\n\n" + "\n".join(steps)
    )


def eddy_activity(
    grid_path: str,
    data_path: str,
    variable_name: str,
) -> str:
    """Generate a guided plan to assess eddy / wave activity.

    Quantifies departures from the latitudinal background state — the signature
    of eddies, stationary waves, and storm tracks — using the zonal anomaly and
    its gradient. Returns instructional text.

    Args:
        grid_path: Path to the mesh grid file.
        data_path: Path to the data file.
        variable_name: Face-centered field to analyse (e.g. geopotential height,
            temperature).

    Returns:
        Multi-step eddy-activity analysis plan as a string.
    """
    return (
        f"Assess eddy/wave activity for `{variable_name}` in `{data_path}`.\n\n"
        "1. Call `run_analysis` with "
        f'operation="calculate_zonal_mean", grid_path="{grid_path}", '
        f'data_path="{data_path}", variable_name="{variable_name}" to establish '
        "the latitudinal background state.\n"
        "2. Call `run_analysis` with "
        f'operation="zonal_anomaly", grid_path="{grid_path}", '
        f'data_path="{data_path}", variable_name="{variable_name}" to isolate '
        "departures from each latitude band (the eddy field).\n"
        "3. Call `run_analysis` with "
        f'operation="gradient", grid_path="{grid_path}", data_path="{data_path}", '
        f'variable_name="{variable_name}" to highlight sharp gradients and '
        "fronts associated with the waves.\n"
        "4. Interpret the anomaly amplitude (std/max) as eddy strength, note "
        "where activity concentrates, and plot the anomaly field with "
        '`plot_dataset(plot_type="variable")`.'
    )


def model_evaluation(
    grid_path: str,
    data_path_a: str,
    data_path_b: str,
    variable_name: str,
) -> str:
    """Generate a guided plan to evaluate a model field against a reference.

    Computes the standard verification triple — bias, RMSE, and pattern
    correlation — between two same-grid fields and guides interpretation.
    Returns instructional text.

    Args:
        grid_path: Path to the shared mesh grid file.
        data_path_a: Model / candidate dataset.
        data_path_b: Reference / observation dataset.
        variable_name: Field to compare.

    Returns:
        Multi-step model-evaluation plan as a string.
    """
    return (
        f"Evaluate `{variable_name}` in `{data_path_a}` against reference "
        f"`{data_path_b}`.\n\n"
        "1. Call `run_analysis` with "
        f'operation="bias", grid_path="{grid_path}", '
        f'data_path_a="{data_path_a}", data_path_b="{data_path_b}", '
        f'variable_name="{variable_name}" for the mean signed error.\n'
        "2. Call `run_analysis` with "
        f'operation="rmse", grid_path="{grid_path}", '
        f'data_path_a="{data_path_a}", data_path_b="{data_path_b}", '
        f'variable_name="{variable_name}" for the magnitude of the error.\n'
        "3. Call `run_analysis` with "
        f'operation="pattern_correlation", grid_path="{grid_path}", '
        f'data_path_a="{data_path_a}", data_path_b="{data_path_b}", '
        f'variable_name="{variable_name}" for spatial-pattern skill.\n'
        "4. Interpret together: bias = systematic offset, RMSE = typical error "
        "size, pattern correlation = structural agreement (1.0 = perfect). Call "
        "out whether errors are a uniform offset or a structural mismatch."
    )


def climatology_anomaly(
    data_path: str,
    variable_name: str,
    grid_path: str = "",
) -> str:
    """Generate a guided plan for a climatology and anomaly analysis.

    Establishes the time-mean state and the departures from it over a time
    series, then summarises the anomaly latitudinally. Returns instructional
    text.

    Args:
        data_path: Path to a time-series data file.
        variable_name: Field to analyse.
        grid_path: Optional mesh grid file (needed for the zonal summary).

    Returns:
        Multi-step climatology/anomaly plan as a string.
    """
    grid_arg = f'grid_path="{grid_path}", ' if grid_path else ""
    last = (
        "4. Call `run_analysis` with "
        f'operation="calculate_zonal_mean", grid_path="{grid_path}", '
        f'data_path="{data_path}", variable_name="{variable_name}" to summarise '
        "the anomaly by latitude.\n"
        if grid_path
        else ""
    )
    return (
        f"Build a climatology and anomalies for `{variable_name}` in "
        f"`{data_path}`.\n\n"
        "1. Call `run_analysis` with "
        f'operation="temporal_mean", data_path="{data_path}", '
        f'variable_name="{variable_name}" to compute the time-mean climatology.\n'
        "2. Call `run_analysis` with "
        f'operation="anomaly", {grid_arg}data_path="{data_path}", '
        f'variable_name="{variable_name}" to compute departures from the mean '
        "state.\n"
        f'3. Plot the anomaly with `plot_dataset(plot_type="variable")`'
        + (".\n" + last if last else " and interpret the spatial structure.\n")
        + (
            f"{5 if grid_arg and last else 4}. Interpret where and when the "
            "field departs most from its climatology."
        )
    )


def hpc_diagnose(endpoint: str = "") -> str:
    """Generate a step-by-step prompt for HPC endpoint diagnosis.

    Returns a text plan instructing the LLM to check endpoint status,
    validate connectivity, and suggest corrective actions.

    Args:
        endpoint: Optional endpoint name to diagnose. Omit for default.

    Returns:
        Multi-step HPC diagnosis prompt as a string.
    """
    ep = f', endpoint="{endpoint}"' if endpoint else ""
    return (
        "Diagnose the HPC Globus Compute configuration.\n\n"
        f'1. Call `diagnose_endpoint(action="status"{ep})` for endpoint '
        "manager and worker status.\n"
        f'2. Call `diagnose_endpoint(action="validate"{ep})` for SDK auth, '
        "manager reachability, and a remote no-op probe.\n"
        "3. Explain failures as concrete next actions: re-authenticate, "
        "restart the endpoint, fix worker environment, or probe a path."
    )


_PROMPT_TOOLS: dict[str, tuple[str, ...]] = {
    "prompt": (
        "first_look",
        "vorticity_analysis",
        "cyclone_structure",
        "eddy_activity",
        "model_evaluation",
        "climatology_anomaly",
        "hpc_diagnose",
    ),
}

# Map prompt tool names to their implementing functions (defined above
# in this module rather than pulled from uxarray_mcp.tools).
_PROMPT_FUNCS: dict[str, object] = {
    "first_look": first_look,
    "vorticity_analysis": vorticity_analysis,
    "cyclone_structure": cyclone_structure,
    "eddy_activity": eddy_activity,
    "model_evaluation": model_evaluation,
    "climatology_anomaly": climatology_anomaly,
    "hpc_diagnose": hpc_diagnose,
}


# ---------------------------------------------------------------------------
# Policy tags
# ---------------------------------------------------------------------------

_TAG_OVERRIDES: dict[str, tuple[set[ToolTag], set[str]]] = {
    # Session state mutators — persist records to disk via state._write_json
    "create_session": ({ToolTag.FILE_SYSTEM}, {"stateful"}),
    "register_dataset": ({ToolTag.FILE_SYSTEM}, {"stateful"}),
    "reset_session_state": ({ToolTag.FILE_SYSTEM}, {"stateful"}),
    # Session/control read-only — read persisted records via state._read_json
    "get_session_state": ({ToolTag.READ_ONLY, ToolTag.FILE_SYSTEM}, set()),
    "get_result_handle": ({ToolTag.READ_ONLY, ToolTag.FILE_SYSTEM}, set()),
    "get_operation_status": ({ToolTag.READ_ONLY, ToolTag.FILE_SYSTEM}, set()),
    "list_operations": ({ToolTag.READ_ONLY, ToolTag.FILE_SYSTEM}, set()),
    "get_workflow_status": ({ToolTag.READ_ONLY, ToolTag.FILE_SYSTEM}, set()),
    # HPC control
    "endpoint_status": ({ToolTag.READ_ONLY, ToolTag.NETWORK}, set()),
    # Reads config from disk; queries the Globus Compute endpoint when one
    # is configured (check_endpoint_manager_status), so it can hit the network.
    "get_execution_mode": (
        {ToolTag.READ_ONLY, ToolTag.FILE_SYSTEM, ToolTag.NETWORK},
        set(),
    ),
    "validate_hpc_setup": ({ToolTag.READ_ONLY, ToolTag.NETWORK}, set()),
    "check_remote_yac": (
        {ToolTag.READ_ONLY, ToolTag.NETWORK, ToolTag.SLOW},
        set(),
    ),
    "set_execution_mode": ({ToolTag.FILE_SYSTEM}, set()),
    # IO
    "list_datasets": ({ToolTag.READ_ONLY, ToolTag.FILE_SYSTEM}, set()),
    "export_to_netcdf": ({ToolTag.FILE_SYSTEM}, set()),
    "export_to_csv": ({ToolTag.FILE_SYSTEM}, set()),
    "write_result": ({ToolTag.FILE_SYSTEM}, set()),
    # Experimental agent
    "run_scientific_agent": ({ToolTag.SLOW}, {"experimental"}),
    # Prompt tools are always read-only (they just return text)
    "first_look": ({ToolTag.READ_ONLY}, set()),
    "vorticity_analysis": ({ToolTag.READ_ONLY}, set()),
    "cyclone_structure": ({ToolTag.READ_ONLY}, set()),
    "eddy_activity": ({ToolTag.READ_ONLY}, set()),
    "model_evaluation": ({ToolTag.READ_ONLY}, set()),
    "climatology_anomaly": ({ToolTag.READ_ONLY}, set()),
    "hpc_diagnose": ({ToolTag.READ_ONLY}, set()),
}

_SLOW_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "calculate_curl",
        "calculate_divergence",
        "calculate_gradient",
        "calculate_azimuthal_mean",
        "calculate_zonal_mean",
        "calculate_zonal_anomaly",
        "calculate_temporal_mean",
        "calculate_anomaly",
        "calculate_ensemble_mean",
        "calculate_ensemble_spread",
        "compare_fields",
        "calculate_bias",
        "calculate_rmse",
        "calculate_pattern_correlation",
        "remap_variable",
        "regrid_dataset",
        "remap_to_rectilinear",
        "subset_polygon",
        "extract_cross_section",
        "plot_mesh",
        "plot_mesh_geo",
        "plot_variable",
        "plot_zonal_mean",
    }
)


def _default_tags_for(
    name: str,
    func: object,
) -> tuple[set[ToolTag], set[str]]:
    """Infer tags when no explicit override exists."""
    predefined: set[ToolTag] = set()
    custom: set[str] = set()
    try:
        sig = inspect.signature(func)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        sig = None
    if sig is not None and "use_remote" in sig.parameters:
        predefined.add(ToolTag.NETWORK)
    if name in _SLOW_TOOL_NAMES:
        predefined.add(ToolTag.SLOW)
    if not predefined and not custom:
        predefined.add(ToolTag.READ_ONLY)
    return predefined, custom


_WIRE_SAFE_FLAG = "_uxarray_mcp_wire_safe"


def _wire_safe(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap ``func`` so its result is JSON-representable before it leaves.

    Registration is the one place every tool passes through, which is why
    the sanitizer attaches here rather than at the ~81 sites that call
    ``attach_provenance`` -- those cover most tools, but "most" is the
    wrong guarantee for a serialization boundary. A NaN that escapes is
    not a wrong number in one field; it is a response the client's JSON
    decoder rejects whole.
    """
    if getattr(func, _WIRE_SAFE_FLAG, False):
        return func

    if inspect.iscoroutinefunction(func):
        # No async tools exist today. If one is added it must be wrapped
        # too, rather than quietly bypassing the boundary.
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return json_safe(await func(*args, **kwargs))

    else:

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return json_safe(func(*args, **kwargs))

    setattr(wrapper, _WIRE_SAFE_FLAG, True)
    return wrapper


def _make_results_wire_safe(tool: Any) -> None:
    """Sanitize a registered tool's results without touching its schema.

    The wrapper is swapped in *after* registration, on the callable
    ``Tool.from_function`` already built, rather than passed to
    ``register()``. Passing it in looked equivalent and was not:
    parameter schemas are generated with ``get_type_hints``, which
    resolves annotations against the function's own ``__globals__``, and
    ``functools.wraps`` cannot carry those over. Registering the wrapper
    directly resolved every annotation in *this* module's namespace
    instead, where ``Optional`` and the rest are not defined -- measured
    as 28 parameters across the deferred-full surface silently falling
    back to an unconstrained schema. By this point the schema is built,
    so replacing the underlying function is invisible to it.
    """
    callable_ = getattr(tool, "callable", None)
    if callable_ is None:
        return
    inner = getattr(callable_, "fn", None)
    if inner is None:
        return
    callable_.fn = _wire_safe(inner)


def _trim_wire_schema(tool: Any) -> None:
    """Drop schema nobody asked for from what we actually serve.

    Two separate pieces of dead weight ride on ``tool.parameters``, and
    both reach clients because the MCP and REST surfaces read that dict
    directly -- ``RouteTable._tool_to_route`` at
    ``toolregistry_server/route_table.py:186`` -- rather than going
    through ``Tool.get_schema()``, which is where upstream does its
    cleaning. Measured together at ~2,400 tokens per request on the
    33-tool core surface, or 21% of it.

    ``toolcall_reason``: ``Tool.model_post_init`` writes this key into
    ``parameters`` on every construction (``toolregistry/tool.py:253``),
    unconditionally. The switch meant to govern it lives in
    ``get_schema()`` (``tool.py:436``) and defaults to off, which is the
    registry we build -- so the feature is disabled and the schema ships
    anyway. Execution already discards the argument
    (``tool_registry.py:361``), so nothing depends on clients sending it.

    Pydantic ``title``: every generated property carries a ``"title"``
    restating its own name in title case. It is display metadata no
    client needs. Upstream agrees it is noise and strips it in
    ``get_schema()``, but with a blanket key filter
    (``Tool._EXTRA_STRIP_KEYS``) that descends into ``properties`` and
    deletes the *parameter named* ``title`` along with it -- which is why
    ``plot_dataset``'s real ``title`` argument is missing from
    ``get_schemas()``. Recurse into property values only, so the
    annotation goes and the parameter stays.

    Both passes are idempotent, and the first becomes a no-op if upstream
    closes the gap.
    """
    params = getattr(tool, "parameters", None)
    if not isinstance(params, dict):
        return

    props = params.get("properties")
    if isinstance(props, dict):
        props.pop("toolcall_reason", None)
    required = params.get("required")
    if isinstance(required, list) and "toolcall_reason" in required:
        params["required"] = [r for r in required if r != "toolcall_reason"]

    _drop_title_annotations(params)


def _drop_title_annotations(schema: Any) -> None:
    """Remove Pydantic ``title`` metadata in place, keeping parameter names.

    Only the values under ``properties`` are recursed into. The keys of
    that mapping are parameter names and are never inspected, which is
    the whole difference between this and a blanket key strip.
    """
    if not isinstance(schema, dict):
        return
    schema.pop("title", None)
    props = schema.get("properties")
    if isinstance(props, dict):
        for spec in props.values():
            _drop_title_annotations(spec)
    items = schema.get("items")
    if isinstance(items, dict):
        _drop_title_annotations(items)


def _apply_tags(
    registry: ToolRegistry,
    registered_name: str,
    raw_name: str,
    func: object,
) -> None:
    """Apply policy tags and the JSON boundary to a freshly registered tool."""
    tool = registry.get_tool(registered_name)
    if tool is None:
        return
    _make_results_wire_safe(tool)
    if tool.metadata is None:
        return
    if raw_name in _TAG_OVERRIDES:
        predefined, custom = _TAG_OVERRIDES[raw_name]
    else:
        predefined, custom = _default_tags_for(raw_name, func)
    tool.metadata.tags |= predefined
    tool.metadata.custom_tags |= custom
    _apply_output_schema(tool, raw_name)


def _apply_output_schema(tool: object, raw_name: str) -> None:
    """Publish a declared response shape as MCP ``outputSchema``.

    The adapter reads ``metadata.extra['output_schema']`` and forwards it
    to clients in ``tools/list``. Only operations that already declare a
    response contract get one; the rest stay silent rather than
    advertising a shape we have not committed to.
    """
    from .typed_results import output_schema_for

    schema = output_schema_for(raw_name)
    if schema is None:
        return
    metadata = getattr(tool, "metadata", None)
    if metadata is None:
        return
    if not isinstance(getattr(metadata, "extra", None), dict):
        metadata.extra = {}
    metadata.extra["output_schema"] = schema


# ---------------------------------------------------------------------------
# BM25 search hints
# ---------------------------------------------------------------------------

_SEARCH_HINTS: dict[str, str] = {
    "check_remote_yac": "yac native remap conservative interpolation worker library build smoke test hpc",
    "transfer_ls": "list remote directory globus collection files hpc browse",
    "transfer_put": "upload stage copy file to hpc cluster globus transfer send",
    "transfer_get": "download fetch retrieve file from hpc cluster globus transfer",
    "transfer_status": "transfer task progress bytes globus poll",
    "calculate_curl": "vorticity rotation circulation wind curl cross product compute vector field zeta",
    "calculate_divergence": "compression expansion source sink wind divergence",
    "calculate_gradient": "spatial derivative slope field gradient",
    "calculate_azimuthal_mean": "radial profile cyclone storm azimuthal",
    "calculate_zonal_mean": "latitudinal average belt zonal",
    "calculate_zonal_anomaly": "zonal anomaly deviation latitude band eddy wave departure",
    "calculate_temporal_mean": "time average climatology",
    "calculate_anomaly": "deviation departure climatology",
    "calculate_ensemble_mean": "model average multi-member",
    "calculate_ensemble_spread": "uncertainty standard deviation members",
    "calculate_bias": "systematic error mean difference",
    "calculate_rmse": "root mean square error verification",
    "calculate_pattern_correlation": "spatial similarity skill score",
    "compare_fields": "diff two datasets verification",
    "calculate_area": "face cell surface area",
    "subset_bbox": "longitude latitude bounding box region",
    "subset_polygon": "polygon region of interest mask",
    "extract_cross_section": "transect slice latitude longitude",
    "remap_variable": "interpolation target grid",
    "regrid_dataset": "interpolation target grid all variables",
    "remap_to_rectilinear": "remap rectilinear regular lon lat structured grid interpolation",
    "inspect_mesh": "topology nodes faces edges grid summary",
    "inspect_variable": "data variable metadata stats",
    "validate_dataset": "data quality NaN Inf fill check",
    "plot_mesh": "wireframe mesh rendering png",
    "plot_mesh_geo": "geographic projection coastlines borders png",
    "plot_variable": "filled contour field rendering png",
    "plot_zonal_mean": "profile plot zonal latitude png",
    "export_to_netcdf": "save write netcdf file disk",
    "export_to_csv": "save write csv file disk",
    "write_result": "save persist result handle file",
    "run_scientific_agent": "autonomous agent workflow loop experimental",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_registry(
    *,
    profile: Profile = "core",
    registry_name: str = "uxarray",
) -> ToolRegistry:
    """Build a ``ToolRegistry`` for the chosen profile.

    Args:
        profile: ``"core"`` for the small default surface (33 tools),
            ``"deferred-full"`` for the complete pool (33 core visible,
            33 raw tools deferred, ``discover_tools`` added).
        registry_name: Identifier for server titles and labels.

    Returns:
        A populated ``ToolRegistry`` ready for ``RouteTable`` wrapping.

    Raises:
        ValueError: Unknown profile.
        RuntimeError: Upstream tool surface drifted from namespace plan.
    """
    if profile not in ("core", "deferred-full"):
        raise ValueError(
            f"unknown profile {profile!r}; expected 'core' or 'deferred-full'"
        )

    registry = ToolRegistry(name=registry_name)
    sep = registry._name_sep  # noqa: SLF001
    registered: set[str] = set()

    # 1. Front-door gateway tools — top level, no namespace.
    for raw in sorted(FRONTDOOR_NAMES):
        func = getattr(_tools_mod, raw, None)
        if func is None:
            raise RuntimeError(
                f"build_registry expects front-door tool {raw!r} but it is "
                f"not exported from uxarray_mcp.tools."
            )
        registry.register(func)
        _apply_tags(registry, raw, raw, func)
        registered.add(raw)

    # 2. Control/status tools — namespaced.
    for ns, raw in _flatten(_CONTROL_TOOLS):
        if raw in registered:
            continue
        func = getattr(_tools_mod, raw)
        registry.register(func, namespace=ns)
        _apply_tags(registry, f"{ns}{sep}{raw}", raw, func)
        registered.add(raw)

    # 3. Core-extra IO.
    for ns, raw in _flatten(_CORE_EXTRA_TOOLS):
        if raw in registered:
            continue
        func = getattr(_tools_mod, raw)
        registry.register(func, namespace=ns)
        _apply_tags(registry, f"{ns}{sep}{raw}", raw, func)
        registered.add(raw)

    # 4. Prompt-as-tool helpers.
    for ns, raw in _flatten(_PROMPT_TOOLS):
        func = _PROMPT_FUNCS[raw]
        registry.register(func, namespace=ns)
        _apply_tags(registry, f"{ns}{sep}{raw}", raw, func)
        # Prompts don't come from uxarray_mcp.tools.__all__, track
        # separately.

    # 5. Deferred pool — only in deferred-full.
    if profile == "deferred-full":
        for ns, raw in _flatten(_DEFERRED_TOOLS):
            if raw in registered:
                continue
            func = getattr(_tools_mod, raw)
            registry.register(func, namespace=ns)
            qualified = f"{ns}{sep}{raw}"
            _apply_tags(registry, qualified, raw, func)
            registry.update_tool_metadata(
                qualified,
                defer=True,
                search_hint=_SEARCH_HINTS.get(raw, ""),
            )
            registered.add(raw)
        if _transfers_are_configured():
            for ns, raw in _flatten(_CONDITIONAL_TOOLS):
                func = getattr(_tools_mod, raw)
                registry.register(func, namespace=ns)
                qualified = f"{ns}{sep}{raw}"
                _apply_tags(registry, qualified, raw, func)
                registry.update_tool_metadata(
                    qualified,
                    defer=True,
                    search_hint=_SEARCH_HINTS.get(raw, ""),
                )
                registered.add(raw)
        registry.enable_tool_discovery()

    # ``enable_tool_discovery`` registers ``discover_tools`` itself, so it
    # never passes through the loops above. Sweep the whole surface rather
    # than name that one tool: anything the library registers on its own
    # belongs behind the same boundary, and both sweeps are idempotent, so
    # re-running them over already-treated tools costs nothing.
    for name in registry.list_tools():
        tool = registry.get_tool(name)
        if tool is not None:
            _make_results_wire_safe(tool)
            _trim_wire_schema(tool)

    _verify_coverage(registered, profile)
    return registry


def _flatten(
    buckets: dict[str, tuple[str, ...]],
) -> Iterable[tuple[str, str]]:
    """Yield ``(namespace, raw_name)`` pairs in stable order."""
    for ns, names in buckets.items():
        for name in names:
            yield ns, name


def _verify_coverage(registered: set[str], profile: Profile) -> None:
    """Loud check that the namespace plan matches upstream."""
    public = set(_tools_mod.__all__)
    if profile == "core":
        bogus = registered - public
        if bogus:
            raise RuntimeError(
                f"Bridge tried to register non-public tools: {sorted(bogus)}"
            )
        return
    # The conditional tools are public so they can be imported and tested, but
    # absent from an unconfigured registry on purpose. Excusing them here is
    # narrower than excusing whatever happens not to be registered: anything
    # else missing is still the loud failure this check exists to be.
    missing = public - registered - _CONDITIONAL_NAMES
    if missing:
        raise RuntimeError(
            f"Namespace plan out of date — {len(missing)} public tools "
            f"unaccounted: {sorted(missing)}. Update _DEFERRED_TOOLS."
        )
