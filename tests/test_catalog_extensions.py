"""Discovery has to list the formats the server can actually open.

`list_datasets` matched only NetCDF, HDF5 and GRIB, so Exodus meshes were
invisible to it even though UXarray reads them and `inspect_mesh` opens them
without complaint. Scanning the 2026 INCITE CONUS grid directory on Chrysalis
reported 24 files where `ls` shows 42; the 18 it dropped were every `.g` mesh
in the set, including the coarse SE meshes the finer grids are refined from.
A caller cannot tell that kind of silence apart from an empty directory.

The scan exists twice -- once locally, once inlined into
``_remote_catalog_fn`` because ``AllCodeStrategies`` ships that function's
source and nothing else -- so these tests also hold the two copies together.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from uxarray_mcp.tools import catalog


def _worker_literal(name: str) -> set[str]:
    """Read one set literal out of the inlined worker function's source."""
    tree = ast.parse(inspect.getsource(catalog._remote_catalog_fn))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if name in targets:
                return set(ast.literal_eval(node.value))
    raise AssertionError(f"{name} not assigned in _remote_catalog_fn")


@pytest.mark.parametrize(
    "name", ["_MESH_EXTENSIONS", "_MESH_ONLY_EXTENSIONS", "_GRID_HINTS", "_DATA_HINTS"]
)
def test_the_worker_copy_matches_the_local_one(name):
    """Two copies of a scan that disagree would list different directories."""
    assert _worker_literal(name) == getattr(catalog, name), (
        f"{name} has drifted between the local scan and the inlined worker copy"
    )


@pytest.mark.parametrize("suffix", [".g", ".exo", ".e"])
def test_exodus_is_a_format_discovery_reports(suffix):
    assert suffix in catalog._MESH_EXTENSIONS


def test_a_directory_of_exodus_meshes_is_not_reported_as_empty(tmp_path):
    """The failure this fixes: real meshes present, discovery says nothing."""
    for name in ("ne30.g", "2026-incite-conus-128x2.g", "coarse.exo"):
        (tmp_path / name).write_bytes(b"\x00" * 16)

    result = catalog.list_datasets(str(tmp_path))

    assert result["total_files"] == 3
    listed = {f["name"] for group in result["groups"] for f in group["files"]}
    assert listed == {"ne30.g", "2026-incite-conus-128x2.g", "coarse.exo"}


def test_an_exodus_file_is_classified_as_a_grid_whatever_it_is_called(tmp_path):
    """Exodus carries topology and no data variables.

    ``2026-incite-conus-1024x4.g`` contains none of the grid hint words, so
    the substring heuristic alone would file it as "unknown" and suggest the
    caller pair it with something. The extension settles it.
    """
    assert catalog._classify("2026-incite-conus-1024x4.g") == "grid"
    assert catalog._classify("model_output_history.g") == "grid", (
        "a filename hint must not outrank a format that cannot hold data"
    )
    assert catalog._classify("wibble.nc") == "unknown"


def test_the_scan_still_finds_netcdf(tmp_path):
    """Adding formats must not drop the ones that already worked."""
    (tmp_path / "mesh_grid.nc").write_bytes(b"\x00" * 16)
    (tmp_path / "output_data.h5").write_bytes(b"\x00" * 16)

    result = catalog.list_datasets(str(tmp_path))
    by_name = {
        f["name"]: f["kind"] for group in result["groups"] for f in group["files"]
    }
    assert by_name == {"mesh_grid.nc": "grid", "output_data.h5": "data"}


def test_a_scrip_mesh_is_recognised_as_a_grid():
    """SCRIP is a mesh convention, and E3SM names half its meshes with it."""
    assert catalog._classify("2026-incite-conus-1024x2-pg2_scrip.nc") == "grid"
    assert catalog._classify("ne30pg2_scrip.nc") == "grid"
    assert catalog._classify("map_ne30_to_ne120.esmf.nc") == "grid"


def test_a_directory_of_meshes_is_told_what_to_do_with_them(tmp_path):
    """The failure: 24 meshes found, all "unknown", zero recommendations.

    Scanning the INCITE tree classified nothing and advised nothing, which
    is less help than the empty-directory branch gives.
    """
    for name in ("2026-incite-conus-1024x2-pg2_scrip.nc", "ne3000pg1_scrip.nc"):
        (tmp_path / name).write_bytes(b"\x00" * 16)

    result = catalog.list_datasets(str(tmp_path))

    kinds = {f["kind"] for group in result["groups"] for f in group["files"]}
    assert kinds == {"grid"}
    assert result["recommendations"], "meshes found and nothing suggested"


def test_files_matching_no_hint_still_earn_advice(tmp_path):
    """A name the heuristics miss must not produce silence."""
    (tmp_path / "wibble.nc").write_bytes(b"\x00" * 16)

    result = catalog.list_datasets(str(tmp_path))

    assert result["recommendations"], (
        "an unclassifiable file left the caller with no next step at all"
    )
    assert "1 candidate" in result["recommendations"][0]


def test_every_discovered_extension_is_one_uxarray_can_open():
    """Discovery that names a file the server cannot open is a false lead."""
    unopenable = catalog._MESH_EXTENSIONS - {
        ".nc",
        ".nc4",
        ".h5",
        ".he5",
        ".grb",
        ".grib",
        ".g",
        ".exo",
        ".e",
    }
    assert not unopenable, (
        f"extensions added to discovery with no reader behind them: {unopenable}"
    )
    assert Path("x.g").suffix in catalog._MESH_ONLY_EXTENSIONS
