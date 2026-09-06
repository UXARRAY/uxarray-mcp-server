"""A regional total must not look like a global one (#33).

``calculate_area`` reported a patch the same way it reported the planet.
Measured on a 5-degree mesh spanning 0-40E/0-40N with
``sphere_radius=6371000.0`` passed as an argument: ``total_area``
22936016715559.137 m^2, which is 4.4967% of ``4*pi*R^2``, delivered with
``scientific_status {'status': 'complete', 'physically_interpretable':
True, 'warning_codes': []}`` and ``postconditions {'status':
'not_evaluated', 'checks': []}``. The identical call on a global mesh
returned 1.0000 of the sphere with the same status. Nothing in either
payload separated them, and the abstention -- correct in itself, since
``4*pi*R^2`` does not hold on an open mesh -- never said why it abstained.

The tests here compare the two payloads rather than checking one in
isolation, because "these two are indistinguishable" was the defect.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest
import uxarray as ux

from uxarray_mcp.domain import mesh_coverage as coverage_module
from uxarray_mcp.domain.mesh_coverage import (
    compute_mesh_coverage,
    mesh_coverage_warning_codes,
)
from uxarray_mcp.response_contract import describe_response_contract
from uxarray_mcp.tools.frontdoor import run_analysis

#: The radius the measurement above was taken on.
EARTH_RADIUS_M = 6371000.0


def _write(tmp_path, name, lon, lat):
    grid = ux.Grid.from_structured(lon=lon, lat=lat)
    path = tmp_path / f"{name}.nc"
    grid.to_xarray().to_netcdf(path)
    return str(path)


@pytest.fixture
def patch_grid_file(tmp_path):
    """The 5-degree 0-40E/0-40N patch from the measurement above."""
    return _write(tmp_path, "patch", np.arange(0, 41, 5.0), np.arange(0, 41, 5.0))


@pytest.fixture
def global_grid_file(tmp_path):
    """A closed 20-degree global mesh, for the side-by-side comparison."""
    return _write(tmp_path, "global", np.arange(0, 360, 20.0), np.arange(-80, 81, 20.0))


@pytest.fixture
def polar_hole_grid_file(tmp_path):
    """Global in longitude, 1-degree in latitude, and open at both poles.

    ``Grid.from_structured`` extends its cells half a step past the outermost
    coordinate, so latitudes running -89 to 89 in steps of 1 stop at +/-89.5
    and leave a small cap uncovered at each pole. The mesh covers 0.999963 of
    the sphere and has 720 boundary edges: geometrically complete,
    topologically open. A single "is this global" verdict would have had to
    suppress one of those two facts.
    """
    return _write(tmp_path, "polar", np.arange(0, 360, 20.0), np.arange(-89, 90, 1.0))


def _area(grid_file, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_analysis(
            operation="calculate_area",
            grid_path=grid_file,
            sphere_radius=EARTH_RADIUS_M,
            **kwargs,
        )


def _inspect(grid_file):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_analysis(operation="inspect_mesh", grid_path=grid_file)


class TestAPatchIsDistinguishableFromThePlanet:
    def test_the_two_results_disagree_about_the_sphere(
        self, state_dir, patch_grid_file, global_grid_file
    ):
        """The measurement that motivated this, asserted directly."""
        patch = _area(patch_grid_file)
        whole = _area(global_grid_file)

        assert patch["mesh_coverage"]["sphere_fraction"] == pytest.approx(
            0.044967, abs=1e-6
        )
        assert whole["mesh_coverage"]["sphere_fraction"] == pytest.approx(1.0, abs=1e-3)

        # The totals themselves stay what they always were: correct sums over
        # the faces each mesh actually has.
        assert patch["total_area"] == pytest.approx(22936016715559.137, rel=1e-9)
        assert whole["total_area"] == pytest.approx(
            4 * math.pi * EARTH_RADIUS_M**2, rel=1e-4
        )

    def test_only_the_patch_is_warned_about(
        self, state_dir, patch_grid_file, global_grid_file
    ):
        patch = _area(patch_grid_file)
        whole = _area(global_grid_file)
        assert "MESH_NOT_GLOBAL" in patch["scientific_status"]["warning_codes"]
        assert "MESH_NOT_GLOBAL" not in whole["scientific_status"]["warning_codes"]

    def test_the_patch_total_stays_interpretable(self, state_dir, patch_grid_file):
        """Warned, not refused, and not demoted.

        22936016715559 m^2 of Earth's surface between 0-40E and 0-40N is a
        true physical quantity. Flipping ``physically_interpretable`` to
        False would be a second wrong answer on top of the first: the number
        was never the problem, the missing disclosure was.
        """
        patch = _area(patch_grid_file)
        assert patch["outcome"] == "complete"
        assert patch["scientific_status"]["physically_interpretable"] is True

    def test_the_abstention_says_why(
        self, state_dir, patch_grid_file, global_grid_file
    ):
        """``not_evaluated`` alone was half the disclosure."""
        patch = _area(patch_grid_file)["postconditions"]
        assert patch["status"] == "not_evaluated"
        reason = patch["not_evaluated_because"]
        assert "closed" in reason
        assert "4.4967%" in reason

        # A mesh the identity does hold on gets the check, not a reason.
        whole = _area(global_grid_file)["postconditions"]
        assert whole["status"] == "checked"
        assert "not_evaluated_because" not in whole


class TestGeometryAndTopologyAreReportedSeparately:
    def test_a_mesh_can_be_open_and_still_cover_the_sphere(
        self, state_dir, polar_hole_grid_file
    ):
        block = _inspect(polar_hole_grid_file)["mesh_coverage"]
        assert block["sphere_fraction"] == pytest.approx(0.999963, abs=1e-5)
        assert block["closed"] is False
        # Two disks removed from a sphere: 2 - 2 = 0.
        assert block["euler_characteristic"] == 0

    def test_the_euler_characteristic_separates_a_sphere_from_a_disk(
        self, state_dir, patch_grid_file, global_grid_file
    ):
        assert _inspect(global_grid_file)["mesh_coverage"]["euler_characteristic"] == 2
        assert _inspect(patch_grid_file)["mesh_coverage"]["euler_characteristic"] == 1

    def test_a_near_global_open_mesh_is_not_warned_about(
        self, state_dir, polar_hole_grid_file
    ):
        """Missing 3.7e-5 of the sphere is not a regional patch.

        The warning exists so a caller does not read a patch total as the
        planet. Firing it on a mesh with pinhole polar caps would spend the
        caller's attention on a rounding difference.
        """
        result = _area(polar_hole_grid_file)
        assert "MESH_NOT_GLOBAL" not in result["scientific_status"]["warning_codes"]

    def test_the_identity_still_abstains_on_it_and_says_so(
        self, state_dir, polar_hole_grid_file
    ):
        """Not warned is not the same as verified.

        ``4*pi*R^2`` genuinely does not hold on a mesh with holes, however
        small, so the check abstains -- and now names the boundary rather
        than leaving an empty ``not_evaluated``.
        """
        block = _area(polar_hole_grid_file)["postconditions"]
        assert block["status"] == "not_evaluated"
        assert "boundary edge" in block["not_evaluated_because"]


class TestTopologyAbstainsRatherThanGuessing:
    def test_a_large_mesh_skips_closure_and_says_it_did(
        self, state_dir, monkeypatch, global_grid_file
    ):
        """``closed: null`` must never read as ``closed: false``.

        Counting edge incidences is a Python loop over every face: 1.43 s on
        a 196,608-face HEALPix mesh and 5.99 s at the next zoom level, on top
        of 0.76 s and 3.68 s for ``n_edge``. Above the limit the check does
        not run, and the block says that instead of reporting a verdict
        nobody computed.
        """
        monkeypatch.setattr(coverage_module, "TOPOLOGY_MAX_FACES", 1)
        block = _inspect(global_grid_file)["mesh_coverage"]
        assert block["closed"] is None
        assert block["euler_characteristic"] is None
        assert "162 faces" in block["topology_skipped"]
        # The geometric half is vectorized and stays.
        assert block["sphere_fraction"] == pytest.approx(1.0, abs=1e-3)

    def test_a_skipped_check_raises_no_warning_code(self):
        """Not knowing is not evidence of a defect."""
        assert mesh_coverage_warning_codes({"sphere_fraction": None}) == []
        assert mesh_coverage_warning_codes({}) == []

    def test_the_abstention_reason_reaches_the_postcondition_block(
        self, state_dir, monkeypatch, global_grid_file
    ):
        monkeypatch.setattr(coverage_module, "TOPOLOGY_MAX_FACES", 1)
        block = _area(global_grid_file)["postconditions"]
        assert block["status"] == "not_evaluated"
        assert "closure was not checked" in block["not_evaluated_because"]

    def test_overlapping_faces_get_their_own_code(self):
        """More surface than a sphere has is not a coverage shortfall.

        Quadrature error is ~2e-6 on a coarse global mesh, three orders
        below the tolerance, so a fraction above 1.001 means faces are
        stored twice or overlap -- a different defect from a patch.
        """
        assert mesh_coverage_warning_codes({"sphere_fraction": 1.05}) == [
            "MESH_COVERAGE_EXCEEDS_SPHERE"
        ]


class TestInspectMeshDescribesWithoutJudging:
    def test_inspect_mesh_carries_the_block(self, state_dir, patch_grid_file):
        """Counts alone never said which part of the sphere they counted."""
        result = _inspect(patch_grid_file)
        assert result["mesh_coverage"]["sphere_fraction"] == pytest.approx(
            0.044967, abs=1e-6
        )
        assert result["mesh_coverage"]["lat_extent"] == [-2.5, 42.5]

    def test_inspecting_a_regional_mesh_is_not_a_warning(
        self, state_dir, patch_grid_file
    ):
        """The code fires where a number is claimed, not where one is described.

        ``inspect_mesh`` reports what a mesh is. A regional mesh is not a
        problem to be flagged; it becomes one only when a scalar total is
        presented as if it covered the planet.
        """
        status = _inspect(patch_grid_file)["scientific_status"]
        assert status["warning_codes"] == []
        assert status["status"] == "complete"


class TestTheBlockIsDeclared:
    @pytest.mark.parametrize("operation", ["calculate_area", "inspect_mesh"])
    def test_the_contract_declares_mesh_coverage(self, operation):
        contract = describe_response_contract(operation)
        declared = {field["name"] for field in contract["fields"]}
        assert "mesh_coverage" in declared
        assert "mesh_coverage" not in contract["required"]

    def test_a_mocked_grid_yields_nulls_rather_than_an_exception(self):
        """A worker sending something grid-shaped must not crash the block."""
        block = compute_mesh_coverage(object())
        assert block["sphere_fraction"] is None
        assert block["closed"] is None
