"""The worker's copy of ``mesh_coverage`` must agree with the local one.

``AllCodeStrategies`` ships one function's code and nothing else, so a
compute function cannot import ``uxarray_mcp``; the coverage measurement is
nested inside ``remote_inspect_mesh`` and ``remote_calculate_area`` as a
literal second and third copy of ``domain/mesh_coverage.py``. Three copies
of an algorithm drift, and the drift would be invisible: a remote reply that
disagreed with a local one about whether a mesh is global would look like a
finding about the mesh.

These tests are the thing standing between them. They run the compute
functions in-process -- they are plain Python and need no endpoint -- and
compare their block to the local one key by key.

The gap they close was measured on the shipped code before this change: a
remote ``calculate_area`` reply carried no ``mesh_coverage`` at all, so
``mesh_coverage_warning_codes`` saw an empty dict and ``MESH_NOT_GLOBAL``
could not fire on any HPC result, whatever the mesh.
"""

from __future__ import annotations

import numpy as np
import pytest

from uxarray_mcp.domain.mesh_coverage import (
    compute_mesh_coverage,
    mesh_coverage_warning_codes,
)
from uxarray_mcp.remote.compute_functions import (
    remote_calculate_area,
    remote_inspect_mesh,
)

ux = pytest.importorskip("uxarray")

#: Mirrors tests/test_mesh_coverage.py: a global mesh, a regional patch, and
#: a structured grid that stops half a cell short of each pole.
GRIDS = {
    "global": (np.arange(0, 360, 20.0), np.arange(-80, 81, 20.0)),
    "patch": (np.arange(0, 41, 5.0), np.arange(0, 41, 5.0)),
    "polar_hole": (np.arange(0, 360, 20.0), np.arange(-89, 90, 1.0)),
}


@pytest.fixture(scope="module")
def grid_files(tmp_path_factory):
    directory = tmp_path_factory.mktemp("remote-coverage")
    written = {}
    for name, (lon, lat) in GRIDS.items():
        path = directory / f"{name}.nc"
        ux.Grid.from_structured(lon=lon, lat=lat).to_xarray().to_netcdf(path)
        written[name] = str(path)
    return written


def _local(path):
    return compute_mesh_coverage(ux.open_grid(path))


class TestTheThreeCopiesAgree:
    @pytest.mark.parametrize("name", sorted(GRIDS))
    def test_remote_inspect_mesh_matches_the_local_block(self, grid_files, name):
        remote = remote_inspect_mesh(grid_files[name])["mesh_coverage"]
        assert remote == _local(grid_files[name])

    @pytest.mark.parametrize("name", sorted(GRIDS))
    def test_remote_calculate_area_matches_the_local_block(self, grid_files, name):
        remote = remote_calculate_area(grid_files[name])["mesh_coverage"]
        assert remote == _local(grid_files[name])

    def test_the_two_remote_copies_agree_with_each_other(self, grid_files):
        path = grid_files["polar_hole"]
        assert (
            remote_inspect_mesh(path)["mesh_coverage"]
            == remote_calculate_area(path)["mesh_coverage"]
        )


class TestAWorkerResultCanNowBeWarnedAbout:
    def test_a_remote_patch_raises_the_code(self, grid_files):
        result = remote_calculate_area(grid_files["patch"])
        codes = mesh_coverage_warning_codes(result["mesh_coverage"])
        assert codes == ["MESH_NOT_GLOBAL"]
        # The fraction is the one the local path measures on the same mesh.
        assert result["mesh_coverage"]["sphere_fraction"] == pytest.approx(
            0.044967, abs=1e-6
        )

    def test_a_remote_global_mesh_raises_nothing(self, grid_files):
        result = remote_calculate_area(grid_files["global"])
        assert mesh_coverage_warning_codes(result["mesh_coverage"]) == []
        assert result["mesh_coverage"]["closed"] is True

    def test_the_remote_total_is_still_on_the_unit_sphere(self, grid_files):
        # mesh_coverage is attached before any radius is applied locally, so
        # sphere_fraction and total_area describe the same measurement.
        result = remote_calculate_area(grid_files["global"])
        assert result["total_area"] == pytest.approx(4.0 * np.pi, rel=1e-5)
        assert result["mesh_coverage"]["sphere_fraction"] == pytest.approx(
            1.0, abs=1e-5
        )


class TestTheWorkerCopyIsSelfContained:
    def test_neither_function_imports_uxarray_mcp(self):
        import inspect

        # Comments name the package on purpose; an executable line that
        # imports it would fail on a worker that has only uxarray.
        for function in (remote_inspect_mesh, remote_calculate_area):
            code = [
                line.split("#", 1)[0]
                for line in inspect.getsource(function).splitlines()
            ]
            offenders = [line for line in code if "uxarray_mcp" in line]
            assert offenders == [], (function.__name__, offenders)

    def test_the_size_guard_is_the_same_number_in_all_three_copies(self):
        import inspect

        from uxarray_mcp.domain import mesh_coverage as local

        limit = str(local.TOPOLOGY_MAX_FACES)
        for function in (remote_inspect_mesh, remote_calculate_area):
            source = inspect.getsource(function).replace("_", "")
            assert limit.replace("_", "") in source, function.__name__
