"""Runner for the heavy benchmark suites.

These are deliberately *not* pytest tests: they build multi-hundred-thousand
face meshes and run real UXarray compute, which takes minutes and hundreds of
MB.  The unit suite mocks the UXarray layer, so it cannot catch the class of
bug this runner targets -- wrong-but-plausible numbers.

Usage
-----
    uv run python benchmarks/heavy/runner.py --suite healpix
    uv run python benchmarks/heavy/runner.py --suite pipeline --scale small
    uv run python benchmarks/heavy/runner.py --suite all --remote --endpoint chrysalis

Results are written to ``benchmarks/heavy/results/<suite>-<venue>.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from cases.healpix_cases import HEALPIX_PIPELINE  # noqa: E402
from cases.pipeline_cases import PIPELINE, Ctx  # noqa: E402
from checks import run_checks  # noqa: E402
from meshgen import build_healpix_data, build_quad_mesh  # noqa: E402

#: Mesh sizes per scale.  ``small`` is for a quick smoke pass; ``large`` is the
#: real workload.
SCALES = {
    "small": {"quad": (90, 45, 4), "healpix_zoom": 3, "healpix_time": 4},
    "medium": {"quad": (180, 90, 8), "healpix_zoom": 5, "healpix_time": 8},
    "large": {"quad": (360, 180, 12), "healpix_zoom": 6, "healpix_time": 12},
}


def _fmt(seconds: float) -> str:
    return f"{seconds:6.1f}s"


def run_suite(
    name: str,
    pipeline: list,
    ctx: Ctx,
    *,
    remote: bool,
) -> dict[str, Any]:
    """Execute one suite, collecting timings, failures, and check problems."""
    records: list[dict[str, Any]] = []
    print(f"\n=== suite: {name}  ({'remote' if remote else 'local'}) ===")
    print(f"    grid={ctx.grid_path}")
    print(f"    data={ctx.data_path}\n")

    for case_name, fn in pipeline:
        started = time.time()
        record: dict[str, Any] = {"case": case_name}
        try:
            result = fn(ctx)
            elapsed = time.time() - started
            problems = run_checks(case_name, result, remote=remote)
            # Cases that self-report (sweeps, parsing) carry their own list.
            if isinstance(result, dict):
                problems = list(problems) + list(result.get("problems") or [])
            record.update(
                status="ok" if not problems else "checks_failed",
                seconds=round(elapsed, 2),
                problems=problems,
            )
            flag = "OK  " if not problems else "CHECK"
            print(f"[{flag}] {case_name:26} {_fmt(elapsed)}")
            for problem in problems:
                print(f"         ! {problem}")
        except Exception as exc:  # noqa: BLE001 - a benchmark reports, never aborts
            elapsed = time.time() - started
            record.update(
                status="error",
                seconds=round(elapsed, 2),
                error=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(limit=6),
            )
            print(f"[FAIL] {case_name:26} {_fmt(elapsed)} {type(exc).__name__}: {exc}")
        records.append(record)

    return {"suite": name, "remote": remote, "cases": records}


def summarize(reports: list[dict[str, Any]]) -> int:
    """Print a compact summary; return the intended process exit code."""
    print("\n" + "=" * 62)
    bad = 0
    for report in reports:
        cases = report["cases"]
        ok = sum(1 for c in cases if c["status"] == "ok")
        checked = sum(1 for c in cases if c["status"] == "checks_failed")
        errored = sum(1 for c in cases if c["status"] == "error")
        slowest = sorted(cases, key=lambda c: -c.get("seconds", 0))[:3]
        bad += checked + errored
        print(
            f"{report['suite']:>10} "
            f"({'remote' if report['remote'] else 'local':>6}): "
            f"{ok} ok, {checked} check-failed, {errored} error"
        )
        print(
            "            slowest: "
            + ", ".join(f"{c['case']} {c.get('seconds', 0)}s" for c in slowest)
        )
    print("=" * 62)
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite", choices=("healpix", "pipeline", "all"), default="all"
    )
    parser.add_argument("--scale", choices=tuple(SCALES), default="medium")
    parser.add_argument(
        "--remote", action="store_true", help="run cases with use_remote=True"
    )
    parser.add_argument("--endpoint", default=None, help="endpoint name for --remote")
    parser.add_argument(
        "--keep-meshes",
        action="store_true",
        default=True,
        help="reuse meshes already present in benchmarks/heavy/meshes",
    )
    args = parser.parse_args()

    scale = SCALES[args.scale]
    meshes = HERE / "meshes"
    results_dir = HERE / "results"
    meshes.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    remote_kwargs: dict[str, Any] = {}
    if args.remote:
        remote_kwargs["use_remote"] = True
        if args.endpoint:
            remote_kwargs["endpoint"] = args.endpoint

    reports: list[dict[str, Any]] = []

    if args.suite in ("healpix", "all"):
        zoom = scale["healpix_zoom"]
        outdir = meshes / f"healpix_z{zoom}"
        data_file = outdir / f"healpix_z{zoom}_data.nc"
        if not (args.keep_meshes and data_file.exists()):
            print(f"building HEALPix z{zoom} data ...")
            info = build_healpix_data(
                str(outdir), zoom=zoom, ntime=scale["healpix_time"]
            )
            print(f"  {info}")
        ctx = Ctx(
            grid_path=f"healpix:{zoom}",
            data_path=str(data_file),
            remote_kwargs=remote_kwargs,
        )
        reports.append(run_suite("healpix", HEALPIX_PIPELINE, ctx, remote=args.remote))

    if args.suite in ("pipeline", "all"):
        nlon, nlat, ntime = scale["quad"]
        outdir = meshes / f"quad_{nlon}x{nlat}"
        grid_file, data_file = outdir / "grid.nc", outdir / "data.nc"
        if not (args.keep_meshes and grid_file.exists() and data_file.exists()):
            print(f"building quad mesh {nlon}x{nlat} ...")
            info = build_quad_mesh(str(outdir), nlon=nlon, nlat=nlat, ntime=ntime)
            print(f"  {info}")
        ctx = Ctx(
            grid_path=str(grid_file),
            data_path=str(data_file),
            remote_kwargs=remote_kwargs,
        )
        reports.append(run_suite("pipeline", PIPELINE, ctx, remote=args.remote))

    venue = f"remote-{args.endpoint or 'default'}" if args.remote else "local"
    for report in reports:
        out = results_dir / f"{report['suite']}-{venue}.json"
        out.write_text(json.dumps(report, indent=2, default=str))
        print(f"wrote {out.relative_to(HERE.parent.parent)}")

    return summarize(reports)


if __name__ == "__main__":
    raise SystemExit(main())
