"""Measure what a reply costs the caller, and where the bytes go.

Every result this server returns is carried in the conversation and re-sent
on each later turn, so its size is paid for repeatedly. ``tests/
test_payload_budget.py`` turns that into a ratchet with a pass/fail number
per operation; this script is the other half, the one that says *why* a
number is what it is -- which key holds the bytes, and how much of the reply
is answer rather than envelope.

It uses the same fixtures as the budget test on purpose, so a figure printed
here and a budget asserted there describe the same payload.

Bytes are exact. Tokens are not: they depend on the tokenizer, and this
repository does not depend on one. With ``tiktoken`` installed the counts
are real and the encoding is named in the output; without it the token
columns are omitted rather than estimated from a bytes-per-token ratio that
would be wrong for every caller who does not share our guess.

Usage::

    uv run python scripts/measure_payload.py
    uv run python scripts/measure_payload.py --json
    uv run --with tiktoken python scripts/measure_payload.py
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import tempfile
import warnings
from typing import Any, Callable

#: Categories match ``tests/test_payload_budget.py``. ``preconditions``,
#: ``postconditions`` and ``scientific_status`` count as signal: they are the
#: checked answer, not decoration around it.
CATEGORY = {
    "_provenance": "provenance",
    "recommended_next_steps": "advice",
    "preconditions": "checks",
    "postconditions": "checks",
    "scientific_status": "status",
    "grid_info": "grid_info",
}

SIGNAL_CATEGORIES = ("answer", "checks", "status")

#: Earth's mean radius, so ``calculate_area`` measures a completed payload
#: rather than the refusal it returns without a radius.
EARTH_RADIUS_M = 6371000.0


def _category(key: str) -> str:
    return CATEGORY.get(key, "answer")


def _size(obj: Any) -> int:
    return len(json.dumps(obj, default=str))


def _load_tokenizer() -> tuple[Callable[[str], int] | None, str | None]:
    """A real token counter, or nothing.

    Returning ``None`` is deliberate. A bytes-per-token constant looks like a
    measurement and is not one; the ratio moves with how much of a payload is
    JSON punctuation, and this server's replies are unusually punctuation-
    heavy.
    """
    try:
        import tiktoken
    except ImportError:
        return None, None
    encoding = tiktoken.get_encoding("cl100k_base")
    return (lambda text: len(encoding.encode(text))), "cl100k_base"


def build_fixtures(tmp_dir: str) -> tuple[str, str]:
    """A 162-face global mesh and one face-centred field on it."""
    import numpy as np
    import uxarray as ux
    import xarray as xr

    grid = ux.Grid.from_structured(
        lon=np.arange(0, 360, 20.0), lat=np.arange(-80, 81, 20.0)
    )
    grid_file = os.path.join(tmp_dir, "grid.nc")
    data_file = os.path.join(tmp_dir, "data.nc")
    grid.to_xarray().to_netcdf(grid_file)
    rng = np.random.default_rng(11)
    xr.Dataset(
        {"temperature": (["n_face"], 250 + 30 * rng.random(int(grid.n_face)))}
    ).to_netcdf(data_file)
    return grid_file, data_file


def measure(grid_file: str, data_file: str) -> dict[str, dict[str, Any]]:
    """Run one call per operation family and take each reply apart."""
    from uxarray_mcp.tools.frontdoor import run_analysis

    calls: dict[str, dict[str, Any]] = {
        "inspect_mesh": {},
        "calculate_area": {"sphere_radius": EARTH_RADIUS_M},
        "inspect_variable": {"variable_name": "temperature", "data_path": data_file},
        "calculate_zonal_mean": {
            "variable_name": "temperature",
            "data_path": data_file,
        },
        "validate_dataset": {"data_path": data_file},
    }

    measured: dict[str, dict[str, Any]] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for operation, kwargs in calls.items():
            result = run_analysis(operation=operation, grid_path=grid_file, **kwargs)
            per_key = {key: _size({key: value}) for key, value in result.items()}
            per_category: collections.Counter[str] = collections.Counter()
            for key, size in per_key.items():
                per_category[_category(key)] += size
            measured[operation] = {
                "bytes": _size(result),
                "per_key": per_key,
                "per_category": dict(per_category),
                "signal_bytes": sum(per_category[c] for c in SIGNAL_CATEGORIES),
                "serialized": json.dumps(result, default=str),
            }
    return measured


def measure_catalog() -> dict[str, Any]:
    """How much context the tool catalog itself occupies before any call."""
    from uxarray_mcp.app import make_registry

    schemas = {
        schema.get("function", schema)["name"]: schema
        for schema in make_registry().get_schemas()
    }
    by_name = {name: _size(schema) for name, schema in schemas.items()}
    total = sum(by_name.values())
    ordered = sorted(by_name.values())
    run_analysis_schema = schemas["run_analysis"]
    return {
        "n_tools": len(schemas),
        "bytes": total,
        "mean_bytes": total // len(schemas),
        "median_bytes": ordered[len(ordered) // 2],
        "largest": sorted(by_name.items(), key=lambda kv: -kv[1])[:5],
        "run_analysis_params": len(
            run_analysis_schema.get("function", run_analysis_schema)["parameters"][
                "properties"
            ]
        ),
    }


def _report(
    measured: dict[str, dict[str, Any]],
    catalog: dict[str, Any],
    count_tokens: Callable[[str], int] | None,
    encoding_name: str | None,
) -> None:
    rule = "=" * 74
    print(rule)
    if count_tokens is None:
        print("tokens: not counted (install tiktoken to count them)")
    else:
        print(f"tokens: {encoding_name}")
    header = f"{'operation':24s} {'bytes':>7s} {'signal%':>8s}"
    if count_tokens is not None:
        header += f" {'tokens':>7s} {'B/token':>8s}"
    print(header)

    for operation, entry in measured.items():
        total = entry["bytes"]
        line = f"{operation:24s} {total:7d} {100 * entry['signal_bytes'] / total:7.1f}%"
        if count_tokens is not None:
            tokens = count_tokens(entry["serialized"])
            entry["tokens"] = tokens
            line += f" {tokens:7d} {total / tokens:8.2f}"
        print(line)

    pooled: collections.Counter[str] = collections.Counter()
    for entry in measured.values():
        pooled.update(entry["per_category"])
    grand = sum(pooled.values())
    print("-" * 74)
    print(f"POOLED over {len(measured)} replies: {grand} bytes")
    for category, size in pooled.most_common():
        print(f"   {category:14s} {size:6d} B   {100 * size / grand:5.1f}%")

    print(rule)
    print("calculate_area key breakdown:")
    for key, size in sorted(
        measured["calculate_area"]["per_key"].items(), key=lambda kv: -kv[1]
    ):
        print(f"   {key:26s} {size:5d} B")

    print(rule)
    print(
        f"TOOL CATALOG: {catalog['n_tools']} tools, {catalog['bytes']} B "
        f"(mean {catalog['mean_bytes']} B, median {catalog['median_bytes']} B)"
    )
    if count_tokens is not None:
        print(f"   run_analysis params: {catalog['run_analysis_params']}")
    for name, size in catalog["largest"]:
        print(
            f"   {name:26s} {size:6d} B   "
            f"{100 * size / catalog['bytes']:5.1f}% of catalog"
        )
    three_tools = 3 * catalog["bytes"] // catalog["n_tools"]
    print(
        f"RETRIEVAL: 3 tools ~= {three_tools} B vs {catalog['bytes']} B full "
        f"catalog = {100 * (1 - 3 / catalog['n_tools']):.1f}% reduction"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the measurements as JSON instead of a table",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault(
        "UXARRAY_MCP_STATE_DIR", tempfile.mkdtemp(prefix="payload-state")
    )
    tmp_dir = tempfile.mkdtemp(prefix="payload")
    grid_file, data_file = build_fixtures(tmp_dir)
    measured = measure(grid_file, data_file)
    catalog = measure_catalog()
    count_tokens, encoding_name = _load_tokenizer()

    if args.json:
        if count_tokens is not None:
            for entry in measured.values():
                entry["tokens"] = count_tokens(entry["serialized"])
        for entry in measured.values():
            # The full payload is reproducible from the fixtures and would
            # dominate the output.
            entry.pop("serialized", None)
        print(
            json.dumps(
                {
                    "token_encoding": encoding_name,
                    "operations": measured,
                    "catalog": catalog,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    _report(measured, catalog, count_tokens, encoding_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
