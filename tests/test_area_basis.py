"""``calculate_area`` says which sphere it measured on (#30).

UXarray never applies ``sphere_radius`` to ``face_areas``. ``Grid.sphere_radius``
is a property reading ``self._ds.attrs.get("sphere_radius", 1.0)`` and nothing
in the area path consults it, so a global mesh sums to 12.566371 -- ``4*pi``
steradians -- whether its file declares an Earth radius or not. The server
returned that number with ``area_units: null``, no warning code, and a
docstring promising ``5.10064e14``.

So the areas are scaled here, and the scaling is declared. A grid that
declares its own radius supplies it; otherwise the caller passes one or the
call refuses, the same way the differential operators already refuse when
radius scaling was not applied.
"""

from __future__ import annotations

import math
import warnings

import pytest

from uxarray_mcp.domain.area import (
    UNIT_SPHERE_RADIUS,
    apply_sphere_radius,
    resolve_sphere_radius,
)
from uxarray_mcp.preconditions import OVERRIDE_TOKEN
from uxarray_mcp.tools.frontdoor import run_analysis

EARTH_RADIUS_M = 6371000.0

#: ``4*pi`` on the unit sphere, to float64. Every closed global fixture here
#: sums to this before scaling.
UNIT_SPHERE_TOTAL = 4.0 * math.pi


class _Grid:
    """Just enough grid to answer ``sphere_radius``."""

    def __init__(self, sphere_radius):
        self.sphere_radius = sphere_radius


def _unit_stats():
    return {
        "total_area": UNIT_SPHERE_TOTAL,
        "mean_area": UNIT_SPHERE_TOTAL / 8.0,
        "min_area": 1.0,
        "max_area": 2.0,
        "area_units": None,
        "n_face": 8,
    }


class TestResolveSphereRadius:
    def test_an_explicit_radius_wins_over_the_grid(self):
        assert resolve_sphere_radius(_Grid(1000.0), 2000.0) == (2000.0, "argument")

    def test_a_declared_radius_is_used_when_no_argument_is_given(self):
        assert resolve_sphere_radius(_Grid(EARTH_RADIUS_M)) == (
            EARTH_RADIUS_M,
            "grid",
        )

    def test_a_grid_declaring_the_unit_sphere_is_not_a_declaration(self):
        """``sphere_radius`` defaults to 1.0, so 1.0 means "unset"."""
        assert resolve_sphere_radius(_Grid(UNIT_SPHERE_RADIUS)) == (None, "unit_sphere")

    def test_a_grid_with_no_radius_attribute_falls_back(self):
        assert resolve_sphere_radius(object()) == (None, "unit_sphere")

    def test_an_unparseable_radius_is_treated_as_absent(self):
        """Better to refuse than to scale by whatever ``float("earth")`` did."""
        assert resolve_sphere_radius(_Grid("earth")) == (None, "unit_sphere")


class TestApplySphereRadius:
    def test_every_area_scales_by_the_square_of_the_radius(self):
        scaled = apply_sphere_radius(_unit_stats(), EARTH_RADIUS_M, "argument")
        factor = EARTH_RADIUS_M**2
        assert scaled["total_area"] == pytest.approx(UNIT_SPHERE_TOTAL * factor)
        assert scaled["mean_area"] == pytest.approx(UNIT_SPHERE_TOTAL / 8.0 * factor)
        assert scaled["min_area"] == pytest.approx(factor)
        assert scaled["max_area"] == pytest.approx(2.0 * factor)

    def test_the_face_count_is_not_an_area(self):
        scaled = apply_sphere_radius(_unit_stats(), EARTH_RADIUS_M, "argument")
        assert scaled["n_face"] == 8

    def test_the_basis_records_the_radius_and_where_it_came_from(self):
        basis = apply_sphere_radius(_unit_stats(), EARTH_RADIUS_M, "grid")["area_basis"]
        assert basis == {
            "sphere_radius": EARTH_RADIUS_M,
            "radius_source": "grid",
            "scaled": True,
        }

    def test_an_unscaled_result_still_carries_a_basis(self):
        """Absent measurement and unit-sphere measurement are different states."""
        basis = apply_sphere_radius(_unit_stats(), None, "unit_sphere")["area_basis"]
        assert basis["scaled"] is False
        assert basis["sphere_radius"] == UNIT_SPHERE_RADIUS

    def test_an_unscaled_result_keeps_its_numbers(self):
        unscaled = apply_sphere_radius(_unit_stats(), None, "unit_sphere")
        assert unscaled["total_area"] == UNIT_SPHERE_TOTAL

    def test_a_caller_supplied_radius_is_metres_so_the_units_are_stated(self):
        scaled = apply_sphere_radius(_unit_stats(), EARTH_RADIUS_M, "argument")
        assert scaled["area_units"] == "m^2"

    def test_a_grid_declared_radius_does_not_invent_units(self):
        """A file saying ``sphere_radius: 6371000.0`` never said metres."""
        scaled = apply_sphere_radius(_unit_stats(), EARTH_RADIUS_M, "grid")
        assert scaled["area_units"] is None

    def test_declared_units_are_never_overwritten(self):
        stats = _unit_stats() | {"area_units": "km^2"}
        assert apply_sphere_radius(stats, EARTH_RADIUS_M, "argument")["area_units"] == (
            "km^2"
        )


def _area(grid_path, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_analysis(operation="calculate_area", grid_path=grid_path, **kwargs)


class TestUnitSphereRefuses:
    def test_a_mesh_with_no_radius_refuses_rather_than_returning_steradians(
        self, state_dir, structured_mesh_files
    ):
        grid_file, _ = structured_mesh_files
        result = _area(grid_file)
        assert result["outcome"] == "input_required"

    def test_the_refusal_withholds_the_number(self, state_dir, structured_mesh_files):
        """#86's whole point: no number beside the warning."""
        grid_file, _ = structured_mesh_files
        assert "total_area" not in _area(grid_file)

    def test_the_repair_names_the_argument_that_lifts_it(
        self, state_dir, structured_mesh_files
    ):
        grid_file, _ = structured_mesh_files
        repair = " ".join(_area(grid_file)["refusal"]["repairs"])
        assert "sphere_radius" in repair
        assert "6371000" in repair

    def test_an_override_returns_the_steradians_and_says_so(
        self, state_dir, structured_mesh_files
    ):
        grid_file, _ = structured_mesh_files
        result = _area(grid_file, acknowledge=OVERRIDE_TOKEN)
        assert result["total_area"] == pytest.approx(UNIT_SPHERE_TOTAL, rel=1e-5)
        assert result["preconditions"]["status"] == "overridden"
        assert result["scientific_status"]["physically_interpretable"] is False


class TestScaledAreas:
    def test_an_earth_radius_gives_earths_area(self, state_dir, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        result = _area(grid_file, sphere_radius=EARTH_RADIUS_M)
        assert result["total_area"] == pytest.approx(
            4.0 * math.pi * EARTH_RADIUS_M**2, rel=1e-5
        )

    def test_a_scaled_result_is_interpretable_and_carries_units(
        self, state_dir, structured_mesh_files
    ):
        grid_file, _ = structured_mesh_files
        result = _area(grid_file, sphere_radius=EARTH_RADIUS_M)
        assert result["outcome"] == "complete"
        assert result["area_units"] == "m^2"
        assert result["scientific_status"]["physically_interpretable"] is True

    def test_the_basis_travels_with_the_number(self, state_dir, structured_mesh_files):
        grid_file, _ = structured_mesh_files
        basis = _area(grid_file, sphere_radius=EARTH_RADIUS_M)["area_basis"]
        assert basis["radius_source"] == "argument"
        assert basis["scaled"] is True


class TestGridDeclaredRadius:
    def test_a_grid_that_declares_a_radius_needs_no_argument(
        self, state_dir, earth_radius_mesh_files
    ):
        grid_file, _ = earth_radius_mesh_files
        result = _area(grid_file)
        assert result["outcome"] == "complete"
        assert result["area_basis"]["radius_source"] == "grid"

    def test_it_reaches_the_same_number_as_an_explicit_radius(
        self, state_dir, earth_radius_mesh_files
    ):
        grid_file, _ = earth_radius_mesh_files
        assert _area(grid_file)["total_area"] == pytest.approx(
            _area(grid_file, sphere_radius=EARTH_RADIUS_M)["total_area"]
        )

    def test_undeclared_units_are_a_warning_not_a_silent_assumption(
        self, state_dir, earth_radius_mesh_files
    ):
        """The file gave a radius. It never said what the radius is measured in."""
        grid_file, _ = earth_radius_mesh_files
        result = _area(grid_file)
        assert result["area_units"] is None
        assert "AREA_UNITS_UNDECLARED" in result["scientific_status"]["warning_codes"]
        assert result["scientific_status"]["physically_interpretable"] is False
