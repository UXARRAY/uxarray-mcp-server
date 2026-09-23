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
    remote_temporal_mean_map,
)

#: The payloads whose self-containment is checked. ``remote_temporal_mean_map``
#: is here because it carries the largest inlined copy of domain code (the
#: weights-file adapter) and is also what the *local* temporal-mean plot runs.
SELF_CONTAINED = (remote_inspect_mesh, remote_calculate_area, remote_temporal_mean_map)

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
        """The payload must not *import* uxarray_mcp; the worker has none.

        Naming it is allowed in two narrow forms that cannot raise on a
        worker without the package:

        - ``importlib.util.find_spec("uxarray_mcp...")`` returns ``None``
          rather than importing, and is how a function discovers where the
          installed source lives in order to report its commit.
        - comments, which do not execute.

        Anything else -- ``import uxarray_mcp``, ``from uxarray_mcp import``,
        an attribute access on the module -- is the failure this guards, and
        it is a real one: the worker resolves such a name against its own
        installed copy, so a fix shipped by value appears to do nothing.
        """
        import inspect
        import re

        for function in SELF_CONTAINED:
            code = "\n".join(
                line.split("#", 1)[0]
                for line in inspect.getsource(function).splitlines()
            )
            # Drop find_spec(...) calls before looking, rather than filtering
            # line by line: the formatter puts the module name on its own
            # line, so a per-line test cannot see the call it belongs to.
            without_find_spec = re.sub(
                r"find_spec\(\s*[^)]*\)", "find_spec(...)", code, flags=re.S
            )
            offenders = [
                line for line in without_find_spec.splitlines() if "uxarray_mcp" in line
            ]
            assert offenders == [], (function.__name__, offenders)

    def test_the_commit_probe_cannot_raise_without_the_package(self):
        """``find_spec`` on an absent package returns None, it does not raise.

        That is the whole reason it is allowed above, so it is checked
        rather than assumed. The check holds only for the top-level
        spelling: ``find_spec("absent.sub")`` imports the parent to resolve
        the child and raises ``ModuleNotFoundError`` when there is none. The
        probe must therefore name the package, never a submodule, and this
        test pins the spelling the payload actually uses.
        """
        import importlib.util
        import inspect

        assert importlib.util.find_spec("a_package_no_worker_has") is None
        with pytest.raises(ModuleNotFoundError):
            importlib.util.find_spec("a_package_no_worker_has.provenance")

        for function in SELF_CONTAINED:
            source = inspect.getsource(function)
            assert 'find_spec("uxarray_mcp")' in source, function.__name__
            assert 'find_spec("uxarray_mcp.' not in source, function.__name__

    def test_an_empty_origin_reports_unknown_not_the_cwd(self):
        """``git -C ""`` is a no-op, so a missing origin must never reach git.

        With no package, ``find_spec`` yields no origin and the dirname is
        the empty string. ``git -C "" rev-parse`` then answers for whatever
        repository the worker's cwd happens to sit in -- a real-looking
        commit for the wrong code. The probe short-circuits to "unknown"
        before calling git; this runs each payload's probe with an empty
        origin to prove it.
        """
        import inspect
        import re

        for function in SELF_CONTAINED:
            source = inspect.getsource(function)
            probe = re.search(r"lambda _d:.*?\)\(\s*str\(", source, flags=re.S)
            assert probe is not None, function.__name__
            body = re.sub(r"\s+", " ", probe.group(0))
            assert '"git"' in body, function.__name__
            assert 'if _d else "unknown"' in body, function.__name__

    def test_the_size_guard_is_the_same_number_in_all_three_copies(self):
        import inspect

        from uxarray_mcp.domain import mesh_coverage as local

        limit = str(local.TOPOLOGY_MAX_FACES)
        for function in (remote_inspect_mesh, remote_calculate_area):
            source = inspect.getsource(function).replace("_", "")
            assert limit.replace("_", "") in source, function.__name__
