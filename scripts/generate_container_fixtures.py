"""Generate the deterministic mesh fixtures baked into the container image.

Why this exists
---------------
The container has to ship *some* data or it is an empty tool surface: an agent
that can call ``run_analysis`` but has nothing to analyze cannot be evaluated,
demonstrated, or smoke-tested. Committing NetCDF binaries to git would be the
obvious alternative and is the wrong one -- they are opaque to review, they
bloat clones for every user who never runs the container, and a binary blob
gives a reader no way to see what is actually in the mesh.

So the image generates its fixtures at build time from this script. The source
of truth is code you can read, the artifact is a file the agent can open, and
the manifest records a hash for each one so a rebuild that silently changes the
data is detectable rather than invisible.

Determinism
-----------
Every field here is either analytic or drawn from a seeded ``default_rng``.
Two builds of the same commit produce byte-identical arrays. NetCDF headers can
still differ across library versions, so the manifest hashes the *array
contents*, not the file bytes -- see ``_content_digest``.

The fixture set mirrors the blind spots that ``tests/conftest.py`` exists to
cover, because a container whose only mesh sits on a unit sphere with one level
and no time axis hides exactly the bugs that matter:

- ``global``       -- coarse global mesh, unit sphere, the everyday case.
- ``earth_radius`` -- declares R = 6371 km, so a missing radius scaling is
                      visible in the numbers instead of hiding behind R = 1.
- ``multi_level``  -- four vertical levels separated by 100 per level, so a
                      wrong level selection is unmistakable.
- ``time_level``   -- three times x four levels, value ``1000*t + 100*(k+1)``:
                      the magnitude alone says which slice was taken.
- ``regional``     -- a sliver mesh, so remap-coverage failures have something
                      that a global target grid falls entirely outside of.

Usage::

    python3 scripts/generate_container_fixtures.py --outdir /data/uxarray
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

EARTH_RADIUS_M = 6371000.0


def _content_digest(path: Path) -> str:
    """Hash the decoded array contents of a NetCDF file.

    Hashing raw file bytes would make the manifest useless: NetCDF writers
    embed library versions and can reorder attributes, so the bytes drift
    across environments even when every number is identical. Hashing the
    decoded arrays instead answers the question we actually care about --
    "is this the same data?" -- and stays stable across netcdf4/h5netcdf
    versions.
    """
    digest = hashlib.sha256()
    with xr.open_dataset(path) as ds:
        for name in sorted(ds.variables):
            var = ds[name]
            digest.update(name.encode())
            digest.update(str(var.dims).encode())
            values = np.asarray(var.values)
            if values.dtype.kind in "SUO":
                digest.update(str(values.tolist()).encode())
            else:
                digest.update(np.ascontiguousarray(values).tobytes())
    return digest.hexdigest()


def _structured_grid(lon: np.ndarray, lat: np.ndarray):
    """Build a UGRID grid from a structured lon/lat product.

    ``Grid.from_structured`` is used rather than hand-rolled connectivity
    because its node coordinates survive a NetCDF round-trip intact, which
    hand-built meshes frequently do not.
    """
    import uxarray as ux

    return ux.Grid.from_structured(lon=lon, lat=lat)


def build_global(outdir: Path) -> dict[str, Any]:
    """Coarse global mesh (18x9 faces) with a face-centered temperature."""
    grid = _structured_grid(np.arange(0, 360, 20.0), np.arange(-80, 81, 20.0))
    grid_file = outdir / "global_grid.nc"
    data_file = outdir / "global_data.nc"

    grid.to_xarray().to_netcdf(grid_file)
    rng = np.random.default_rng(11)
    xr.Dataset(
        {
            "temperature": (
                ["n_face"],
                250 + 30 * rng.random(grid.n_face),
                {"units": "K", "long_name": "Air temperature"},
            )
        }
    ).to_netcdf(data_file)

    return {
        "name": "global",
        "description": "Coarse global UGRID mesh on a unit sphere, one face-centered field.",
        "grid": grid_file.name,
        "data": data_file.name,
        "n_face": int(grid.n_face),
        "variables": ["temperature"],
    }


def build_earth_radius(outdir: Path) -> dict[str, Any]:
    """Global mesh declaring a physical Earth radius, with u/v winds."""
    grid = _structured_grid(np.arange(0, 360, 20.0), np.arange(-80, 81, 20.0))
    grid_file = outdir / "earth_radius_grid.nc"
    data_file = outdir / "earth_radius_data.nc"

    grid_ds = grid.to_xarray()
    grid_ds.attrs["sphere_radius"] = EARTH_RADIUS_M
    grid_ds.to_netcdf(grid_file)

    rng = np.random.default_rng(23)
    xr.Dataset(
        {
            "u": (
                ["n_face"],
                10 * rng.standard_normal(grid.n_face),
                {"units": "m s-1", "long_name": "Zonal wind"},
            ),
            "v": (
                ["n_face"],
                10 * rng.standard_normal(grid.n_face),
                {"units": "m s-1", "long_name": "Meridional wind"},
            ),
        }
    ).to_netcdf(data_file)

    return {
        "name": "earth_radius",
        "description": (
            "Global mesh with sphere_radius = 6371 km and u/v winds. Use this "
            "for gradient, vorticity, and divergence -- a missing radius "
            "scaling changes the answer here, unlike on a unit sphere."
        ),
        "grid": grid_file.name,
        "data": data_file.name,
        "n_face": int(grid.n_face),
        "sphere_radius_m": EARTH_RADIUS_M,
        "variables": ["u", "v"],
    }


def build_multi_level(outdir: Path) -> dict[str, Any]:
    """Mesh plus a four-level field where each level is 100 apart."""
    grid = _structured_grid(np.arange(0, 360, 30.0), np.arange(-75, 76, 30.0))
    grid_file = outdir / "multi_level_grid.nc"
    data_file = outdir / "multi_level_data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    n_level = 4
    values = np.stack([np.full(grid.n_face, 100.0 * (k + 1)) for k in range(n_level)])
    xr.Dataset(
        {"temperature": (["n_level", "n_face"], values, {"units": "K"})},
        coords={"n_level": np.arange(n_level)},
    ).to_netcdf(data_file)

    return {
        "name": "multi_level",
        "description": (
            "Four vertical levels centered on 100, 200, 300, 400. A mean of "
            "~200 can only come from level 1, so a wrong level selection is "
            "unambiguous."
        ),
        "grid": grid_file.name,
        "data": data_file.name,
        "n_face": int(grid.n_face),
        "n_level": n_level,
        "variables": ["temperature"],
    }


def build_time_level(outdir: Path) -> dict[str, Any]:
    """Mesh plus a three-time, four-level field: value = 1000*t + 100*(k+1)."""
    grid = _structured_grid(np.arange(0, 360, 30.0), np.arange(-75, 76, 30.0))
    grid_file = outdir / "time_level_grid.nc"
    data_file = outdir / "time_level_data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    n_time, n_level = 3, 4
    values = np.stack(
        [
            np.stack(
                [
                    np.full(grid.n_face, 1000.0 * t + 100.0 * (k + 1))
                    for k in range(n_level)
                ]
            )
            for t in range(n_time)
        ]
    )
    xr.Dataset(
        {"temperature": (["time", "n_level", "n_face"], values, {"units": "K"})},
        coords={"time": np.arange(n_time), "n_level": np.arange(n_level)},
    ).to_netcdf(data_file)

    return {
        "name": "time_level",
        "description": (
            "Three times x four levels, value = 1000*t + 100*(level+1). The "
            "magnitude identifies the slice: wrong time is off by a thousand, "
            "wrong level by a hundred."
        ),
        "grid": grid_file.name,
        "data": data_file.name,
        "n_face": int(grid.n_face),
        "n_time": n_time,
        "n_level": n_level,
        "variables": ["temperature"],
    }


def build_regional(outdir: Path) -> dict[str, Any]:
    """Small regional mesh (~40-48E, +/-2 lat) for remap-coverage checks."""
    grid = _structured_grid(np.arange(40, 48, 2.0), np.arange(-2, 3, 1.0))
    grid_file = outdir / "regional_grid.nc"
    data_file = outdir / "regional_data.nc"
    grid.to_xarray().to_netcdf(grid_file)

    rng = np.random.default_rng(7)
    xr.Dataset(
        {
            "temperature": (
                ["n_face"],
                0.1 + 0.06 * rng.random(grid.n_face),
                {"units": "K"},
            )
        }
    ).to_netcdf(data_file)

    return {
        "name": "regional",
        "description": (
            "Regional sliver mesh covering only ~40-48E. Remapping this onto a "
            "global target should report incomplete coverage rather than "
            "silently filling."
        ),
        "grid": grid_file.name,
        "data": data_file.name,
        "n_face": int(grid.n_face),
        "variables": ["temperature"],
    }


BUILDERS = (
    build_global,
    build_earth_radius,
    build_multi_level,
    build_time_level,
    build_regional,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--outdir",
        default="/data/uxarray",
        help="Directory to write fixtures into (default: /data/uxarray).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Do not write. Re-hash existing fixtures and compare against "
            "MANIFEST.json, exiting non-zero on any drift."
        ),
    )
    args = parser.parse_args(argv)
    outdir = Path(args.outdir)

    if args.verify:
        return _verify(outdir)

    outdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for builder in BUILDERS:
        entry = builder(outdir)
        for role in ("grid", "data"):
            path = outdir / entry[role]
            entry[f"{role}_sha256"] = _content_digest(path)
            entry[f"{role}_bytes"] = path.stat().st_size
        entries.append(entry)
        print(f"  wrote {entry['name']:14} {entry['grid']} + {entry['data']}")

    manifest = {
        "schema": 1,
        "generator": "scripts/generate_container_fixtures.py",
        "note": (
            "sha256 fields hash decoded array contents, not file bytes, so "
            "they are stable across NetCDF library versions. Verify with "
            "--verify."
        ),
        "fixtures": entries,
    }
    manifest_path = outdir / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote MANIFEST.json ({len(entries)} fixtures)")
    return 0


def _verify(outdir: Path) -> int:
    """Re-hash on-disk fixtures against the recorded manifest."""
    manifest_path = outdir / "MANIFEST.json"
    if not manifest_path.exists():
        print(f"[FAIL] no manifest at {manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    drift = 0
    for entry in manifest["fixtures"]:
        for role in ("grid", "data"):
            path = outdir / entry[role]
            if not path.exists():
                print(f"[FAIL] missing {path}", file=sys.stderr)
                drift += 1
                continue
            actual = _content_digest(path)
            expected = entry[f"{role}_sha256"]
            if actual != expected:
                print(
                    f"[FAIL] {entry['name']}/{role}: {actual[:12]} != {expected[:12]}",
                    file=sys.stderr,
                )
                drift += 1

    if drift:
        print(f"[FAIL] {drift} fixture(s) drifted", file=sys.stderr)
        return 1
    print(f"[OK] {len(manifest['fixtures'])} fixtures match the manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
