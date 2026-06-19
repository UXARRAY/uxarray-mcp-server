"""Build a ``toolregistry.ToolRegistry`` from ``uxarray_mcp.tools``.

Two profiles are supported:

* ``"core"`` (default) — small, predictable surface visible to LLMs.
  Mirrors the original MCP server's 11 front-door tools, adds 12
  control/status tools, the ``list_datasets`` discovery helper, and
  three prompt-as-tool helpers (former ``@mcp.prompt()`` decorators).
* ``"deferred-full"`` — loads every public function with the core set
  enabled and 30 raw implementation tools marked ``defer=True``.
  Includes ``discover_tools`` (BM25 search) so LLMs find deferred
  tools by intent.

Policy tags (``ToolTag`` + custom strings) are attached from day one
so downstream policy code has concrete metadata to key off.

Nothing in ``uxarray_mcp.tools``, ``uxarray_mcp.domain``, or
``uxarray_mcp.remote`` is modified.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Iterable, Literal

from toolregistry import ToolRegistry
from toolregistry.tool import ToolTag

import uxarray_mcp.tools as _tools_mod

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
    ),
    "shape": (
        "subset_bbox",
        "subset_polygon",
        "extract_cross_section",
        "remap_variable",
        "regrid_dataset",
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
}


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
    "prompt": ("first_look", "vorticity_analysis", "hpc_diagnose"),
}

# Map prompt tool names to their implementing functions (defined above
# in this module rather than pulled from uxarray_mcp.tools).
_PROMPT_FUNCS: dict[str, object] = {
    "first_look": first_look,
    "vorticity_analysis": vorticity_analysis,
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
    "hpc_diagnose": ({ToolTag.READ_ONLY}, set()),
}

_SLOW_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "calculate_curl",
        "calculate_divergence",
        "calculate_gradient",
        "calculate_azimuthal_mean",
        "calculate_zonal_mean",
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


def _apply_tags(
    registry: ToolRegistry,
    registered_name: str,
    raw_name: str,
    func: object,
) -> None:
    """Apply policy tags to a freshly registered tool."""
    tool = registry.get_tool(registered_name)
    if tool is None or tool.metadata is None:
        return
    if raw_name in _TAG_OVERRIDES:
        predefined, custom = _TAG_OVERRIDES[raw_name]
    else:
        predefined, custom = _default_tags_for(raw_name, func)
    tool.metadata.tags |= predefined
    tool.metadata.custom_tags |= custom


# ---------------------------------------------------------------------------
# BM25 search hints
# ---------------------------------------------------------------------------

_SEARCH_HINTS: dict[str, str] = {
    "calculate_curl": "vorticity rotation circulation wind curl cross product compute vector field zeta",
    "calculate_divergence": "compression expansion source sink wind divergence",
    "calculate_gradient": "spatial derivative slope field gradient",
    "calculate_azimuthal_mean": "radial profile cyclone storm azimuthal",
    "calculate_zonal_mean": "latitudinal average belt zonal",
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
        profile: ``"core"`` for the small default surface (~27 tools),
            ``"deferred-full"`` for the complete pool (core visible,
            30 raw tools deferred, ``discover_tools`` added).
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
        registry.enable_tool_discovery()

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
    missing = public - registered
    if missing:
        raise RuntimeError(
            f"Namespace plan out of date — {len(missing)} public tools "
            f"unaccounted: {sorted(missing)}. Update _DEFERRED_TOOLS."
        )
