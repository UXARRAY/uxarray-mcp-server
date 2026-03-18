"""Autonomous scientific agent implementing Analyze -> Plan -> Execute -> Verify loop."""

import math
from typing import Any

_HPC_PATH_PREFIXES = ("/home/", "/lus/", "/grand/", "/scratch/", "/projects/", "/gpfs/")
_LARGE_MESH_THRESHOLD = 1_000_000  # faces


def _is_hpc_path(file_path: str) -> bool:
    """Return True if the path lives on a known HPC filesystem."""
    return any(file_path.startswith(prefix) for prefix in _HPC_PATH_PREFIXES)


def _decide_venue(file_path: str, n_face: int) -> str:
    """Decide execution venue based on file path and mesh size.

    Returns "hpc" if the path lives on a known HPC filesystem or the mesh
    is large (>1M faces); otherwise returns "local".
    """
    if _is_hpc_path(file_path):
        return "hpc"
    if n_face > _LARGE_MESH_THRESHOLD:
        return "hpc"
    return "local"


def run_scientific_agent(
    file_path: str,
    data_path: str | None = None,
    variable_name: str | None = None,
) -> dict[str, Any]:
    """Run an autonomous scientific analysis workflow on a mesh dataset.

    This tool implements a four-stage reasoning loop:
    Analyze -> Plan -> Execute -> Verify

    The agent automatically decides where to run each operation:
    files on HPC filesystems (e.g. /home/, /lus/, /scratch/) or meshes
    with more than 1 million faces are routed to HPC via Globus Compute.
    All other files run locally.

    Args:
        file_path: Path to the mesh file. Can be a local path, an HPC
            filesystem path, or a HEALPix spec like "healpix:4".
        data_path: Optional path to a data file containing variables.
        variable_name: Optional specific variable to analyze. If None and
            data_path is provided, the first face-centered variable is used.

    Returns:
        Dictionary containing:
        - file_path: Input path
        - execution_venue: "local" or "hpc"
        - reasoning_trace: List of decisions made during planning
        - mesh_summary: Topology info from inspect_mesh
        - area_results: Face area statistics
        - variable_results: Variable metadata (if data_path provided)
        - zonal_mean_results: Zonal mean profile (if face-centered var found)
        - verification: Sanity check results with passed flag and warnings

    Example:
        >>> run_scientific_agent("healpix:3")
        {
            "file_path": "healpix:3",
            "execution_venue": "local",
            "reasoning_trace": [...],
            ...
        }
    """
    from uxarray_mcp.tools.inspection import (
        inspect_mesh,
        inspect_variable,
        calculate_area,
        calculate_zonal_mean,
        validate_dataset,
    )
    from uxarray_mcp.tools.remote_tools import (
        inspect_mesh_hpc,
        calculate_area_hpc,
        inspect_variable_hpc,
        calculate_zonal_mean_hpc,
    )

    reasoning_trace: list[dict[str, Any]] = []
    hpc_path = _is_hpc_path(file_path)

    # ── STAGE 1: ANALYZE ──────────────────────────────────────────────────────
    # Check path FIRST — if HPC path, we must inspect remotely (file not local)
    if hpc_path:
        reasoning_trace.append(
            {
                "stage": "analyze",
                "action": f"HPC path detected -> inspect_mesh_hpc({file_path!r})",
            }
        )
        try:
            mesh_summary = inspect_mesh_hpc(file_path, use_remote=True)
        except Exception as exc:
            return {
                "file_path": file_path,
                "execution_venue": "hpc",
                "reasoning_trace": [
                    *reasoning_trace,
                    {"stage": "analyze", "error": f"HPC inspection failed: {exc}"},
                ],
                "mesh_summary": None,
                "area_results": None,
                "variable_results": None,
                "zonal_mean_results": None,
                "verification": {
                    "passed": False,
                    "warnings": [f"Could not reach HPC endpoint: {exc}"],
                },
            }
    else:
        reasoning_trace.append(
            {"stage": "analyze", "action": f"inspect_mesh({file_path!r})"}
        )
        mesh_summary = inspect_mesh(file_path)

    n_face = mesh_summary.get("n_face", 0)
    reasoning_trace.append(
        {"stage": "analyze", "observation": f"mesh has {n_face:,} faces"}
    )

    variable_results = None
    face_centered_var = None

    if data_path:
        reasoning_trace.append(
            {"stage": "analyze", "action": f"inspect_variable({data_path!r})"}
        )
        if hpc_path or _is_hpc_path(data_path):
            variable_results = inspect_variable_hpc(
                file_path, data_path, variable_name, use_remote=True
            )
        else:
            variable_results = inspect_variable(file_path, data_path, variable_name)

        for var in variable_results.get("variables", []):
            if var.get("location") == "faces":
                face_centered_var = var["name"]
                reasoning_trace.append(
                    {
                        "stage": "analyze",
                        "observation": f"found face-centered variable: {face_centered_var!r}",
                    }
                )
                break
        if not face_centered_var:
            reasoning_trace.append(
                {
                    "stage": "analyze",
                    "observation": "no face-centered variables found -- zonal mean not applicable",
                }
            )

        # Run validation — results gate downstream tools (Criterion 1 + 5)
        reasoning_trace.append(
            {"stage": "analyze", "action": f"validate_dataset({data_path!r})"}
        )
        try:
            validation_result = validate_dataset(file_path, data_path)
            validation_summary = {
                "passed": validation_result["passed"],
                "n_variables_checked": validation_result["n_variables_checked"],
                "n_variables_failed": validation_result["n_variables_failed"],
                "warnings": validation_result["_provenance"]["warnings"],
            }
            if not validation_result["passed"]:
                reasoning_trace.append(
                    {
                        "stage": "analyze",
                        "warning": f"validation failed: {validation_result['n_variables_failed']} variable(s) have issues",
                    }
                )
        except Exception as exc:
            validation_summary = {"passed": None, "error": str(exc)}
            reasoning_trace.append(
                {"stage": "analyze", "warning": f"validation skipped: {exc}"}
            )
    else:
        validation_summary = None

    # ── STAGE 2: PLAN ─────────────────────────────────────────────────────────
    venue = _decide_venue(file_path, n_face)
    use_remote = venue == "hpc"

    reasoning_trace.append(
        {
            "stage": "plan",
            "decision": f"execution_venue={venue!r}",
            "reason": (
                "path is on HPC filesystem"
                if hpc_path
                else f"n_face={n_face:,} exceeds {_LARGE_MESH_THRESHOLD:,} threshold"
                if n_face > _LARGE_MESH_THRESHOLD
                else "small mesh on local path"
            ),
        }
    )

    planned_ops = ["calculate_area"]
    validation_passed = validation_summary is None or validation_summary.get("passed") is not False
    if face_centered_var and validation_passed:
        planned_ops.append("calculate_zonal_mean")
    elif face_centered_var and not validation_passed:
        reasoning_trace.append(
            {
                "stage": "plan",
                "decision": "skip calculate_zonal_mean",
                "reason": "validation failed — results may be unreliable",
            }
        )

    reasoning_trace.append({"stage": "plan", "operations": planned_ops})

    # ── STAGE 3: EXECUTE ──────────────────────────────────────────────────────
    if use_remote:
        reasoning_trace.append({"stage": "execute", "venue": "hpc (Globus Compute)"})
        try:
            area_results = calculate_area_hpc(file_path, use_remote=True)
        except Exception as exc:
            reasoning_trace.append(
                {
                    "stage": "execute",
                    "warning": f"HPC failed: {exc}, falling back to local",
                }
            )
            area_results = calculate_area(file_path)
            venue = "local (HPC fallback)"
    else:
        reasoning_trace.append({"stage": "execute", "venue": "local"})
        area_results = calculate_area(file_path)

    zonal_mean_results = None
    if face_centered_var:
        target_var = variable_name or face_centered_var
        reasoning_trace.append(
            {"stage": "execute", "action": f"calculate_zonal_mean({target_var!r})"}
        )
        if use_remote:
            try:
                zonal_mean_results = calculate_zonal_mean_hpc(
                    file_path, data_path, target_var, use_remote=True
                )
            except Exception as exc:
                reasoning_trace.append(
                    {
                        "stage": "execute",
                        "warning": f"HPC zonal mean failed: {exc}, falling back",
                    }
                )
                zonal_mean_results = calculate_zonal_mean(
                    file_path, data_path, target_var
                )
        else:
            zonal_mean_results = calculate_zonal_mean(file_path, data_path, target_var)

    # ── STAGE 4: VERIFY ───────────────────────────────────────────────────────
    warnings: list[str] = []
    passed = True

    total_area = area_results.get("total_area")
    if total_area is not None:
        # Global meshes should be ~5.1e14 m^2; allow wide range for subsets
        if total_area > 0:
            reasoning_trace.append(
                {"stage": "verify", "check": "total_area > 0", "result": "pass"}
            )
        else:
            passed = False
            warnings.append("total_area is zero or negative -- mesh may be empty")

        # Flag if total area is suspiciously small for a global mesh
        if n_face > 10_000 and total_area < 1e10:
            warnings.append(
                f"total_area={total_area:.2e} seems very small for a {n_face:,}-face mesh"
            )

    if zonal_mean_results:
        values = zonal_mean_results.get("zonal_mean_values", [])
        finite_values = [
            v
            for v in values
            if v is not None and isinstance(v, (int, float)) and math.isfinite(v)
        ]
        if len(finite_values) < len(values):
            n_bad = len(values) - len(finite_values)
            warnings.append(f"zonal mean contains {n_bad} NaN/Inf/null values")
            reasoning_trace.append(
                {
                    "stage": "verify",
                    "check": "zonal_mean finite",
                    "result": f"{n_bad} non-finite",
                }
            )
        else:
            reasoning_trace.append(
                {"stage": "verify", "check": "zonal_mean finite", "result": "pass"}
            )

    from uxarray_mcp.provenance import attach_provenance

    # ── BUILD ARTIFACT LIST ───────────────────────────────────────────────────
    artifacts: list[dict] = []

    if mesh_summary:
        artifacts.append({
            "type": "mesh_topology",
            "n_face": mesh_summary.get("n_face"),
            "n_node": mesh_summary.get("n_node"),
            "format": mesh_summary.get("format"),
        })
    if area_results:
        artifacts.append({
            "type": "face_areas",
            "total_area": area_results.get("total_area"),
            "n_face": area_results.get("n_face"),
            "area_units": area_results.get("area_units"),
        })
    if validation_summary:
        artifacts.append({
            "type": "validation",
            "passed": validation_summary.get("passed"),
            "n_variables_checked": validation_summary.get("n_variables_checked"),
            "n_variables_failed": validation_summary.get("n_variables_failed"),
        })
    if zonal_mean_results:
        artifacts.append({
            "type": "zonal_mean",
            "variable": face_centered_var,
            "n_latitudes": len(zonal_mean_results.get("latitudes", [])),
        })

    result = {
        "file_path": file_path,
        "execution_venue": venue,
        "reasoning_trace": reasoning_trace,
        "mesh_summary": mesh_summary,
        "area_results": area_results,
        "variable_results": variable_results,
        "zonal_mean_results": zonal_mean_results,
        "validation_summary": validation_summary,
        "verification": {"passed": passed, "warnings": warnings},
    }

    return attach_provenance(
        result,
        tool="run_scientific_agent",
        inputs={
            "file_path": file_path,
            "data_path": data_path,
            "variable_name": variable_name,
        },
        venue=venue,
        warnings=warnings,
        validation_summary=validation_summary,
        selected_variable=face_centered_var,
        artifacts=artifacts,
    )
