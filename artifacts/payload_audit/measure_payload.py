"""Re-measure reply payload composition and tool-catalog size on the current tree.

Mirrors tests/test_payload_budget.py fixtures so the numbers are reproducible.
Emits the exact figures quoted on the SC26 poster.
"""
from __future__ import annotations

import json, warnings, tempfile, os, collections
import numpy as np, xarray as xr, uxarray as ux

os.environ.setdefault("UXARRAY_MCP_STATE_DIR", tempfile.mkdtemp(prefix="paystate"))
from uxarray_mcp.tools.frontdoor import run_analysis  # noqa: E402

tmp = tempfile.mkdtemp(prefix="payload")
lon = np.arange(0, 360, 20.0); lat = np.arange(-80, 81, 20.0)
grid = ux.Grid.from_structured(lon=lon, lat=lat)
grid_file = os.path.join(tmp, "grid.nc"); data_file = os.path.join(tmp, "data.nc")
grid.to_xarray().to_netcdf(grid_file)
rng = np.random.default_rng(11)
xr.Dataset({"temperature": (["n_face"], 250 + 30 * rng.random(grid.n_face))}).to_netcdf(data_file)

CALLS = {
    "inspect_mesh": {},
    "calculate_area": {},
    "inspect_variable": {"variable_name": "temperature", "data_path": data_file},
    "calculate_zonal_mean": {"variable_name": "temperature", "data_path": data_file},
    "validate_dataset": {"data_path": data_file},
}

# key -> category
# Categories follow tests/test_payload_budget.py: preconditions/postconditions/
# scientific_status are SIGNAL (they are the checked answer), _provenance and
# recommended_next_steps are envelope.
CATEGORY = {
    "_provenance": "provenance",
    "recommended_next_steps": "advice",
    "preconditions": "checks",
    "postconditions": "checks",
    "scientific_status": "status",
    "grid_info": "grid_info",
}
def cat(k): return CATEGORY.get(k, "answer")

results, sizes = {}, {}
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for op, kw in CALLS.items():
        results[op] = run_analysis(operation=op, grid_path=grid_file, **kw)

pool = collections.Counter()
print("=" * 74)
print(f"{'operation':24s} {'bytes':>7s}  {'signal%':>8s}  {'status B':>8s}")
for op, res in results.items():
    total = len(json.dumps(res, default=str))
    sizes[op] = total
    per = collections.Counter()
    for k, v in res.items():
        per[cat(k)] += len(json.dumps({k: v}, default=str))
        pool[cat(k)] += len(json.dumps({k: v}, default=str))
    signal = per["answer"] + per["checks"] + per["status"]
    status_b = len(json.dumps({"scientific_status": res["scientific_status"]}, default=str)) if "scientific_status" in res else 0
    print(f"{op:24s} {total:7d}  {100*signal/total:7.1f}%  {status_b:8d}")

print("-" * 74)
grand = sum(pool.values())
print(f"POOLED over {len(results)} replies: {grand} bytes")
for k, v in pool.most_common():
    print(f"   {k:14s} {v:6d} B   {100*v/grand:5.1f}%")

print("=" * 74)
print("calculate_area key breakdown:")
area = results["calculate_area"]
for k, v in sorted(area.items(), key=lambda kv: -len(json.dumps({kv[0]: kv[1]}, default=str))):
    print(f"   {k:26s} {len(json.dumps({k: v}, default=str)):5d} B")

from uxarray_mcp.app import make_registry  # noqa: E402
schemas = {s.get("function", s)["name"]: s for s in make_registry().get_schemas()}
tot = sum(len(json.dumps(s)) for s in schemas.values())
byname = sorted(((len(json.dumps(s)), n) for n, s in schemas.items()), reverse=True)
med = sorted(b for b, _ in byname)[len(byname) // 2]
print("=" * 74)
print(f"TOOL CATALOG: {len(schemas)} tools, {tot} B  (mean {tot//len(schemas)} B, median {med} B)")
for b, n in byname[:5]:
    print(f"   {n:26s} {b:6d} B   {100*b/tot:5.1f}% of catalog")
ra = schemas["run_analysis"]
nparams = len(ra.get("function", ra)["parameters"]["properties"])
print(f"   run_analysis params: {nparams}")
print(f"RETRIEVAL: 3 tools ~= {3*tot//len(schemas)} B vs {tot} B full catalog "
      f"= {100*(1-3/len(schemas)):.1f}% reduction")
