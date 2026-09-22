#!/usr/bin/env python3
"""Exercise the server the way an agent does: through its tools, only.

Why this exists. While debugging a 63 GB SCRIP mesh on a cluster I wrote ten
throwaway ``globus_compute_sdk`` scripts -- shipping my own functions to the
worker and reading the answers directly. Every one of them proved something
about *uxarray* and nothing about *this server*, and the gaps they papered
over were real: ``get_capabilities`` did not mention conservative remapping,
and no tool reported that the worker was running months-old server code. Both
were invisible precisely because nobody was going through the front door.

So this script takes the questions that debugging session actually asked and
answers each one with a tool call. If a question cannot be answered that way,
that is a finding, and it is reported as one rather than worked around.

    python scripts/exercise_tools.py                       # local only
    python scripts/exercise_tools.py --endpoint chrysalis  # add remote checks
    python scripts/exercise_tools.py --json                # machine-readable

Exit status is 0 when every question was answerable through a tool, 1
otherwise. Nothing here mutates state: it inspects, plans and reports.
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from typing import Any, Callable

# Each entry is one question a scientist or agent would actually ask, the tool
# call that should answer it, and a predicate deciding whether the answer is
# usable. The predicate is the point: "the call returned" is not the same as
# "the caller learned what they asked".
Check = tuple[str, str, Callable[[], Any], Callable[[Any], tuple[bool, str]]]


def _ok(detail: str = "") -> tuple[bool, str]:
    return True, detail


def _no(detail: str) -> tuple[bool, str]:
    return False, detail


# ---------------------------------------------------------------------------
# Local questions
# ---------------------------------------------------------------------------


def _local_checks() -> list[Check]:
    from uxarray_mcp.tools.capabilities import get_capabilities
    from uxarray_mcp.tools.frontdoor import run_analysis

    def q_what_can_i_do() -> Any:
        return get_capabilities("healpix:2")

    def a_what_can_i_do(r: Any) -> tuple[bool, str]:
        tools = [t["name"] for t in r["mcp_server_tools"] if t["applicable"]]
        if not tools:
            return _no("no applicable tools reported for a valid mesh")
        return _ok(
            f"{len(tools)} applicable tools, n_face={r['grid_summary']['n_face']}"
        )

    def q_how_do_i_remap_a_flux() -> Any:
        return get_capabilities("healpix:2")["uxarray_capabilities"]["remapping"]

    def a_how_do_i_remap_a_flux(lines: Any) -> tuple[bool, str]:
        # The honest answer is "conservatively"; if the catalogue does not say
        # so, an agent will pick something that does not conserve.
        conservative = [ln for ln in lines if "conservative" in ln]
        if not conservative:
            return _no(
                "conservative remapping is not advertised, so an agent asking "
                "how to remap a flux is told only about methods that do not "
                "preserve the areal integral"
            )
        if not all('backend="yac"' in ln for ln in conservative):
            return _no(f"advertised without the backend argument: {conservative}")
        return _ok(conservative[0].strip())

    def q_which_operations_exist() -> Any:
        import inspect

        return inspect.getdoc(run_analysis) or ""

    def a_which_operations_exist(doc: Any) -> tuple[bool, str]:
        expected = ("remap_variable", "gradient", "curl", "divergence", "subset_bbox")
        missing = [op for op in expected if op not in doc]
        if missing:
            return _no(f"run_analysis docstring does not mention {missing}")
        return _ok(f"documents {len(expected)} of the operations checked")

    def q_does_conservative_actually_conserve() -> Any:
        """The claim the whole YAC build exists to support, measured."""
        import importlib.util
        import tempfile
        from pathlib import Path

        if importlib.util.find_spec("yac") is None:
            return {"skipped": "yac not importable in this interpreter"}

        import numpy as np
        import uxarray as ux
        import xarray as xr

        from uxarray_mcp.tools.frontdoor import get_result

        tmp = Path(tempfile.mkdtemp())
        fine, coarse = ux.Grid.from_healpix(3), ux.Grid.from_healpix(2)
        for g in (fine, coarse):
            _ = g.node_lon, g.node_lat, g.face_node_connectivity
        fine.to_xarray().to_netcdf(tmp / "fine.nc")
        coarse.to_xarray().to_netcdf(tmp / "coarse.nc")

        lat = np.asarray(fine.face_lat.values)
        values = 10.0 + 5.0 * np.cos(np.deg2rad(lat))
        ds = fine.to_xarray()
        ds["flux"] = (("n_face",), values)
        ds.to_netcdf(tmp / "field.nc")
        source_mean = float(values.mean())

        drifts: dict[str, float] = {}
        for method in ("conservative", "nearest_neighbor"):
            res = run_analysis(
                "remap_variable",
                grid_path=str(tmp / "fine.nc"),
                data_path=str(tmp / "field.nc"),
                variable_name="flux",
                target_grid_path=str(tmp / "coarse.nc"),
                method=method,
            )
            handle = get_result(res["result_handle"])
            mean = float(xr.open_dataset(handle["artifact_path"])["flux"].values.mean())
            drifts[method] = abs(mean - source_mean) / source_mean * 100
            drifts[f"{method}_backend"] = res["backend"]
        return drifts

    def a_does_conservative_actually_conserve(r: Any) -> tuple[bool, str]:
        if "skipped" in r:
            return _ok(f"skipped: {r['skipped']}")
        if r.get("conservative_backend") != "yac":
            return _no(
                "method='conservative' did not route to the YAC backend "
                f"(got {r.get('conservative_backend')!r}); a silent fallback "
                "would report a conservative remap that never ran"
            )
        if r["conservative"] >= r["nearest_neighbor"]:
            return _no(
                f"conservative drifted {r['conservative']:.4f}% vs nearest "
                f"neighbour {r['nearest_neighbor']:.4f}% -- the method chosen "
                "for flux work is losing to point sampling"
            )
        ratio = r["nearest_neighbor"] / r["conservative"]
        return _ok(
            f"conservative {r['conservative']:.4f}% vs nearest "
            f"{r['nearest_neighbor']:.4f}% drift ({ratio:.1f}x better)"
        )

    return [
        (
            "What can I do with this mesh?",
            "get_capabilities",
            q_what_can_i_do,
            a_what_can_i_do,
        ),
        (
            "How should I remap a flux?",
            "get_capabilities",
            q_how_do_i_remap_a_flux,
            a_how_do_i_remap_a_flux,
        ),
        (
            "Which operations does the front door expose?",
            "run_analysis",
            q_which_operations_exist,
            a_which_operations_exist,
        ),
        (
            "Does conservative remapping actually conserve?",
            "run_analysis + get_result",
            q_does_conservative_actually_conserve,
            a_does_conservative_actually_conserve,
        ),
    ]


# ---------------------------------------------------------------------------
# Remote questions -- the ones the throwaway scripts were written for
# ---------------------------------------------------------------------------


def _remote_checks(endpoint: str) -> list[Check]:
    from uxarray_mcp.tools.execution_control import validate_hpc_setup
    from uxarray_mcp.tools.frontdoor import diagnose_endpoint

    def q_is_the_endpoint_up() -> Any:
        return diagnose_endpoint(action="status", endpoint=endpoint, use_remote=True)

    def a_is_the_endpoint_up(r: Any) -> tuple[bool, str]:
        rows = r.get("endpoints") or []
        if not rows:
            return _no("no endpoint rows returned")
        status = rows[0].get("status")
        if status not in ("active", "registered"):
            return _no(f"endpoint status is {status!r}")
        return _ok(f"status={status}, node={rows[0].get('node')}")

    def q_which_yac_is_the_worker_running() -> Any:
        return validate_hpc_setup(
            endpoint=endpoint, run_remote_probe=True, probe_timeout_seconds=180
        )

    def a_which_yac_is_the_worker_running(r: Any) -> tuple[bool, str]:
        probe = r.get("remote_probe") or {}
        yac = (probe.get("modules") or {}).get("yac") or {}
        if not yac.get("package_available"):
            return _no("worker reports no yac package")
        version = yac.get("version_from_path") or yac.get("version_from_metadata")
        if not version:
            return _no(
                "the worker has yac but no tool reports *which* version -- "
                "a stale build is indistinguishable from a current one"
            )
        return _ok(f"worker yac = {version}")

    def q_is_the_worker_running_current_server_code() -> Any:
        return validate_hpc_setup(
            endpoint=endpoint, run_remote_probe=True, probe_timeout_seconds=180
        )

    def a_is_the_worker_running_current_server_code(r: Any) -> tuple[bool, str]:
        from uxarray_mcp.provenance import _get_server_commit, _get_server_version

        runtime = (r.get("remote_probe") or {}).get("_worker_runtime") or {}
        worker = runtime.get("mcp_server_version")
        local = _get_server_version()
        if not worker or worker == "unknown":
            return _no(
                "the worker does not report its uxarray-mcp version, so a "
                "cluster running stale server code looks healthy"
            )
        if worker != local:
            return _no(
                f"worker is on uxarray-mcp {worker}, submitter on {local}. "
                "Fixes merged here are absent there; redeploy and restart."
            )

        # Matching versions are not enough. The string only moves at release,
        # so a worker many merges behind still reports the current number --
        # this check passed against a worker missing three merged PRs before
        # it compared commits.
        worker_commit = runtime.get("mcp_server_commit")
        local_commit = _get_server_commit()
        if not worker_commit or worker_commit == "unknown":
            return _no(
                f"both report {worker}, but the worker does not report a "
                "commit, so drift within a release is invisible"
            )
        if worker_commit != local_commit:
            return _no(
                f"both report {worker}, but the worker is at commit "
                f"{worker_commit} and the submitter at {local_commit}. "
                "Merged fixes are absent there; redeploy and restart."
            )
        return _ok(f"worker and submitter both on {worker} @ {worker_commit}")

    return [
        (
            "Is the endpoint reachable?",
            "diagnose_endpoint",
            q_is_the_endpoint_up,
            a_is_the_endpoint_up,
        ),
        (
            "Which YAC build will my remap use?",
            "validate_hpc_setup",
            q_which_yac_is_the_worker_running,
            a_which_yac_is_the_worker_running,
        ),
        (
            "Is the worker running current server code?",
            "validate_hpc_setup",
            q_is_the_worker_running_current_server_code,
            a_is_the_worker_running_current_server_code,
        ),
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--endpoint", help="also run the remote checks against this endpoint"
    )
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    checks = _local_checks()
    if args.endpoint:
        checks += _remote_checks(args.endpoint)

    rows: list[dict[str, Any]] = []
    for question, tool, call, judge in checks:
        started = time.perf_counter()
        try:
            answer = call()
            passed, detail = judge(answer)
            error = None
        except Exception as exc:
            passed, detail, error = (
                False,
                f"{type(exc).__name__}: {exc}",
                traceback.format_exc()[-800:],
            )
        rows.append(
            {
                "question": question,
                "tool": tool,
                "answerable": passed,
                "detail": detail,
                "seconds": round(time.perf_counter() - started, 2),
                **({"traceback": error} if error else {}),
            }
        )

    if args.json:
        print(json.dumps({"checks": rows}, indent=2))
    else:
        width = max(len(r["question"]) for r in rows)
        print()
        for r in rows:
            mark = "PASS" if r["answerable"] else "GAP "
            print(
                f"  [{mark}] {r['question']:<{width}}  ({r['tool']}, {r['seconds']}s)"
            )
            print(f"         {r['detail']}")
        gaps = [r for r in rows if not r["answerable"]]
        print()
        print(
            f"  {len(rows) - len(gaps)}/{len(rows)} questions answerable through tools"
        )
        if gaps:
            print("  Gaps are features the server does not yet expose:")
            for g in gaps:
                print(f"    - {g['question']}")
        print()

    return 0 if all(r["answerable"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
